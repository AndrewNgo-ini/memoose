"""The maintained-memory benchmark, run as tests.

It needs no model and no network, so the claims mnemoth actually makes — a fact changed,
two sources disagree, where did this come from, we learned this before — are checked on
every commit rather than in an occasional paid benchmark run. See
`benchmarks/maintained/README.md`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BENCH = Path(__file__).resolve().parents[1] / "benchmarks" / "maintained"
sys.path.insert(0, str(BENCH))

from cases import CASES  # noqa: E402
from run_maintained import run_case  # noqa: E402


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_maintained_case(case):
    r = run_case(case, "hash")
    assert r["error"] is None, r["error"]
    bad = [c["name"] + (f" — {c['detail']}" if c["detail"] else "") for c in r["checks"] if not c["ok"]]
    assert not bad, f"{case.id} asks: {case.asks}\n" + "\n".join(bad)


def test_every_claim_has_a_negative_control_somewhere():
    """A suite of only positive assertions would be passed by a system that says yes to everything."""
    assert sum(c.negative for c in CASES) >= 3
