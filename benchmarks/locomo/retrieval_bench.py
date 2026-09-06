"""Model-free LoCoMo retrieval benchmark for mnemoth.

Ingests every conversation turn deterministically (no extraction: each turn is a chunk whose
`source` is its dia_id, plus Date entities for session dates), then asks recall for each QA
and checks whether the gold `evidence` dia_ids are among the returned chunks.

This isolates the retrieval half of the memory system so RRF weights, chunk sizes, and modes
can be tuned quickly without a model. It is NOT the LLM-judge score; see run_locomo.py.

Usage: uv run python benchmarks/locomo/retrieval_bench.py [--conv 0] [--k 10] [--mode hybrid|lexical]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from mnemoth.embeddings import HashEmbedder, default_embedder  # noqa: E402
from mnemoth.engine import Engine  # noqa: E402
from mnemoth.ids import chunk_id  # noqa: E402
from mnemoth.models import EntityIn, RelationIn  # noqa: E402
from mnemoth.store.sqlite_store import ChunkRow  # noqa: E402

CATEGORIES = {1: "multi-hop", 2: "temporal", 3: "open-domain", 4: "single-hop", 5: "adversarial"}


def sessions_of(conv: dict):
    i = 1
    while f"session_{i}" in conv:
        yield i, conv[f"session_{i}_date_time"], conv[f"session_{i}"]
        i += 1


def ingest(ds, conv: dict, turns_per_chunk: int) -> int:
    """Each chunk = a window of consecutive turns from one session, text prefixed with speaker; source lists dia_ids."""
    a, b = conv["speaker_a"], conv["speaker_b"]
    ds.remember([EntityIn(name=a, type="Person", description=f"Speaker in the conversation with {b}."), EntityIn(name=b, type="Person", description=f"Speaker in the conversation with {a}.")], [])
    n = 0
    for sidx, when, turns in sessions_of(conv):
        date_ent = EntityIn(name=f"Session {sidx}", type="Event", description=f"Conversation session {sidx} between {a} and {b} on {when}.")
        ds.remember([date_ent], [RelationIn(source=a, name="talked_with", target=b, description=f"{a} talked with {b} in session {sidx} on {when}.", evidence=f"session_{sidx}")])
        for start in range(0, len(turns), turns_per_chunk):
            window = turns[start : start + turns_per_chunk]
            text = f"[{when}]\n" + "\n".join(f"{t['speaker']}: {t['text']}" + (f" (photo: {t['blip_caption']})" if t.get("blip_caption") else "") for t in window)
            cid = chunk_id(text)
            with ds.store.conn:
                ds.store.upsert_chunk(ChunkRow(cid, text, None, ",".join(t["dia_id"] for t in window)), [])
                ds.store.index_text("chunk", cid, text)
                vec = ds.embedder.embed([text])[0]
                ds.store.index_vector("chunk", cid, ds.embedder.name, vec)
            n += 1
    return n


def evaluate(ds, qa: list[dict], k: int, mode: str | None) -> dict:
    per_cat: dict[int, list[float]] = defaultdict(list)
    per_cat_any: dict[int, list[float]] = defaultdict(list)
    lat = []
    for q in qa:
        if q["category"] == 5 or not q.get("evidence"):
            continue
        t0 = time.perf_counter()
        res = ds.recall(q["question"], mode=mode, limit=k)
        lat.append(time.perf_counter() - t0)
        got: set[str] = set()
        for c in res.get("chunks", []):
            got |= set((c.get("source") or "").split(","))
        gold = set(q["evidence"])
        frac = len(gold & got) / len(gold)
        per_cat[q["category"]].append(frac)
        per_cat_any[q["category"]].append(1.0 if gold & got else 0.0)
    out = {"k": k, "mode": mode or "auto", "latency_ms_p50": round(statistics.median(lat) * 1000, 1) if lat else None, "categories": {}}
    all_frac, all_any = [], []
    for cat in sorted(per_cat):
        out["categories"][CATEGORIES[cat]] = {"n": len(per_cat[cat]), "evidence_recall": round(statistics.mean(per_cat[cat]), 3), "hit_any": round(statistics.mean(per_cat_any[cat]), 3)}
        all_frac += per_cat[cat]
        all_any += per_cat_any[cat]
    out["overall"] = {"n": len(all_frac), "evidence_recall": round(statistics.mean(all_frac), 3), "hit_any": round(statistics.mean(all_any), 3)}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--conv", type=int, nargs="*", default=None, help="conversation indices (default all)")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--mode", default=None)
    ap.add_argument("--turns-per-chunk", type=int, default=4)
    ap.add_argument("--embedder", default="auto", help="auto|hash|fastembed")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    data = json.load(open(Path(__file__).with_name("locomo10.json")))
    convs = args.conv if args.conv is not None else list(range(len(data)))
    embedder = HashEmbedder() if args.embedder == "hash" else default_embedder()
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        eng = Engine(embedder=embedder, data_dir=Path(tmp))
        for ci in convs:
            sample = data[ci]
            ds = eng.dataset(f"locomo-{ci}")
            t0 = time.perf_counter()
            n = ingest(ds, sample["conversation"], args.turns_per_chunk)
            r = evaluate(ds, sample["qa"], args.k, args.mode)
            r.update({"conversation": ci, "chunks": n, "ingest_s": round(time.perf_counter() - t0, 1), "embedder": embedder.name})
            results.append(r)
            print(json.dumps(r))
        eng.close()
    if len(results) > 1:
        agg = defaultdict(list)
        for r in results:
            for cat, v in r["categories"].items():
                agg[cat].append((v["evidence_recall"], v["n"]))
        summary = {cat: round(sum(s * n for s, n in xs) / sum(n for _, n in xs), 3) for cat, xs in agg.items()}
        total_n = sum(r["overall"]["n"] for r in results)
        summary["overall"] = round(sum(r["overall"]["evidence_recall"] * r["overall"]["n"] for r in results) / total_n, 3)
        print(json.dumps({"summary_evidence_recall@k": summary, "k": args.k, "mode": args.mode or "auto", "embedder": embedder.name}))
    if args.out:
        Path(args.out).write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
