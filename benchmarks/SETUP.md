# Running the benchmarks on a fresh machine (VPS)

The harness drives **Claude Code** as the host model, so the machine needs the `claude` CLI
authenticated, plus Python. Nothing else: memoose itself has no API key and no service.

## 1. Dependencies

```sh
# Python 3.11+ and uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Claude Code CLI
npm install -g @anthropic-ai/claude-code     # or: curl -fsSL https://claude.ai/install.sh | bash

git clone https://github.com/AndrewNgo-ini/mnemoth
cd mnemoth
uv sync --extra fastembed --group dev
uv run pytest -q                              # 77 tests, ~3s
```

`fastembed` downloads a ~130 MB ONNX model (BAAI/bge-small-en-v1.5) on first use. Set
`MEMOOSE_EMBEDDER=hash` to skip it entirely at some cost in recall (0.804 vs 0.876).

## 2. Authenticate Claude Code headlessly

Two options, in order of preference on a VPS:

```sh
claude setup-token          # long-lived token, needs a Claude subscription (interactive once)
export ANTHROPIC_API_KEY=…  # API-key users
```

Verify: `claude -p --model haiku 'Reply OK'` should print `OK`.

## 3. Dataset

Fetched automatically on first run (not redistributed in this repo):

```sh
uv run python benchmarks/locomo/fetch_dataset.py
```

## 4. Run

```sh
# free, no model: retrieval quality only (~5 min for all 10 conversations)
uv run python benchmarks/locomo/retrieval_bench.py --k 20

# LLM judge, stratified sample of 16 questions per conversation (160 questions, ~$9, ~1.5 h)
uv run python benchmarks/locomo/run_locomo.py --conv 0 1 2 3 4 5 6 7 8 9 \
  --ingest chunks --turns-per-chunk 4 --k 20 --sample 16 --seed 1 \
  --answerer haiku --judge haiku --workers 6 --tag sample16-chunks-k20-haiku

# the full 1,540-question run (~$85, many hours)
uv run python benchmarks/locomo/run_locomo.py --conv 0 1 2 3 4 5 6 7 8 9 \
  --ingest chunks --turns-per-chunk 4 --k 20 --answerer haiku --judge haiku \
  --workers 8 --tag full-chunks-k20-haiku
```

## Operational notes learned the hard way

- **Runs resume.** Rerunning with the same `--tag` skips questions already in `rows-*.jsonl`.
  `--reuse-rows-from <tag>` imports matching rows from another run's directory.
- **Usage limits pause the run**, they no longer corrupt it. On a limit the harness stops issuing
  calls, probes every 5 minutes, and resumes; failed calls are never written as rows. An earlier
  version recorded the limit error as an answer and invalidated 1,492 of 1,540 rows.
- **Run Claude Code with cwd outside the repo.** The harness writes its own `mcp.json` in a temp
  directory and passes `--mcp-config … --strict-mcp-config`, because the plugin manifest pins
  `MEMOOSE_DATA_DIR` to the plugin data directory and a project-level config inside the repo
  clashes with it.
- **Workers.** 6–8 parallel questions is fine; parallel *agent ingest* sessions write one SQLite
  file, which is why embeddings are computed outside the write transaction and the store has a
  60 s busy timeout.
- **Don't kill runs with `pkill -f run_locomo`** from inside a Claude Code session: the pattern
  matches the agent's own shell. Kill by PID.
- **Sizes.** Memory databases under `results/*/data/` reach tens of MB and are gitignored; the
  result rows are text and small (~1.5 MB tracked). Only commit rows, summaries, and logs.
