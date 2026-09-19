"""LongMemEval (ICLR 2025) LLM-judge benchmark for memoose, following mem0's memory-benchmarks protocol.

Protocol (same as mem0ai/memory-benchmarks/benchmarks/longmemeval):
  dataset: longmemeval_s_cleaned (500 questions, ~50 haystack sessions each, ~115k tokens per question).
  ingest: sessions in chronological order, one chunk per user+assistant pair (mem0's CHUNK_SIZE=2).
  answer: memories shown chronologically inside mem0's ANSWER_GENERATION_PROMPT, "ANSWER:" parsed.
  judge: mem0's unified yes/no rubric judge. Score = % yes, over all question types incl. abstention.
  sample: stratified by question_type, `--per-type N`, seed 42 (mem0's default pilot is 5 per type = 30).

Also records a model-free retrieval signal per row: did any returned chunk come from an
answer session (`session_hit`), and what fraction of `has_answer` turns came back (`turn_recall`).

Host model: Claude Code (`claude -p`), as in the LoCoMo runner, whose driver this reuses.

Usage:
  uv run python benchmarks/longmemeval/run_longmemeval.py --per-type 5 --k 20 --answerer haiku --judge haiku
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import tempfile
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))
import mem0_prompts as P  # noqa: E402  (benchmarks/longmemeval/mem0_prompts.py, vendored from mem0)

assert "longmemeval" in P.__file__, P.__file__  # locomo/ has a module of the same name
sys.path.insert(0, str(ROOT / "benchmarks" / "locomo"))
from run_locomo import claude, log, wilson  # noqa: E402

from memoose.store.embeddings import HashEmbedder, default_embedder  # noqa: E402
from memoose.engine import Engine  # noqa: E402
from memoose.graph.ids import Ids  # noqa: E402
from memoose.store.sqlite_store import ChunkRow  # noqa: E402

DATASETS = [HERE / "longmemeval_s_cleaned.json", HERE / "longmemeval_s.json"]
DATASET_URL = "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_s_cleaned.json"


def load_dataset() -> tuple[str, list[dict]]:
    for p in DATASETS:
        if p.exists() and p.stat().st_size > 1_000_000:
            return p.name, json.load(open(p))
    raise SystemExit(f"dataset missing: curl -L -o {DATASETS[0]} {DATASET_URL}")


def parse_date(s: str) -> datetime | None:
    """'2023/05/01 (Mon) 21:05' -> datetime (same cleaning as mem0)."""
    try:
        return datetime.strptime(re.sub(r"\s*\([A-Za-z]+\)\s*", " ", s).strip(), "%Y/%m/%d %H:%M")
    except (ValueError, TypeError):
        return None


def sessions_of(q: dict):
    """(session_id, date_str, turns) sorted chronologically, undated last (mem0's sort_sessions_chronologically)."""
    trip = list(zip(q["haystack_session_ids"], q["haystack_dates"], q["haystack_sessions"]))
    trip.sort(key=lambda t: (0, parse_date(t[1]).timestamp(), t[1]) if parse_date(t[1]) else (1, 0, t[1]))
    return trip


# ----- ingest ------------------------------------------------------------------------------------
def ingest(ds, q: dict) -> int:
    """One chunk per user+assistant pair; source = '<session_id>:<turn indices>' so evidence can be checked."""
    n = 0
    for sid, when, turns in sessions_of(q):
        pairs = [turns[i : i + 2] for i in range(0, len(turns), 2)]
        texts = [f"[{when}]\n" + "\n".join(f"{t['role']}: {t['content']}" for t in pair) for pair in pairs]
        vecs = ds.embedder.embed(texts)  # one batch per session: ~10x faster than per-chunk
        with ds.store.conn:
            for i, (pair, text, vec) in enumerate(zip(pairs, texts, vecs)):
                cid = Ids.chunk(text)
                ds.store.upsert_chunk(ChunkRow(cid, text, None, ",".join(f"{sid}:{2 * i + j}" for j in range(len(pair)))), [])
                ds.store.index_text("chunk", cid, text)
                ds.store.index_vector("chunk", cid, ds.embedder.name, vec)
                n += 1
    return n


def gold_turns(q: dict) -> set[str]:
    return {f"{sid}:{i}" for sid, _, turns in zip(q["haystack_session_ids"], q["haystack_dates"], q["haystack_sessions"]) if sid in set(q["answer_session_ids"]) for i, t in enumerate(turns) if t.get("has_answer")}


# ----- answer + judge ------------------------------------------------------------------------------
def memories_from_recall(res: dict) -> list[dict]:
    mems = []
    for c in res.get("chunks", []):
        m = re.match(r"\[(.*?)\]\n", c["text"])
        when = parse_date(m.group(1)) if m else None
        mems.append({"memory": c["text"][m.end():] if m else c["text"], "created_at": when.isoformat() if when else ""})
    for f in res.get("facts", []):
        mems.append({"memory": f["fact"], "created_at": (f.get("valid_from") or "")[:10]})
    return sorted(mems, key=lambda x: x["created_at"])


def parse_yes_no(raw: str) -> bool:
    """mem0's LLMClient._parse_yes_no_judgment."""
    text = raw.strip()
    if not text:
        return False
    region = re.split(r"</judge_thinking>|</thinking>", text, flags=re.I)[-1].strip()
    for line in reversed([l.strip().lower() for l in region.splitlines() if l.strip()]):
        if line in ("yes", "no"):
            return line == "yes"
    toks = re.findall(r"\b(yes|no)\b", region.lower())
    return toks[-1] == "yes" if toks else text.lower().startswith("yes")


def retrieve(ds, q: dict, k: int) -> dict:
    """Main thread only: SQLite connections are not shareable across threads."""
    t0 = time.perf_counter()
    res = ds.recall(q["question"], limit=k)
    ms = round((time.perf_counter() - t0) * 1000, 1)
    got = {s for c in res.get("chunks", []) for s in (c.get("source") or "").split(",")}
    gold = gold_turns(q)
    qd = parse_date(q.get("question_date", ""))
    prompt = P.get_answer_generation_prompt(q["question"], memories_from_recall(res), qd.strftime("%A, %B %d, %Y") if qd else q.get("question_date", ""))
    return {"res": res, "prompt": prompt, "retrieval_ms": ms, "question_date_human": qd.strftime("%A, %B %d, %Y") if qd else "",
            "session_hit": any(s.split(":")[0] in set(q["answer_session_ids"]) for s in got),
            "turn_recall": round(len(gold & got) / len(gold), 3) if gold else None}


def answer_and_judge(q: dict, ret: dict, answerer: str, judge: str, cwd: Path) -> dict:
    a = claude(ret["prompt"], answerer, cwd)
    if a.get("is_error"):
        raise RuntimeError(f"answer call failed: {(a.get('result') or '')[:200]}")
    generated = re.sub(r"[<\[]mem_thinking[>\]].*?[<\[]/mem_thinking[>\]]", "", a.get("result") or "", flags=re.S).strip()
    if "ANSWER:" in generated:
        generated = generated.rsplit("ANSWER:", 1)[-1].strip()
    jp = P.get_judge_prompt(q["question_type"], q["question_id"], q["question"], str(q["answer"]), generated, ret["question_date_human"])
    j = claude(jp, judge, cwd)
    if j.get("is_error"):
        raise RuntimeError(f"judge call failed: {(j.get('result') or '')[:200]}")
    raw = j.get("result") or ""
    res = ret["res"]
    return {
        "question_id": q["question_id"], "question_type": q["question_type"], "question": q["question"], "gold": str(q["answer"]),
        "is_abstention": q["question_id"].endswith("_abs"), "generated": generated[:1000], "correct": parse_yes_no(raw),
        "mode": res.get("mode"), "n_chunks": len(res.get("chunks", [])), "n_facts": len(res.get("facts", [])),
        "prompt_chars": len(ret["prompt"]), "retrieval_ms": ret["retrieval_ms"], "session_hit": ret["session_hit"], "turn_recall": ret["turn_recall"],
        "answer_cost": a.get("total_cost_usd"), "judge_cost": j.get("total_cost_usd"), "answer_wall_s": a.get("wall_s"), "judge_reasoning": raw[-300:],
    }


def summarize(rows: list[dict]) -> dict:
    k = sum(r["correct"] for r in rows)
    out = {"n": len(rows), "score": round(100 * k / max(1, len(rows)), 1), "ci95": wilson(k, len(rows)), "by_type": {}}
    by = defaultdict(list)
    for r in rows:
        by[r["question_type"]].append(r)
    for t, sub in sorted(by.items()):
        sk = sum(r["correct"] for r in sub)
        out["by_type"][t] = {"n": len(sub), "score": round(100 * sk / len(sub), 1), "session_hit": round(100 * sum(r["session_hit"] for r in sub) / len(sub), 1)}
    ab = [r for r in rows if r["is_abstention"]]
    out["abstention"] = {"n": len(ab), "score": round(100 * sum(r["correct"] for r in ab) / len(ab), 1)} if ab else None
    out["session_hit"] = round(100 * sum(r["session_hit"] for r in rows) / max(1, len(rows)), 1)
    tr = [r["turn_recall"] for r in rows if r["turn_recall"] is not None]
    out["turn_recall"] = round(sum(tr) / len(tr), 3) if tr else None
    out["mean_prompt_tokens_est"] = round(sum(r["prompt_chars"] for r in rows) / max(1, len(rows)) / 4)
    out["total_cost_usd"] = round(sum((r["answer_cost"] or 0) + (r["judge_cost"] or 0) for r in rows), 2)
    out["retrieval_ms_p50"] = sorted(r["retrieval_ms"] for r in rows)[len(rows) // 2] if rows else None
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-type", type=int, default=5, help="stratified sample per question_type (mem0 default 5 -> 30 questions)")
    ap.add_argument("--all", action="store_true", help="all 500 questions")
    ap.add_argument("--types", nargs="*", default=None, help="restrict to these question_types")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--k", type=int, default=20)
    ap.add_argument("--answerer", default="haiku")
    ap.add_argument("--judge", default="haiku")
    ap.add_argument("--embedder", default="auto")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--retrieval-only", action="store_true", help="no model: ingest + recall + session_hit/turn_recall only")
    ap.add_argument("--tag", default=None)
    ap.add_argument("--data-dir", default=None, help="reuse an existing ingested data dir")
    args = ap.parse_args()

    ds_file, data = load_dataset()
    if not args.all:
        rnd = random.Random(args.seed)
        groups = defaultdict(list)
        for q in data:
            groups[q["question_type"]].append(q)
        data = [q for t in sorted(groups) for q in rnd.sample(groups[t], min(args.per_type, len(groups[t])))]
    if args.types:  # after sampling, so a per-type rerun sees the same questions as the full sample
        data = [q for q in data if q["question_type"] in set(args.types)]
    tag = args.tag or f"lme-k{args.k}-{args.answerer}-{time.strftime('%Y%m%d-%H%M')}"
    out_dir = HERE / "results" / tag
    out_dir.mkdir(parents=True, exist_ok=True)
    cwd = Path(tempfile.gettempdir()) / "memoose-bench" / tag
    cwd.mkdir(parents=True, exist_ok=True)
    embedder = HashEmbedder() if args.embedder == "hash" else default_embedder()
    eng = Engine(embedder=embedder, data_dir=Path(args.data_dir) if args.data_dir else out_dir / "data")

    rows_path = out_dir / "rows.jsonl"
    done = {json.loads(l)["question_id"] for l in rows_path.read_text().splitlines()} if rows_path.exists() else set()
    todo = [q for q in data if q["question_id"] not in done]
    log(f"[{tag}] {ds_file}: {len(data)} questions, {len(todo)} to run, embedder {embedder.name}")

    lock = threading.Lock()
    ingest_s = []
    n_done = [0]

    def write_row(f) -> None:  # runs as each answer+judge finishes, so a partial run still has rows on disk
        try:
            r = f.result()
        except Exception as e:  # noqa: BLE001
            log(f"  question skipped: {e}")
            return
        with lock, rows_path.open("a") as fh:
            fh.write(json.dumps(r) + "\n")
            n_done[0] += 1
        log(f"  {n_done[0]}/{len(todo)} {r['question_id']} {r['question_type']}: {'yes' if r['correct'] else 'no'} (session_hit={r['session_hit']}, {r['prompt_chars'] // 4} tok)")
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for q in todo:
            ds = eng.dataset(f"lme-{q['question_id']}")
            if ds.store.stats()["chunks"] == 0:
                t0 = time.time()
                n = ingest(ds, q)
                ingest_s.append(time.time() - t0)
                log(f"  ingested {q['question_id']} ({q['question_type']}): {n} chunks in {ingest_s[-1]:.1f}s")
            ret = retrieve(ds, q, args.k)
            if args.retrieval_only:
                with rows_path.open("a") as fh:
                    fh.write(json.dumps({"question_id": q["question_id"], "question_type": q["question_type"], "is_abstention": q["question_id"].endswith("_abs"), "correct": False,
                                         "session_hit": ret["session_hit"], "turn_recall": ret["turn_recall"], "prompt_chars": len(ret["prompt"]), "retrieval_ms": ret["retrieval_ms"], "answer_cost": 0, "judge_cost": 0}) + "\n")
                continue
            ex.submit(answer_and_judge, q, ret, args.answerer, args.judge, cwd).add_done_callback(write_row)
    eng.close()
    rows = [json.loads(l) for l in rows_path.read_text().splitlines()]
    total = summarize(rows)
    total.update({"tag": tag, "dataset": ds_file, "k": args.k, "answerer": args.answerer, "judge": args.judge, "embedder": embedder.name,
                  "per_type": None if args.all else args.per_type, "seed": args.seed, "retrieval_only": args.retrieval_only,
                  "ingest_s_mean": round(sum(ingest_s) / len(ingest_s), 1) if ingest_s else None})
    (out_dir / "summary.json").write_text(json.dumps(total, indent=2))
    print(json.dumps(total, indent=2))


if __name__ == "__main__":
    main()
