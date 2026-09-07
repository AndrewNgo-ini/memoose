"""LoCoMo LLM-judge benchmark for mnemoth, following mem0's memory-benchmarks protocol.

Protocol (same as mem0ai/memory-benchmarks):
  categories 1-4 scored, 5 excluded; gold answer for category 3 cut at ';'.
  answer: memories shown chronologically inside mem0's ANSWER_GENERATION_PROMPT, "ANSWER:" parsed.
  judge: mem0's binary CORRECT/WRONG JSON judge. Score = % CORRECT.

Host model: Claude Code (`claude -p`), which is how mnemoth ships. Two ingest paths:
  --ingest chunks  deterministic: each window of turns is a chunk (no model), speakers as entities.
  --ingest agent   the real product path: per session, a Claude Code run with the mnemoth plugin
                   reads the transcript and calls `remember` itself (skill-driven extraction).
Retrieval at question time is mnemoth's own `recall`; the answerer sees the returned chunks and facts.

Usage:
  uv run python benchmarks/locomo/run_locomo.py --conv 0 --ingest chunks --k 20 --answerer haiku --judge haiku
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))
import mem0_prompts as P  # noqa: E402
from retrieval_bench import ingest as ingest_chunks  # noqa: E402
from retrieval_bench import sessions_of  # noqa: E402

from mnemoth.embeddings import HashEmbedder, default_embedder  # noqa: E402
from mnemoth.engine import Engine  # noqa: E402

CATS = {1: "multi-hop", 2: "temporal", 3: "open-domain", 4: "single-hop"}
_print_lock = threading.Lock()


def log(*a):
    with _print_lock:
        print(*a, file=sys.stderr, flush=True)


# ----- Claude Code as the model ----------------------------------------------------------
LIMIT_MARKERS = ("session limit", "usage limit", "rate limit", "overloaded", "hit your limit")
_limit_pause = threading.Event()


def _is_transient(data: dict) -> bool:
    text = ((data.get("result") or "") + " " + (data.get("stderr") or "")).lower()
    return bool(data.get("is_error")) and any(m in text for m in LIMIT_MARKERS) or ("hit your" in text and "limit" in text)


def claude(prompt: str, model: str, cwd: Path, max_turns: int = 1, extra: list[str] | None = None, env: dict | None = None, timeout: int = 600, max_wait_h: float = 8.0) -> dict:
    """Run Claude Code once. On a usage/rate limit, wait (polling every 5 min) and retry instead of returning junk."""
    cmd = ["claude", "-p", "--model", model, "--output-format", "json", "--max-turns", str(max_turns)] + (extra or [])
    deadline = time.time() + max_wait_h * 3600
    while True:
        while _limit_pause.is_set():
            time.sleep(30)
        t0 = time.time()
        proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=str(cwd), env={**os.environ, **(env or {})}, timeout=timeout)
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            data = {"result": proc.stdout, "is_error": True, "stderr": proc.stderr[-500:]}
        data["wall_s"] = round(time.time() - t0, 1)
        if _is_transient(data) and time.time() < deadline:
            if not _limit_pause.is_set():
                log(f"  usage limit hit ({(data.get('result') or '')[:80]!r}); pausing all calls, retrying every 5 min")
                _limit_pause.set()
                threading.Thread(target=_probe_until_clear, args=(model, cwd), daemon=True).start()
            continue
        return data


def _probe_until_clear(model: str, cwd: Path) -> None:
    while True:
        time.sleep(300)
        proc = subprocess.run(["claude", "-p", "--model", model, "--output-format", "json", "--max-turns", "1"], input="Reply OK", capture_output=True, text=True, cwd=str(cwd), timeout=120)
        try:
            d = json.loads(proc.stdout)
        except json.JSONDecodeError:
            d = {"result": proc.stdout, "is_error": True}
        if not _is_transient(d):
            log("  usage limit cleared; resuming")
            _limit_pause.clear()
            return


def parse_locomo_date(s: str) -> datetime | None:
    for fmt in ("%I:%M %p on %d %B, %Y", "%I:%M %p on %d %b, %Y"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            pass
    return None


# ----- ingest ------------------------------------------------------------------------------------
AGENT_INGEST_PROMPT = """You are building long-term memory with the mnemoth tools (they are available as MCP tools; load the `mnemoth` skill rules: basic entity types, full names, snake_case relations, one-sentence fact descriptions with the endpoint names, Date entities as YYYY-MM-DD, evidence pointers, no outside knowledge).

Below is one session of a conversation between {a} and {b}, which took place on {when}.
Store everything a person would want to remember later: who did what, when, with whom, where, what they like, plan, feel, own, and what happened to them. Use dataset "{dataset}" on every call.

