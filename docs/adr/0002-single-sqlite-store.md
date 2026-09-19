---
status: accepted
---

# One SQLite database per Dataset instead of a metadata + graph + vector store trio

Graph memory libraries typically split metadata, graph, and vectors across three stores. memoose is a plugin that must install cleanly via `uvx` on every developer machine and holds agent-scale memory, thousands of facts rather than millions, so we keep everything in a single SQLite file per Dataset: metadata tables, node and edge tables traversed with recursive queries, FTS5 for lexical search, and a vector extension for embeddings. One file per Dataset is trivial to open, back up, copy, or delete, and removes two native dependencies. The graph and vector access sits behind generic interfaces, so a dedicated graph or vector database can be introduced if a Dataset outgrows SQLite.
