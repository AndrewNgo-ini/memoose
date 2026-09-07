"""Cases for the maintained-memory benchmark.

Each case builds a small history with the real MCP-facing API and then asserts on what
comes back. No model is involved anywhere: the questions are about whether the store
keeps a body of facts *trustworthy over time*, which is decidable by reading the payload.

Five claims, taken from VISION.md, one per section below:

  currency    A fact changed. Does recall return the current one?
  history     Can it still show me the old one, and why it changed?
  conflict    Two sources disagree. Does the system say so, or silently pick one?
  provenance  Why do we believe this? Point at the evidence.
  reuse       We solved this before. Does the lesson come back?

Four cases are **negative controls** (`negative=True`): they assert the system does *not*
do something. A benchmark that only rewards flagging would be passed by a system that flags
everything, and one that only rewards supersession would be passed by a system that
overwrites blindly. The controls are what make the score mean something.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from mnemoth.models import EntityIn, LessonIn, RelationIn

CLAIMS = {
    "currency": "A fact changed. Does recall return the current one?",
    "history": "Can it still show me the old one, and why it changed?",
    "conflict": "Two sources disagree. Does the system say so, or silently pick one?",
    "provenance": "Why do we believe this? Point at the evidence.",
    "reuse": "We solved this before. Does the lesson come back?",
}


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class Case:
    id: str
    claim: str
    asks: str
    fn: Callable
    negative: bool = False


CASES: list[Case] = []


def case(claim: str, cid: str, asks: str, negative: bool = False):
    def deco(fn):
        CASES.append(Case(f"{claim}/{cid}", claim, asks, fn, negative))
        return fn

    return deco


# ----- helpers -------------------------------------------------------------------------
def person(name: str, what: str = "") -> EntityIn:
    return EntityIn(name=name, type="Person", description=what)


def system(name: str, what: str = "") -> EntityIn:
    return EntityIn(name=name, type="System", description=what)


def facts_of(res: dict) -> list[str]:
    return [f["fact"] for f in res.get("facts", [])]


def fact_with(res: dict, relation: str, target: str) -> dict | None:
    return next((f for f in res.get("facts", []) if f["relation"] == relation and f["target"] == target), None)


def own(what: str, who: str, when: str, evidence: str) -> RelationIn:
    """`what --owned_by--> who`. Subject is the thing owned, so successive owners share a subject."""
    return RelationIn(
        source=what, name="owned_by", target=who,
        description=f"{what} is owned by {who} as of {when}.",
        evidence=evidence, valid_from=when,
    )


def _owner_history(ds, *, functional: bool = True) -> dict[str, str]:
    """Three successive owners of billing-service, plus a distractor service. Returns relation ids."""
    if functional:
        ds.declare_functional_relations(["owned_by"])
    ids: dict[str, str] = {}
    ds.remember(
        entities=[system("billing-service", "Charges customers."), system("search-service", "Serves queries."), person("Priya"), person("Tomas")],
        relations=[
            RelationIn(source="billing-service", name="owned_by", target="Priya", description="billing-service is owned by Priya as of 2024-01-15.", evidence="handover doc 2024-01-15", valid_from="2024-01-15"),
            RelationIn(source="search-service", name="owned_by", target="Tomas", description="search-service is owned by Tomas as of 2024-01-15.", evidence="handover doc 2024-01-15", valid_from="2024-01-15"),
        ],
        summary="Ownership as of January 2024: Priya on billing-service, Tomas on search-service.",
        source_text="[2024-01-15] Priya takes billing-service. Tomas keeps search-service.",
        source="handover-2024-01",
    )
    out = ds.remember(
        entities=[person("Wei")],
        relations=[RelationIn(source="billing-service", name="owned_by", target="Wei", description="billing-service is owned by Wei as of 2024-06-01.", evidence="rota 2024-06-01", valid_from="2024-06-01")],
        summary="Wei took billing-service from Priya in June 2024.",
        source_text="[2024-06-01] Wei takes over billing-service from Priya.",
        source="rota-2024-06",
    )
    ids["wei"] = out["relations"][0]["id"]
    out = ds.remember(
        entities=[person("Dana")],
        relations=[RelationIn(source="billing-service", name="owned_by", target="Dana", description="billing-service is owned by Dana as of 2025-02-10.", evidence="rota 2025-02-10", valid_from="2025-02-10")],
        summary="Dana took billing-service from Wei in February 2025.",
        source_text="[2025-02-10] Dana takes over billing-service from Wei.",
        source="rota-2025-02",
    )
    ids["dana"] = out["relations"][0]["id"]
    ids["superseded_by_last_write"] = ",".join(s["relation_id"] for s in out["superseded"])
    return ids


# ===== currency ========================================================================
@case("currency", "functional-supersedes", "Two owners in sequence: does recall name the second?")
def _(ds) -> list[Check]:
    ds.declare_functional_relations(["owned_by"])
    ds.remember(
        entities=[system("billing-service"), person("Priya")],
        relations=[own("billing-service", "Priya", "2024-01-15", "handover doc")],
    )
    out = ds.remember(
        entities=[person("Wei")],
        relations=[RelationIn(source="billing-service", name="owned_by", target="Wei", description="billing-service is owned by Wei as of 2024-06-01.", evidence="rota", valid_from="2024-06-01")],
    )
    res = ds.recall("who owns billing-service?", mode="facts", limit=20)
    return [
        Check("remember reported the supersession", bool(out["superseded"]), f"superseded={out['superseded']}"),
        Check("current owner is recalled", fact_with(res, "owned_by", "Wei") is not None, str(facts_of(res))),
        Check("previous owner is not recalled by default", fact_with(res, "owned_by", "Priya") is None, str(facts_of(res))),
    ]


@case("currency", "three-generations-with-distractor", "Three owners over 13 months, and another service alongside: only the newest is current.")
def _(ds) -> list[Check]:
    _owner_history(ds)
    res = ds.recall("who owns billing-service?", mode="facts", limit=20)
    others = ds.recall("who owns search-service?", mode="facts", limit=20)
    return [
        Check("newest owner is recalled", fact_with(res, "owned_by", "Dana") is not None, str(facts_of(res))),
        Check("both earlier owners are gone from default recall", fact_with(res, "owned_by", "Wei") is None and fact_with(res, "owned_by", "Priya") is None, str(facts_of(res))),
        Check("the distractor service kept its own owner", fact_with(others, "owned_by", "Tomas") is not None, str(facts_of(others))),
    ]


@case("currency", "non-functional-is-not-silently-picked", "A relation that legitimately holds many values must NOT be superseded.", negative=True)
def _(ds) -> list[Check]:
    ds.remember(
        entities=[person("Priya"), system("billing-service"), EntityIn(name="Postgres", type="Technology"), EntityIn(name="Redis", type="Technology")],
        relations=[RelationIn(source="billing-service", name="depends_on", target="Postgres", description="billing-service depends on Postgres.", evidence="repo://pyproject.toml")],
    )
    out = ds.remember(
        entities=[],
        relations=[RelationIn(source="billing-service", name="depends_on", target="Redis", description="billing-service depends on Redis.", evidence="repo://pyproject.toml")],
    )
    res = ds.recall("what does billing-service depend on?", mode="facts", limit=20)
    return [
        Check("nothing was superseded", not out["superseded"], f"superseded={out['superseded']}"),
        Check("both dependencies are still current", fact_with(res, "depends_on", "Postgres") is not None and fact_with(res, "depends_on", "Redis") is not None, str(facts_of(res))),
        Check("the multi-valued subject is raised as a hotspot to judge", bool(out["hotspots"]), f"hotspots={len(out['hotspots'])}"),
    ]


@case("currency", "explicit-supersede", "For a relation nobody declared functional, an explicit supersede must still take effect.")
def _(ds) -> list[Check]:
    a = ds.remember(
        entities=[system("billing-service"), EntityIn(name="eu-west-1", type="Place"), EntityIn(name="eu-central-1", type="Place")],
        relations=[RelationIn(source="billing-service", name="deployed_in", target="eu-west-1", description="billing-service is deployed in eu-west-1.", evidence="terraform 2024-03")],
    )["relations"][0]["id"]
    b = ds.remember(
        entities=[],
        relations=[RelationIn(source="billing-service", name="deployed_in", target="eu-central-1", description="billing-service is deployed in eu-central-1 after the migration.", evidence="terraform 2025-01")],
    )["relations"][0]["id"]
    before = ds.recall("where is billing-service deployed?", mode="facts", limit=20)
    out = ds.supersede(a, b, "the eu-west-1 deployment was migrated to eu-central-1 in January 2025")
    after = ds.recall("where is billing-service deployed?", mode="facts", limit=20)
    return [
        Check("both regions were current before the judgment", fact_with(before, "deployed_in", "eu-west-1") is not None and fact_with(before, "deployed_in", "eu-central-1") is not None, str(facts_of(before))),
        Check("supersede reported success", out["superseded"] is True, str(out)),
        Check("the old region left default recall", fact_with(after, "deployed_in", "eu-west-1") is None, str(facts_of(after))),
        Check("the new region stayed", fact_with(after, "deployed_in", "eu-central-1") is not None, str(facts_of(after))),
    ]


@case("currency", "late-arriving-old-fact", "An older fact learned late must not displace the newer one it predates.")
def _(ds) -> list[Check]:
    ds.declare_functional_relations(["owned_by"])
    ds.remember(
        entities=[system("billing-service"), person("Dana")],
        relations=[RelationIn(source="billing-service", name="owned_by", target="Dana", description="billing-service is owned by Dana as of 2025-02-10.", evidence="rota 2025-02", valid_from="2025-02-10")],
    )
    # Only now do we learn who owned it in 2024. It is older by valid_from, newer by write order.
    out = ds.remember(
        entities=[person("Priya")],
        relations=[RelationIn(source="billing-service", name="owned_by", target="Priya", description="billing-service was owned by Priya as of 2024-01-15.", evidence="handover doc 2024-01", valid_from="2024-01-15")],
    )
    out_rel_id = out["relations"][0]["id"]
    res = ds.recall("who owns billing-service?", mode="facts", limit=20)
    current = fact_with(res, "owned_by", "Dana")
    return [
        Check("the 2025 owner is still the current one", current is not None, str(facts_of(res))),
        Check("the backfilled 2024 owner is not current", fact_with(res, "owned_by", "Priya") is None, str(facts_of(res))),
        Check("the backfilled fact was recorded as the superseded one", [r["relation_id"] for r in out["superseded"]] == [out_rel_id], f"superseded={out['superseded']}"),
    ]


# ===== history =========================================================================
@case("history", "superseded-still-retrievable", "Ask for history and the replaced fact comes back, flagged and linked to its replacement.")
def _(ds) -> list[Check]:
    ids = _owner_history(ds)
    res = ds.recall("who owns billing-service?", mode="facts", limit=30, include_superseded=True)
    priya = fact_with(res, "owned_by", "Priya")
    wei = fact_with(res, "owned_by", "Wei")
    return [
        Check("the first owner is retrievable on request", priya is not None, str(facts_of(res))),
        Check("the middle owner is retrievable on request", wei is not None, str(facts_of(res))),
        Check("replaced facts are flagged superseded", bool(priya and priya["superseded"]) and bool(wei and wei["superseded"]), f"priya={priya and priya['superseded']} wei={wei and wei['superseded']}"),
        Check("each points at what replaced it", bool(wei and wei["superseded_by"] == ids["dana"]), f"superseded_by={wei and wei['superseded_by']}"),
        Check("the replaced facts kept their own evidence", bool(priya and priya["evidence"]) and bool(wei and wei["evidence"]), f"priya={priya and priya['evidence']!r} wei={wei and wei['evidence']!r}"),
    ]


@case("history", "change-is-explained", "The ledger says the fact was superseded, by which fact, and why.")
def _(ds) -> list[Check]:
    ids = _owner_history(ds)
    events = ds.history(entity="billing-service", limit=100)["events"]
    sup = [e for e in events if e["action"] == "supersede"]
    payloads = [str(e.get("data") or e) for e in sup]
    return [
        Check("both handovers are in the ledger", len(sup) >= 2, f"{len(sup)} supersede events"),
        Check("each supersession names its replacement", all("superseded_by" in p for p in payloads), str(payloads)[:300]),
        Check("each supersession carries a reason", all("reason" in p for p in payloads), str(payloads)[:300]),
        Check("the ledger is ordered newest first", [e["at"] for e in events] == sorted((e["at"] for e in events), reverse=True), "out of order" if events else "no events"),
    ]


@case("history", "nothing-true-is-deleted", "After two handovers, all three facts are still stored.")
def _(ds) -> list[Check]:
    _owner_history(ds)
    stats = ds.store.stats()
    inc = ds.recall("who owns billing-service?", mode="facts", limit=30, include_superseded=True)
    owners = {f["target"] for f in inc.get("facts", []) if f["relation"] == "owned_by" and f["source"] == "billing-service"}
    return [
        Check("all four ownership facts are still in the store", stats["relations"] + stats["superseded_relations"] >= 4, f"current={stats['relations']} superseded={stats['superseded_relations']}"),
        Check("the two replaced facts are held as superseded, not dropped", stats["superseded_relations"] == 2, f"superseded={stats['superseded_relations']}"),
        Check("all three billing-service owners are recoverable", owners == {"Priya", "Wei", "Dana"}, f"owners={sorted(owners)}"),
    ]


# ===== conflict ========================================================================
@case("conflict", "hotspot-surfaced", "Two sources give different answers to the same question: is the clash offered up?")
def _(ds) -> list[Check]:
    ds.remember(
        entities=[system("billing-service"), EntityIn(name="Stripe", type="Technology"), EntityIn(name="Adyen", type="Technology")],
        relations=[RelationIn(source="billing-service", name="charges_through", target="Stripe", description="billing-service charges customers through Stripe.", evidence="repo://src/billing/gateway.py#L12-L40")],
    )
    out = ds.remember(
        entities=[],
        relations=[RelationIn(source="billing-service", name="charges_through", target="Adyen", description="billing-service charges customers through Adyen.", evidence="ARCHITECTURE.md#payments")],
    )
    cands = ds.contradiction_candidates(entity_names=["billing-service"])
    spots = cands["hotspots"]
    targets = {f["object"] for s in spots for f in s["facts"]}
    return [
        Check("remember warned that a subject now holds two values", any("several values" in w for w in out["warnings"]), str(out["warnings"])),
        Check("the clash is offered as a hotspot", len(spots) == 1, f"{len(spots)} hotspots: {[s['subject_relation'] for s in spots]}"),
        Check("the hotspot groups both competing values", targets == {"Stripe", "Adyen"}, f"targets={sorted(targets)}"),
        Check("the hotspot carries each side's evidence so it can be judged", all(f["evidence"] for s in spots for f in s["facts"]), str([f["evidence"] for s in spots for f in s["facts"]])),
    ]


@case("conflict", "contested-after-judgment", "Once judged incompatible, both facts come back marked contested rather than one being hidden.")
def _(ds) -> list[Check]:
    a = ds.remember(
        entities=[system("billing-service"), EntityIn(name="Stripe", type="Technology"), EntityIn(name="Adyen", type="Technology")],
        relations=[RelationIn(source="billing-service", name="charges_through", target="Stripe", description="billing-service charges customers through Stripe.", evidence="repo://src/billing/gateway.py")],
    )["relations"][0]["id"]
    b = ds.remember(entities=[], relations=[RelationIn(source="billing-service", name="charges_through", target="Adyen", description="billing-service charges customers through Adyen.", evidence="ARCHITECTURE.md")])["relations"][0]["id"]
    marked = ds.mark_contradiction(a, b, "the code and the architecture doc name different payment gateways; both claim to be current", 0.9)
    res = ds.recall("how does billing-service charge customers?", mode="facts", limit=20)
    stripe, adyen = fact_with(res, "charges_through", "Stripe"), fact_with(res, "charges_through", "Adyen")
    open_ = ds.contradiction_candidates()["open_contradictions"]
    return [
        Check("the contradiction was recorded", bool(marked["contradiction_id"]), str(marked)),
        Check("neither side was hidden", stripe is not None and adyen is not None, str(facts_of(res))),
        Check("both sides are marked contested", bool(stripe and stripe["contested"]) and bool(adyen and adyen["contested"]), f"stripe={stripe and stripe['contested']} adyen={adyen and adyen['contested']}"),
        Check("it stays on the open list until someone decides", any(c["first_relation_id"] == a for c in open_), f"{len(open_)} open"),
        Check("the reason is stored with it", any("payment gateways" in (c.get("reason") or "") for c in open_), str([c.get("reason") for c in open_])[:200]),
    ]


@case("conflict", "compatible-facts-are-not-flagged", "Facts that merely differ must not be reported as a clash.", negative=True)
def _(ds) -> list[Check]:
    out = ds.remember(
        entities=[person("Priya"), system("billing-service"), EntityIn(name="Payments", type="Topic"), EntityIn(name="Postgres", type="Technology")],
        relations=[
            RelationIn(source="Priya", name="owns", target="billing-service", description="Priya owns billing-service.", evidence="rota"),
            RelationIn(source="Priya", name="works_on", target="Payments", description="Priya works on the Payments topic.", evidence="rota"),
            RelationIn(source="billing-service", name="depends_on", target="Postgres", description="billing-service depends on Postgres.", evidence="repo://pyproject.toml"),
        ],
    )
    cands = ds.contradiction_candidates(entity_names=["Priya", "billing-service"])
    return [
        Check("no hotspot from three compatible facts", not cands["hotspots"], f"hotspots={[s['subject_relation'] for s in cands['hotspots']]}"),
        Check("no warning about multiple values", not any("several values" in w for w in out["warnings"]), str(out["warnings"])),
        Check("nothing is contested", not cands["already_flagged"], str(cands["already_flagged"])),
    ]


@case("conflict", "resolved-by-supersede", "When the clash turns out to be a change over time, resolving it closes the contradiction.")
def _(ds) -> list[Check]:
    a = ds.remember(
        entities=[system("billing-service"), EntityIn(name="Stripe", type="Technology"), EntityIn(name="Adyen", type="Technology")],
        relations=[RelationIn(source="billing-service", name="charges_through", target="Stripe", description="billing-service charges customers through Stripe.", evidence="repo://src/billing/gateway.py")],
    )["relations"][0]["id"]
    b = ds.remember(entities=[], relations=[RelationIn(source="billing-service", name="charges_through", target="Adyen", description="billing-service charges customers through Adyen since the 2025 migration.", evidence="ARCHITECTURE.md")])["relations"][0]["id"]
    ds.mark_contradiction(a, b, "two gateways both claim to be current", 0.9)
    ds.supersede(a, b, "Stripe was replaced by Adyen in the 2025 migration; the code comment was stale")
    res = ds.recall("how does billing-service charge customers?", mode="facts", limit=20)
    adyen = fact_with(res, "charges_through", "Adyen")
    open_ = ds.contradiction_candidates()["open_contradictions"]
    return [
        Check("the contradiction is no longer open", not any(c["first_relation_id"] == a for c in open_), f"{len(open_)} open"),
        Check("the surviving fact is current", adyen is not None, str(facts_of(res))),
        Check("the surviving fact is no longer contested", bool(adyen and not adyen["contested"]), f"contested={adyen and adyen['contested']}"),
        Check("the replaced fact left default recall", fact_with(res, "charges_through", "Stripe") is None, str(facts_of(res))),
    ]


# ===== provenance ======================================================================
@case("provenance", "evidence-survives-recall", "Every recalled fact can say where it came from.")
def _(ds) -> list[Check]:
    ds.remember(
        entities=[system("billing-service"), person("Priya"), EntityIn(name="Postgres", type="Technology"), EntityIn(name="ADR-7", type="Decision", description="Chose Postgres over DynamoDB for billing.")],
        relations=[
            RelationIn(source="Priya", name="owns", target="billing-service", description="Priya owns billing-service.", evidence="rota 2024-01-15"),
            RelationIn(source="billing-service", name="depends_on", target="Postgres", description="billing-service depends on Postgres.", evidence="repo://src/billing/db.py#L1-L30"),
            RelationIn(source="ADR-7", name="decided_on", target="Postgres", description="ADR-7 decided billing would use Postgres.", evidence="docs/adr/0007-postgres.md"),
        ],
        source_text="Priya owns billing-service, which depends on Postgres per ADR-7.",
        source="notes-2024-01",
    )
    res = ds.recall("what does billing-service depend on and who decided?", mode="facts", limit=20)
    got = {f["target"]: f["evidence"] for f in res["facts"]}
    return [
        Check("every recalled fact carries evidence", all(f["evidence"] for f in res["facts"]), str(got)),
        Check("the evidence is the pointer that was stored, verbatim", got.get("Postgres") in ("repo://src/billing/db.py#L1-L30", "docs/adr/0007-postgres.md"), str(got)),
        Check("a file-range pointer survived intact", any((f["evidence"] or "").startswith("repo://") for f in res["facts"]), str(got)),
    ]


@case("provenance", "ledger-names-actor-and-action", "The ledger can answer who wrote this fact, when, and as what kind of change.")
def _(ds) -> list[Check]:
    ds.remember(
        entities=[system("billing-service"), person("Priya")],
        relations=[RelationIn(source="Priya", name="owns", target="billing-service", description="Priya owns billing-service.", evidence="rota 2024-01-15")],
        source="notes-2024-01",
    )
    events = ds.history(entity="billing-service", limit=50)["events"]
    actions = {e["action"] for e in events}
    return [
        Check("the write is in the ledger", bool(events), f"{len(events)} events"),
        Check("the entity's creation is recorded", "create" in actions, str(sorted(actions))),
        Check("the fact's assertion is recorded", "assert" in actions, str(sorted(actions))),
        Check("every event names an actor", all(e.get("actor") for e in events), str([e.get("actor") for e in events])),
        Check("every event is timestamped", all(e.get("at") for e in events), str([e.get("at") for e in events][:5])),
    ]


@case("provenance", "evidence-is-not-invented", "A fact stored without a source must not come back with one.", negative=True)
def _(ds) -> list[Check]:
    ds.remember(
        entities=[system("billing-service"), person("Priya")],
        relations=[RelationIn(source="Priya", name="owns", target="billing-service", description="Priya owns billing-service.")],
    )
    res = ds.recall("who owns billing-service?", mode="facts", limit=20)
    f = fact_with(res, "owns", "billing-service")
    return [
        Check("the fact is recalled", f is not None, str(facts_of(res))),
        Check("its evidence is empty, not fabricated", bool(f) and not f["evidence"], f"evidence={f and f['evidence']!r}"),
    ]


# ===== reuse ===========================================================================
def _teach_lesson(ds) -> dict:
    ds.remember(
        entities=[system("billing-service"), EntityIn(name="Stripe", type="Technology"), system("search-service")],
        relations=[RelationIn(source="billing-service", name="charges_through", target="Stripe", description="billing-service charges customers through Stripe.", evidence="repo://src/billing/gateway.py")],
    )
    sid = ds.session_start("session-alpha")["session_id"]
    ds.session_add_turn(sid, "user", "The Stripe webhook retries silently and we double-charged three customers.")
    ds.session_add_turn(sid, "assistant", "Made the webhook handler idempotent, keyed on the Stripe event id.")
    ds.session_set_context(sid, "rules", "Every Stripe webhook handler in billing-service must be idempotent, keyed on the Stripe event id.")
    ds.session_set_context(sid, "preferences", "Prefer structured logging over print in search-service.")
    ds.publish_lessons(sid, [LessonIn(
        title="Stripe webhooks retry, so handlers must be idempotent",
        text="Stripe redelivers webhooks on any non-2xx reply. Key the handler on the Stripe event id or you will double-charge.",
        evidence="session-alpha, double-charge incident",
        applies_to=["billing-service", "Stripe"],
    )])
    ds.session_end(sid)
    return {"session_id": sid}


@case("reuse", "lesson-returns-in-next-session", "A later session is handed the earlier session's rule without asking.")
def _(ds) -> list[Check]:
    _teach_lesson(ds)
    start = ds.session_start("session-beta")
    sections = {c["section"] for c in start["standing_context"]}
    contents = " ".join(c["content"] for c in start["standing_context"])
    titles = [l["title"] for l in start["recent_lessons"]]
    return [
        Check("the new session is new", start["new"] is True, str(start["new"])),
        Check("standing context arrives unprompted", bool(start["standing_context"]), f"{len(start['standing_context'])} entries"),
        Check("the rule from the earlier session is in it", "idempotent" in contents, contents[:200]),
        Check("rules and preferences both carry over", {"rules", "preferences"} <= sections, str(sorted(sections))),
        Check("the distilled lesson is offered too", any("idempotent" in t for t in titles), str(titles)),
    ]


@case("reuse", "lesson-ranks-for-the-work-at-hand", "Asked about the thing the lesson is about, the lesson ranks first.")
def _(ds) -> list[Check]:
    _teach_lesson(ds)
    on_topic = ds.recall("what rules apply to the Stripe webhook handler in billing-service?", mode="rules", limit=10)
    off_topic = ds.recall("what rules apply to logging in search-service?", mode="rules", limit=10)
    top_on = on_topic["rules"][0]["content"] if on_topic["rules"] else ""
    top_off = off_topic["rules"][0]["content"] if off_topic["rules"] else ""
    return [
        Check("the Stripe rule ranks first for the Stripe question", "idempotent" in top_on, top_on[:160]),
        Check("the logging rule ranks first for the logging question", "logging" in top_off, top_off[:160]),
        Check("the lesson text is returned alongside the rules", any("double-charge" in l["text"] for l in on_topic["lessons"]), str([l["text"][:60] for l in on_topic["lessons"]])),
        Check("the lesson keeps its evidence", all(l["evidence"] for l in on_topic["lessons"]), str([l["evidence"] for l in on_topic["lessons"]])),
    ]


@case("reuse", "lesson-is-linked-into-the-graph", "The lesson is reachable from the thing it applies to, not only from the session that made it.")
def _(ds) -> list[Check]:
    _teach_lesson(ds)
    res = ds.recall("billing-service", mode="neighbourhood", limit=20)
    applies = [f for f in res["facts"] if f["relation"] == "applies_to"]
    names = {e["name"] for e in res["entities"]}
    return [
        Check("the lesson is linked to what it applies to", bool(applies), str(facts_of(res))[:300]),
        Check("walking out from billing-service reaches the lesson", any("idempotent" in n for n in names) or any("idempotent" in f["source"] for f in applies), str(sorted(names))[:300]),
        Check("the link carries the lesson's evidence", all(f["evidence"] for f in applies), str([f["evidence"] for f in applies])),
    ]
