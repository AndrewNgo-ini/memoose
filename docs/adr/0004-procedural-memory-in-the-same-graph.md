---
status: accepted
extends: ADR 0001 (the store stays deterministic), ADR 0003 (the hint hook gains a second key)
source: Lu, Chen, Wu, Arik. "Procedural Graphs: Self-Evolving Execution Structures for LLM Agents." arXiv:2609.09153, Google, 2026.
---

# Procedural memory is a subgraph of the knowledge graph, localised on the agent's last action

Facts answer *what is*. Long-horizon agents also fail on *what to do next*: they lose the order of
steps, skip a check, and repeat a step that already failed. The Procedural Graphs paper stores that
knowledge as (procedure, relation, procedure) triplets with condition, guidance and pitfall text on
each edge, localises the agent's most recent action on a node, and hands the agent the two-hop
outgoing neighbourhood as guidance. Its ablation is the finding that matters for us: the *local*
subgraph beat the whole graph on every benchmark, and injecting the whole graph lowered task success
on the embodied one. Guidance has to be keyed on where the agent is, and it has to be small.

## Decision

1. **Procedures live in the same graph, under a `Procedure` entity type.** No second store, no
   second schema. The relation vocabulary already expresses transitions (`leads_to`, `requires`,
   `triggers`, `converges_to`), and a relation's description carries the paper's three attributes
   as one sentence: `When <condition>: <guidance>. Avoid: <pitfall>.` The same supersession,
   provenance and contradiction machinery applies to a transition as to any other fact, which is
   what makes a failed transition *history* rather than deleted.
2. **The hint hook localises on the last action.** `hooks/recommend.py` reads the agent's most
   recent tool calls from the transcript, matches one lexically to a `Procedure` (at least two of
   the action's tokens must appear in the node), and injects that node's outgoing transitions two
   hops out, grouped by hop. Outgoing only: predecessors are what the agent already did. The
   prompt-keyed BM25 hint still follows it. No model call; the host's model is the guidance model.
3. **Rejection memory, in the ledger.** A maintenance candidate the model judged and declined is
   recorded as a `dismiss` event in provenance with its reason. `maintain` and
   `contradiction_candidates` filter on it and show recent reasons as negative evidence. This is the
   paper's step 4 and it closes a real defect: the pass re-proposed the same judged pairs forever.
4. **Contrastive distillation is a skill rule, not code.** When a session held a failure then a
   success, the lesson is written as `Procedure` edges and the failing transition is superseded.

## What we did not adopt

- **The validation gate.** The paper accepts a graph edit only if it does not lower a held-out
  score. An agent's project memory has no task distribution to score against. The nearest
  honest signal is a user correction, which the existing feedback weights can carry; we are not
  going to pretend a gate exists where one cannot be measured.
- **A separate guidance model call.** The paper runs a guidance LLM per step. Under ADR 0001 the
  library never calls a model; the hook serialises the subgraph and the host's model reads it.
- **Exact matching on tool names.** Their tasks have rich tool catalogues; ours has Bash, Read and
  Edit, which identify nothing. We match on the command text instead, with a two-token floor so a
  wrong match cannot steer the agent.

## Consequences

A procedure is a handful of edges (the paper's graphs have 7 to 17 nodes), written by the same
`remember` and read by the same `recall`. The cost is one more thing for the extraction skill to
teach, and a hint hook that now reads the transcript as well as the prompt. Whether an agent
actually follows the guidance is not yet verified live; it is on the same list as the rewritten
capture prompt.
