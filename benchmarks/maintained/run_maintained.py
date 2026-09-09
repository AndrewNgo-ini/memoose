"""The maintained-memory benchmark: does memory stay trustworthy as facts change?

Every published memory benchmark we know of (LoCoMo, LongMemEval, mem0's and Zep's suites)
scores one question: can you find a fact that was stated once. That is retrieval. It says
nothing about the part that makes long-lived memory hard — a fact changed, two sources
disagree, why do we believe this, we learned this before. memoose claims all four
(VISION.md), and LoCoMo showed our graph buys nothing there (McNemar p = 1.00), so those
claims were carrying no evidence at all.

This suite is the evidence. It asserts on the payloads the MCP tools actually return, so
**no model is involved**: it runs in about a second, needs no API key, is exactly
reproducible, and can therefore gate every commit — which is why it is also wired into
pytest (`tests/test_maintained.py`). An LLM-judged suite cannot do that.

Scoring is deliberately unforgiving. A case passes only when every one of its checks
passes, and four cases are negative controls that fail if the system over-reacts — flags
compatible facts, supersedes a legitimately multi-valued relation, or invents a source.
A system that just says yes to everything scores 0 on those.

Usage:
  uv run python benchmarks/maintained/run_maintained.py
  uv run python benchmarks/maintained/run_maintained.py --embedder fastembed --json out.json
  uv run python benchmarks/maintained/run_maintained.py --case currency/late-arriving-old-fact -v
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import traceback
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

from cases import CASES, CLAIMS, Case, Check  # noqa: E402

from memoose.embeddings import HashEmbedder, default_embedder  # noqa: E402
from memoose.engine import Engine  # noqa: E402


def run_case(c: Case, embedder_name: str) -> dict:
    """Each case gets its own store, so cases cannot contaminate one another."""
    t0 = time.time()
    keys = ("MEMOOSE_DATA_DIR", "MEMOOSE_PROJECT_DIR")
    saved = {k: os.environ.get(k) for k in keys}
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["MEMOOSE_DATA_DIR"] = str(Path(tmp) / "data")
        os.environ["MEMOOSE_PROJECT_DIR"] = str(Path(tmp) / "proj")
        embedder = HashEmbedder() if embedder_name == "hash" else default_embedder()
        engine = Engine(embedder=embedder)
        try:
            checks = c.fn(engine.dataset("maintained"))
            error = None
        except Exception:
            checks, error = [], traceback.format_exc(limit=6)
        finally:
            engine.close()
            for k, v in saved.items():  # the suite runs inside pytest too; leave the env as found
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    rows = [{"name": k.name, "ok": bool(k.ok), "detail": k.detail} for k in checks]
    return {
        "id": c.id, "claim": c.claim, "asks": c.asks, "negative": c.negative,
        "passed": bool(rows) and all(r["ok"] for r in rows) and error is None,
        "checks": rows, "error": error, "ms": round((time.time() - t0) * 1000, 1),
    }


def summarize(results: list[dict]) -> dict:
    by_claim: dict[str, dict] = defaultdict(lambda: {"cases": 0, "cases_passed": 0, "checks": 0, "checks_passed": 0})
    for r in results:
        for key in (r["claim"], "_all"):
            s = by_claim[key]
            s["cases"] += 1
            s["cases_passed"] += int(r["passed"])
            s["checks"] += len(r["checks"])
            s["checks_passed"] += sum(k["ok"] for k in r["checks"])
    neg = [r for r in results if r["negative"]]
    for s in by_claim.values():
        s["case_score"] = round(100.0 * s["cases_passed"] / s["cases"], 1) if s["cases"] else 0.0
        s["check_score"] = round(100.0 * s["checks_passed"] / s["checks"], 1) if s["checks"] else 0.0
    overall = by_claim.pop("_all")
    return {
        "overall": overall,
        "by_claim": dict(by_claim),
        "negative_controls": {"cases": len(neg), "passed": sum(r["passed"] for r in neg)},
        "failed": [r["id"] for r in results if not r["passed"]],
    }


def report(results: list[dict], summary: dict, verbose: bool) -> None:
    w = max(len(r["id"]) for r in results)
    print(f"\n{'case'.ljust(w)}  checks  result")
    print("-" * (w + 20))
    for claim in CLAIMS:
        print(f"\n# {claim} — {CLAIMS[claim]}")
        for r in [x for x in results if x["claim"] == claim]:
            n_ok = sum(k["ok"] for k in r["checks"])
            mark = "PASS" if r["passed"] else "FAIL"
            tag = " (negative control)" if r["negative"] else ""
            print(f"{r['id'].ljust(w)}  {n_ok}/{len(r['checks']):<5}  {mark}{tag}")
            if r["error"]:
                print(f"    ERROR: {r['error'].strip().splitlines()[-1]}")
            for k in r["checks"]:
                if not k["ok"] or verbose:
                    print(f"    {'ok ' if k['ok'] else 'BAD'} {k['name']}" + (f" — {k['detail'][:200]}" if k["detail"] and not k["ok"] else ""))

    print("\n" + "=" * (w + 20))
    print(f"{'claim'.ljust(14)} {'cases':>12} {'checks':>12}")
    for claim, s in list(summary["by_claim"].items()) + [("OVERALL", summary["overall"])]:
        cases = f"{s['cases_passed']}/{s['cases']}"
        checks = f"{s['checks_passed']}/{s['checks']}"
        if claim == "OVERALL":
            print("-" * (w + 20))
        print(f"{claim.ljust(14)} {cases:>12} {checks:>12}")
    o, nc = summary["overall"], summary["negative_controls"]
    print(f"case score {o['case_score']}%   check score {o['check_score']}%   negative controls {nc['passed']}/{nc['cases']}")
    if summary["failed"]:
        print("failed: " + ", ".join(summary["failed"]))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--embedder", choices=["hash", "fastembed"], default="hash", help="hash is deterministic and needs no download; fastembed is what ships by default.")
    ap.add_argument("--case", action="append", help="run only these case ids (repeatable)")
    ap.add_argument("--claim", action="append", choices=list(CLAIMS), help="run only these claims (repeatable)")
    ap.add_argument("--json", type=Path, help="write the full result to this file")
    ap.add_argument("-v", "--verbose", action="store_true", help="show passing checks too")
    a = ap.parse_args(argv)

    selected = [c for c in CASES if (not a.case or c.id in a.case) and (not a.claim or c.claim in a.claim)]
    if not selected:
        print("no cases matched", file=sys.stderr)
        return 2

    results = [run_case(c, a.embedder) for c in selected]
    summary = summarize(results)
    report(results, summary, a.verbose)

    payload = {"benchmark": "maintained-memory", "embedder": a.embedder, "model_calls": 0, "summary": summary, "results": results}
    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(json.dumps(payload, indent=2) + "\n")
        print(f"\nwrote {a.json}")
    return 0 if not summary["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