Do this:
1. Call remember ONCE per 4-6 consecutive turns (so several remember calls for the session). In each call pass:
   - entities: {a} and {b} (Person) plus every person, place, organization, event, product, activity, pet, date etc. mentioned (basic types).
   - relations: every fact as source --relation--> target with a description that repeats the names and includes the date {date_iso} when the fact is about this session (e.g. "{a} went camping with friends on {date_iso}."). Put the dia_id(s) in evidence, e.g. "D3:7".
   - source_text: the exact turns of that window, prefixed "[{when}]" and with speaker names, and source: the dia_id range.
   - summary: "This chunk is about:\\n- People: ...\\nFacts:\\n- ..." covering the window.
2. Do not skip turns. Do not answer questions. Nobody will reply to you: never ask for confirmation. If a tool call returns an error (for example StoreBusy or a validation message), fix the input if needed and retry the same call, up to 5 times. When every turn is stored, reply with only: DONE <number of remember calls>.

Session {sidx} transcript:
{transcript}
"""


def ingest_agent(ds_name: str, conv: dict, data_dir: Path, model: str, cwd: Path, workers: int) -> dict:
    a, b = conv["speaker_a"], conv["speaker_b"]
    # The plugin manifest pins MNEMOTH_DATA_DIR to the plugin data dir, so the harness supplies its own
    # server entry (strict) pointing at the benchmark data dir; skills still come from --plugin-dir.
    mcp_cfg = cwd / "mcp.json"
    mcp_cfg.write_text(json.dumps({"mcpServers": {"mnemoth": {
        "command": "uv", "args": ["run", "--project", str(ROOT), "mnemoth", "serve"],
        "env": {"MNEMOTH_DATA_DIR": str(data_dir), "MNEMOTH_EMBEDDER": os.environ.get("MNEMOTH_EMBEDDER", "auto")}}}}))
    env = {}
    extra = ["--plugin-dir", str(ROOT), "--mcp-config", str(mcp_cfg), "--strict-mcp-config", "--dangerously-skip-permissions"]
    jobs = []
    for sidx, when, turns in sessions_of(conv):
        dt = parse_locomo_date(when)
        transcript = "\n".join(f"{t['dia_id']} {t['speaker']}: {t['text']}" + (f" [photo: {t['blip_caption']}]" if t.get("blip_caption") else "") for t in turns)
        prompt = AGENT_INGEST_PROMPT.format(a=a, b=b, when=when, date_iso=dt.strftime("%Y-%m-%d") if dt else when, dataset=ds_name, sidx=sidx, transcript=transcript)
        jobs.append((sidx, prompt))
    results = {}
    # Sessions in order matters little for memory (dates are explicit); run a few in parallel.
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(claude, p, model, cwd, 60, extra, env, 1800): s for s, p in jobs}
        for f in as_completed(futs):
            s = futs[f]
            r = f.result()
            results[s] = {"result": (r.get("result") or "")[-80:], "cost": r.get("total_cost_usd"), "wall_s": r.get("wall_s"), "turns": r.get("num_turns"), "error": r.get("is_error")}
            log(f"  ingest session {s}: {results[s]}")
    failed = [s for s, r in results.items() if r["error"]]
    if failed:
        raise RuntimeError(f"agent ingest failed for sessions {failed}; data dir is partial, delete it and rerun")
    return results


# ----- answer + judge ------------------------------------------------------------------------------
def memories_from_recall(res: dict) -> list[dict]:
    mems = []
    for c in res.get("chunks", []):
        text = c["text"]
        m = re.match(r"\[(.*?)\]\n", text)
        when = parse_locomo_date(m.group(1)) if m else None
        mems.append({"memory": text[m.end():] if m else text, "created_at": when.isoformat() if when else ""})
    for f in res.get("facts", []):
        when = None
        for cand in (f.get("valid_from"), f.get("when")):
            if cand:
                try:
                    when = datetime.fromisoformat(cand[:10])
                    break
                except ValueError:
                    pass
        mems.append({"memory": f["fact"] + (f" [evidence {f['evidence']}]" if f.get("evidence") else ""), "created_at": when.isoformat() if when else ""})
    return mems


def retrieve(ds, q: dict, k: int, reference_date: str) -> dict:
    """Runs on the main thread: SQLite connections are not shareable across threads."""
    t0 = time.perf_counter()
    res = ds.recall(q["question"], limit=k)
    retrieval_ms = round((time.perf_counter() - t0) * 1000, 1)
    mems = memories_from_recall(res)
    prompt = P.get_answer_generation_prompt(q["question"], mems, reference_date=reference_date)
    return {"res": res, "prompt": prompt, "retrieval_ms": retrieval_ms}


def answer_and_judge(q: dict, ret: dict, answerer: str, judge: str, cwd: Path) -> dict:
    res, prompt, retrieval_ms = ret["res"], ret["prompt"], ret["retrieval_ms"]
    a = claude(prompt, answerer, cwd)
    if a.get("is_error"):
        raise RuntimeError(f"answer call failed: {(a.get('result') or '')[:200]}")
    generated = a.get("result") or ""
    if "ANSWER:" in generated:
        generated = generated.rsplit("ANSWER:", 1)[-1].strip()
    gold = P.preprocess_answer(q["category"], str(q["answer"]))
    jp = P.get_judge_prompt(q["category"], q["question"], gold, generated)
    j = claude(P.JUDGE_SYSTEM_PROMPT + "\n\n" + jp, judge, cwd)
    if j.get("is_error"):
        raise RuntimeError(f"judge call failed: {(j.get('result') or '')[:200]}")
    raw = j.get("result") or ""
    label = "WRONG"
    m = re.search(r'"label"\s*:\s*"(CORRECT|WRONG)"', raw, re.I)
    if m:
        label = m.group(1).upper()
    elif "CORRECT" in raw.upper() and "WRONG" not in raw.upper():
        label = "CORRECT"
    return {
        "question": q["question"], "category": q["category"], "category_name": CATS[q["category"]], "gold": gold,
        "generated": generated[:1000], "label": label, "correct": label == "CORRECT", "mode": res.get("mode"),
        "n_chunks": len(res.get("chunks", [])), "n_facts": len(res.get("facts", [])), "prompt_chars": len(prompt),
        "retrieval_ms": retrieval_ms, "answer_cost": a.get("total_cost_usd"), "judge_cost": j.get("total_cost_usd"),
        "answer_wall_s": a.get("wall_s"), "judge_reasoning": raw[:300], "evidence": q.get("evidence"),
    }


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% confidence interval for a proportion, so a sampled score reports its own precision."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    return (round(100 * (c - m) / d, 1), round(100 * (c + m) / d, 1))


def summarize(rows: list[dict]) -> dict:
    k = sum(r["correct"] for r in rows)
    out = {"n": len(rows), "score": round(100 * k / max(1, len(rows)), 1), "ci95": wilson(k, len(rows)), "by_category": {}}
    for c, name in CATS.items():
        sub = [r for r in rows if r["category"] == c]
        if sub:
            sk = sum(r["correct"] for r in sub)
            out["by_category"][name] = {"n": len(sub), "score": round(100 * sk / len(sub), 1), "ci95": wilson(sk, len(sub))}
    by_conv = {}
    for r in rows:
        by_conv.setdefault(r.get("conversation"), []).append(r["correct"])
    out["by_conversation"] = {str(c): {"n": len(v), "score": round(100 * sum(v) / len(v), 1)} for c, v in sorted(by_conv.items(), key=lambda x: (x[0] is None, x[0]))}
    out["mean_prompt_tokens_est"] = round(sum(r["prompt_chars"] for r in rows) / max(1, len(rows)) / 4)
    out["total_cost_usd"] = round(sum((r["answer_cost"] or 0) + (r["judge_cost"] or 0) for r in rows), 2)
    out["retrieval_ms_p50"] = sorted(r["retrieval_ms"] for r in rows)[len(rows) // 2] if rows else None
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--conv", type=int, nargs="*", default=[0])
    ap.add_argument("--ingest", choices=["chunks", "agent"], default="chunks")
    ap.add_argument("--k", type=int, default=20)
    ap.add_argument("--turns-per-chunk", type=int, default=4)
    ap.add_argument("--answerer", default="haiku")
    ap.add_argument("--judge", default="haiku")
    ap.add_argument("--ingest-model", default="sonnet")
    ap.add_argument("--embedder", default="auto")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit", type=int, default=None, help="first N questions per conversation (pilot runs)")
    ap.add_argument("--sample", type=int, default=None, help="deterministic random sample of N questions per conversation (stratified estimate)")
    ap.add_argument("--seed", type=int, default=0, help="sample seed")
    ap.add_argument("--reuse-rows-from", default=None, help="tag directory whose already-scored rows should be reused when they fall in the sample")
    ap.add_argument("--tag", default=None)
    ap.add_argument("--data-dir", default=None, help="reuse an existing ingested data dir")
    args = ap.parse_args()

    data = json.load(open(HERE / "locomo10.json"))
    tag = args.tag or f"{args.ingest}-k{args.k}-{args.answerer}-{time.strftime('%Y%m%d-%H%M')}"
    out_dir = HERE / "results" / tag
    out_dir.mkdir(parents=True, exist_ok=True)
    data_dir = Path(args.data_dir) if args.data_dir else out_dir / "data"
    # Run Claude Code outside the repo so no project config interferes with the plugin.
    import tempfile
    cwd = Path(tempfile.gettempdir()) / "mnemoth-bench" / tag
    cwd.mkdir(parents=True, exist_ok=True)
    embedder = HashEmbedder() if args.embedder == "hash" else default_embedder()
    eng = Engine(embedder=embedder, data_dir=data_dir)
    all_rows: list[dict] = []
    for ci in args.conv:
        sample = data[ci]
        conv = sample["conversation"]
        ds_name = f"locomo-{ci}"
        ds = eng.dataset(ds_name)
        if ds.store.stats()["chunks"] == 0:
            log(f"[conv {ci}] ingest ({args.ingest}) ...")
            t0 = time.time()
            if args.ingest == "chunks":
                n = ingest_chunks(ds, conv, args.turns_per_chunk)
                ingest_info = {"chunks": n}
            else:
                eng.close()
                ingest_info = ingest_agent(ds_name, conv, data_dir, args.ingest_model, cwd, max(1, args.workers // 2))
                eng = Engine(embedder=embedder, data_dir=data_dir)
                ds = eng.dataset(ds_name)
            ingest_info["seconds"] = round(time.time() - t0, 1)
            ingest_info["stats"] = ds.store.stats()
            (out_dir / f"ingest-{ci}.json").write_text(json.dumps(ingest_info, indent=2))
            log(f"[conv {ci}] ingested: {ingest_info['stats']}")
        last = max((parse_locomo_date(w) for _, w, _ in sessions_of(conv) if parse_locomo_date(w)), default=None)
        reference_date = last.strftime("%B %d, %Y") if last else "2023"
        qa = [q for q in sample["qa"] if q["category"] in CATS]
        if args.sample:
            rnd = random.Random(f"{args.seed}:{ci}")
            qa = sorted(rnd.sample(qa, min(args.sample, len(qa))), key=lambda q: q["category"])
        elif args.limit:
            qa = qa[: args.limit]
        rows_path = out_dir / f"rows-{ci}.jsonl"
        if args.reuse_rows_from:
            src = HERE / "results" / args.reuse_rows_from / f"rows-{ci}.jsonl"
            if src.exists() and not rows_path.exists():
                wanted = {q["question"] for q in qa}
                keep = [l for l in src.read_text().splitlines() if json.loads(l)["question"] in wanted]
                rows_path.write_text("\n".join(keep) + ("\n" if keep else ""))
                log(f"[conv {ci}] reused {len(keep)} scored rows from {args.reuse_rows_from}")
        done = set()
        if rows_path.exists():
            for line in rows_path.read_text().splitlines():
                done.add(json.loads(line)["question"])
        todo = [q for q in qa if q["question"] not in done]
        log(f"[conv {ci}] {len(qa)} questions, {len(todo)} to run, reference date {reference_date}")
        lock = threading.Lock()
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = [ex.submit(answer_and_judge, q, retrieve(ds, q, args.k, reference_date), args.answerer, args.judge, cwd) for q in todo]
            for i, f in enumerate(as_completed(futs), 1):
                try:
                    r = f.result()
                except Exception as e:  # noqa: BLE001
                    log(f"[conv {ci}] question skipped: {e}")
                    continue
                r["conversation"] = ci
                with lock, rows_path.open("a") as fh:
                    fh.write(json.dumps(r) + "\n")
                if i % 10 == 0:
                    log(f"[conv {ci}] {i}/{len(todo)} done")
        rows = [json.loads(l) for l in rows_path.read_text().splitlines()]
        all_rows += rows
        s = summarize(rows)
        (out_dir / f"summary-{ci}.json").write_text(json.dumps(s, indent=2))
        log(f"[conv {ci}] {json.dumps(s)}")
    eng.close()
    total = summarize(all_rows)
    total.update({"tag": tag, "conversations": args.conv, "ingest": args.ingest, "k": args.k, "answerer": args.answerer, "judge": args.judge, "embedder": embedder.name,
                  "sample_per_conversation": args.sample, "seed": args.seed if args.sample else None})
    (out_dir / "summary.json").write_text(json.dumps(total, indent=2))
    print(json.dumps(total, indent=2))


if __name__ == "__main__":
    main()
