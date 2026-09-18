"""`memoose view`: the knowledge graph as one self-contained HTML file.

No server and nothing uploaded: the entities and facts are inlined as JSON, and so is the drawing
library (vis-network, downloaded from cdnjs once and cached; the request for it is the only thing
that ever leaves the machine, and it carries none of your data). The file opens offline from a
file:// URL and can be handed to someone.

Colour is the entity type, a diamond is a Procedure, a dashed grey edge is a superseded fact
(shown only with --superseded). Hover an edge for its description and evidence, click a node
for everything memory holds about it, type in the box to find a name.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from .datasets import data_dir
from .store.sqlite_store import SqliteStore

VIS_JS = "https://cdnjs.cloudflare.com/ajax/libs/vis-network/9.1.9/standalone/umd/vis-network.min.js"


def vis_source() -> tuple[str, bool]:
    """The drawing library as inline script text, fetched once and cached under the data dir.

    Inlining is what makes the page a single file that opens offline and can be handed to
    someone. The first `memoose view` on a machine downloads it (about 690 KB); if that fails
    the page falls back to a CDN <script> tag and says so, rather than rendering nothing.
    """
    version = VIS_JS.split("/vis-network/")[1].split("/")[0]  # "9.1.9"
    cache = data_dir() / "cache" / f"vis-network-{version}.min.js"
    try:
        if not cache.exists():
            cache.parent.mkdir(parents=True, exist_ok=True)
            with urllib.request.urlopen(VIS_JS, timeout=30) as r:  # noqa: S310 - fixed https URL
                cache.write_bytes(r.read())
        return cache.read_text(encoding="utf-8"), True
    except (OSError, UnicodeDecodeError):
        return f'</script><script src="{VIS_JS}"></script><script>', False


def export_graph(store: SqliteStore, include_superseded: bool = False) -> dict:
    ents = store.all_entities()
    sup = "" if include_superseded else " WHERE superseded=0"
    rels = store.conn.execute(f"SELECT * FROM relations{sup} ORDER BY updated_at DESC").fetchall()
    known = {e.id for e in ents}
    edges = [
        {
            "id": r["id"], "from": r["source_id"], "to": r["target_id"], "name": r["name"],
            "description": r["description"] or "", "evidence": r["evidence"],
            "valid_from": r["valid_from"], "valid_to": r["valid_to"], "superseded": bool(r["superseded"]),
        }
        for r in rels if r["source_id"] in known and r["target_id"] in known
    ]
    return {
        "nodes": [{"id": e.id, "name": e.name, "type": e.type, "description": e.description, "mentions": e.mentions} for e in ents],
        "edges": edges,
        "types": sorted({e.type for e in ents}),
        "stats": store.stats(),
    }


def render_html(graph: dict, dataset: str, vis: str | None = None) -> str:
    # `</` inside a <script> block would end it early; JSON never needs the raw form.
    data = json.dumps(graph, ensure_ascii=False).replace("</", "<\\/")
    if vis is None:
        vis, _ = vis_source()
    return TEMPLATE.replace("__DATA__", data).replace("__DATASET__", dataset).replace("__VIS__", vis)


def write_graph(store: SqliteStore, dataset: str, out: Path, include_superseded: bool = False) -> dict:
    graph = export_graph(store, include_superseded)
    vis, inlined = vis_source()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(graph, dataset, vis), encoding="utf-8")
    return {"dataset": dataset, "path": str(out), "nodes": len(graph["nodes"]), "edges": len(graph["edges"]), "types": graph["types"], "self_contained": inlined}


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>memoose · __DATASET__</title>
<style>
  :root { color-scheme: light dark;
    --bg: #fbfaf7; --fg: #1d1d1b; --muted: #6b6b66; --panel: #ffffff; --line: #e4e2dc; --accent: #2f6f4e; }
  @media (prefers-color-scheme: dark) { :root {
    --bg: #17181a; --fg: #e8e6e1; --muted: #9a9892; --panel: #1f2023; --line: #33353a; --accent: #7fc8a0; } }
  html, body { margin: 0; height: 100%; background: var(--bg); color: var(--fg);
    font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
  body { display: flex; flex-direction: column; }
  #top { display: flex; gap: 12px; align-items: center; padding: 10px 14px; border-bottom: 1px solid var(--line); background: var(--panel); }
  #top h1 { font-size: 15px; margin: 0; font-weight: 600; }
  #top .stats { color: var(--muted); font-size: 13px; }
  #q { margin-left: auto; padding: 6px 10px; border: 1px solid var(--line); border-radius: 6px; background: var(--bg); color: var(--fg); min-width: 240px; }
  #legend { display: flex; flex-wrap: wrap; gap: 6px 12px; padding: 8px 14px; border-bottom: 1px solid var(--line); font-size: 13px; }
  #legend button { border: 1px solid var(--line); background: var(--panel); color: var(--fg); border-radius: 999px; padding: 2px 10px; cursor: pointer; display: inline-flex; align-items: center; gap: 6px; }
  #legend button.off { opacity: .35; }
  #legend .dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
  #main { display: grid; grid-template-columns: 1fr 340px; flex: 1; min-height: 0; }
  #net { min-height: 400px; height: 100%; }
  #side { border-left: 1px solid var(--line); background: var(--panel); padding: 14px; overflow: auto; }
  #side h2 { font-size: 15px; margin: 0 0 4px; }
  #side .type { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }
  #side p { margin: 8px 0; }
  #side ul { padding-left: 0; list-style: none; margin: 10px 0 0; }
  #side li { padding: 8px 0; border-top: 1px solid var(--line); }
  #side li.stale { opacity: .55; }
  #side .ev { color: var(--muted); font-size: 12px; }
  #side code { background: var(--bg); padding: 1px 5px; border-radius: 4px; font-size: 12px; }
  #side .hint { color: var(--muted); }
  @media (max-width: 800px) { #main { grid-template-columns: 1fr; } #side { display: none; } }
</style>
</head>
<body>
<div id="top">
  <h1>memoose · __DATASET__</h1>
  <span class="stats" id="stats"></span>
  <input id="q" type="search" placeholder="find a name…" autocomplete="off">
</div>
<div id="legend"></div>
<div id="main">
  <div id="net"></div>
  <aside id="side"><p class="hint">Click a node for what memory holds about it. Hover an edge for its evidence. Colour is the entity type; a diamond is a Procedure.</p></aside>
</div>
<script>__VIS__</script>
<script>
const G = __DATA__;
const netEl = document.getElementById("net");
function fail(msg) { netEl.innerHTML = `<p style="padding:20px;color:var(--muted)">${msg}</p>`; }
window.addEventListener("error", ev => fail("The graph could not be drawn: " + (ev.message || ev.error)));
if (typeof vis === "undefined") { fail("The drawing library did not load. The page was written without network access; run <code>memoose view</code> again once online, and the library is cached for good."); throw new Error("vis missing"); }
const PALETTE = ["#2f6f4e","#3b6ea8","#b5541b","#7b4fa0","#a8322f","#2a8a8a","#8a7a1e","#5b6b3a","#8c3f6b","#4a6f8a","#c07a10","#4c8c4a","#6f4f2c","#3d5a99","#9a4a2a","#2e7f6a","#7a5a9a","#555"];
const color = Object.fromEntries(G.types.map((t, i) => [t, PALETTE[i % PALETTE.length]]));
const byId = Object.fromEntries(G.nodes.map(n => [n.id, n]));
const hidden = new Set();
let query = "";

const nodes = new vis.DataSet(G.nodes.map(n => ({
  id: n.id, label: n.name, group: n.type,
  shape: n.type === "Procedure" ? "diamond" : "dot",
  size: 10 + Math.min(20, Math.log2(1 + (n.mentions || 1)) * 5),
  color: { background: color[n.type], border: color[n.type], highlight: { background: color[n.type], border: "#000" } },
  font: { color: getComputedStyle(document.documentElement).getPropertyValue("--fg").trim() || "#222", size: 13 },
  title: n.description || n.name,
})));
const edges = new vis.DataSet(G.edges.map(e => ({
  id: e.id, from: e.from, to: e.to, label: e.name,
  arrows: "to",
  dashes: e.superseded, color: e.superseded ? { color: "#999", opacity: .5 } : { color: "#8d8d88", opacity: .75 },
  font: { size: 10, align: "middle", color: "#8d8d88", strokeWidth: 0 },
  title: [e.description, e.evidence ? "evidence: " + e.evidence : "", e.valid_from ? "from " + e.valid_from : "", e.superseded ? "SUPERSEDED" : ""].filter(Boolean).join("\n"),
})));

const big = G.nodes.length > 300;
const net = new vis.Network(netEl, { nodes, edges }, {
  autoResize: true,
  physics: { solver: "forceAtlas2Based", stabilization: { iterations: big ? 150 : 400 }, forceAtlas2Based: { gravitationalConstant: -60, springLength: 120 } },
  interaction: { hover: true, tooltipDelay: 120, navigationButtons: false },
  edges: { smooth: { type: "continuous" }, width: 1.2 },
});
net.once("stabilizationIterationsDone", () => { if (big) net.setOptions({ physics: false }); net.fit({ animation: false }); });
window.addEventListener("load", () => { net.redraw(); net.fit({ animation: false }); });

document.getElementById("stats").textContent = `${G.nodes.length} entities · ${G.edges.length} facts` + (G.stats.superseded_relations ? ` · ${G.stats.superseded_relations} superseded` : "");

const legend = document.getElementById("legend");
for (const t of G.types) {
  const b = document.createElement("button");
  b.innerHTML = `<span class="dot" style="background:${color[t]}"></span>${t} <span style="opacity:.6">${G.nodes.filter(n => n.type === t).length}</span>`;
  b.onclick = () => { b.classList.toggle("off"); hidden.has(t) ? hidden.delete(t) : hidden.add(t); refresh(); };
  legend.appendChild(b);
}

function refresh() {
  const q = query.toLowerCase();
  nodes.update(G.nodes.map(n => {
    const dim = hidden.has(n.type) || (q && !n.name.toLowerCase().includes(q) && !(n.description || "").toLowerCase().includes(q));
    return { id: n.id, hidden: hidden.has(n.type), opacity: q && dim ? .15 : 1 };
  }));
}
document.getElementById("q").addEventListener("input", ev => { query = ev.target.value.trim(); refresh(); });

net.on("click", p => {
  const side = document.getElementById("side");
  if (!p.nodes.length) return;
  const n = byId[p.nodes[0]];
  const facts = G.edges.filter(e => e.from === n.id || e.to === n.id);
  const li = facts.map(e => {
    const s = byId[e.from]?.name ?? "?", t = byId[e.to]?.name ?? "?";
    return `<li class="${e.superseded ? "stale" : ""}"><div><b>${esc(s)}</b> —${esc(e.name)}→ <b>${esc(t)}</b>${e.superseded ? " <code>superseded</code>" : ""}</div>` +
      (e.description ? `<div>${esc(e.description)}</div>` : "") +
      `<div class="ev">${e.evidence ? esc(e.evidence) : ""}${e.valid_from ? " · from " + esc(e.valid_from) : ""}</div></li>`;
  }).join("");
  side.innerHTML = `<div class="type">${esc(n.type)} · ${n.mentions || 1} mention${(n.mentions || 1) === 1 ? "" : "s"}</div><h2>${esc(n.name)}</h2>` +
    (n.description ? `<p>${esc(n.description)}</p>` : "") +
    `<p class="hint">${facts.length} fact${facts.length === 1 ? "" : "s"}</p><ul>${li || "<li class='hint'>no facts yet</li>"}</ul>`;
});
function esc(s) { return String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
</script>
</body>
</html>
"""
