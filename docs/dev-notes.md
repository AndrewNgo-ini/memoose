# Dev notes — in-flight work

**Temporary. Delete this file once the entries below are resolved.** Nothing here is public-facing:
the README carries only finished, checked numbers.

## Found by dogfooding memoose on this repo (2026-09-10)

- **Fixed.** `--dataset` only parsed before the subcommand, so `memoose remember "..." --dataset user`
  (the order the skill teaches, and the order anyone writes) failed with a usage error. Now accepted
  in both positions.
- **Fixed.** Context rows came back from `recall` as raw JSON dicts, spending a model's context on
  `"confidence": 1.0` and friends. They render as `[rules] <content>` now.
- **Fixed.** `cross_connect` candidates degenerated on a young store (10 pairs like "Kuzu + Hieu Ngo"
  out of 11 entities, all from one chunk). `maintain` now requires two shared chunks, and a judged
  candidate can be dismissed with a reason so it never comes back.

## Not verified live

- The rewritten `hooks/capture.py` prompt drives the keeper through the CLI instead of MCP. Extraction
  quality has not been re-checked live since the prompt changed shape.
- `memoose maintain` has never been run end to end through the memory-keeper subagent.
- Procedural guidance (ADR 0004): the hint hook localising on the last tool call is unit-tested,
  not yet observed changing an agent's next action in a live session.
