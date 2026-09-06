---
status: accepted
---

# One SQLite database per Dataset instead of cognee's SQLite + Kuzu + LanceDB trio

cognee stores metadata in SQLite, the graph in Kuzu, and vectors in LanceDB. mnemoth is a plugin that must install cleanly via `uvx` on every developer machine and holds coding-agent-scale memory, thousands of facts rather than millions, so we keep everything in a single SQLite file per Dataset: metadata tables, node and edge tables traversed with recursive queries, FTS5 for lexical search, and a vector extension for embeddings. One file per Dataset is trivial to open, back up, copy, or delete, and removes two native dependencies. The graph and vector access sits behind interfaces shaped like cognee's, so Kuzu or LanceDB can be reintroduced if a Dataset outgrows SQLite.
