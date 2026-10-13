"""
Draws the project map (ldz_demand.project_map) as one self-contained HTML document: an SVG diagram laid
out here in fixed columns, the map as JSON, and a little vanilla JavaScript for the interaction —

- click a box: it and everything upstream / downstream of it stay lit, the rest dims; the panel shows
  what's in it, where it lives, its modules (as files) and dashboard page;
- click an arrow: the process — commands, modules, config, where it runs;
- click the background or press Escape: clear.

No external libraries; colours from the active chart theme. Shown in the dashboard with mo.iframe.
"""

import html
import importlib.util
import json
from pathlib import Path

from ldz_demand import project_map as pm
from ldz_demand.charts import style
from ldz_demand.charts.pages import PAGES
from ldz_demand.config import get_project_root

ORIENTATION = "vertical"  # "vertical": the stages are bands, top to bottom; "horizontal": columns, left to right
PAD = 16
NODE_H = 58
MAX_SCALE = 1.15  # on wide screens, grow the map at most this much
STRIPE = "top"  # the stage colour on each box: "top" (a bar along the top) or "left" (down the left side)
INLINE_LABELS = ("Pre-CWV models",)  # vertical: stage labels level with the first boxes (the lane beside them is free)
BEHIND_AT = 0.72
SUBTITLE_MAX = 26  # characters (11 px text in a 168 px box; checked in the browser)  # "behind" arrows run at this fraction of the box width (beside the centre line)
H = dict(node_w=184, stage_step=234, slot_step=80, top=44, support_gap=70)   # horizontal: slot = down a column
V = dict(node_w=168, lane_step=184, depth_step=150, top=40, support_gap=1.1)  # vertical: Node.at = (lane, depth)


def _dims() -> dict:
    return V if ORIENTATION == "vertical" else H


def module_file(module: str) -> str | None:
    """'data.store' -> 'src/ldz_demand/data/store/__init__.py' (relative to the project root)."""
    spec = importlib.util.find_spec(f"ldz_demand.{module}")
    if spec is None or spec.origin is None:
        return None
    try:
        return str(Path(spec.origin).resolve().relative_to(get_project_root().resolve()))
    except ValueError:
        return spec.origin


def layout() -> dict:
    """Positions for every node, a path for every edge and the stage labels (SVG user units)."""
    d = _dims()
    w, vertical = d["node_w"], ORIENTATION == "vertical"
    stages = len(pm.COLUMNS)
    slots = max(n.row for n in pm.NODES if n.column is not None)
    support = [n for n in pm.NODES if n.column is None]

    if vertical:
        place = lambda n: (PAD + n.at[0] * d["lane_step"], d["top"] + n.at[1] * d["depth_step"])  # noqa: E731
        support_depth = max(n.at[1] for n in pm.NODES if n.column is not None) + d["support_gap"]
        support_at = lambda i: (PAD + i * d["lane_step"], d["top"] + support_depth * d["depth_step"])  # noqa: E731
    else:
        place = lambda n: (PAD + n.column * d["stage_step"], d["top"] + n.row * d["slot_step"])  # noqa: E731
        support_at = lambda i: (PAD + i * d["stage_step"], d["top"] + slots * d["slot_step"] + NODE_H + d["support_gap"])  # noqa: E731
    pos = {n.id: support_at(support.index(n)) if n.column is None else place(n) for n in pm.NODES}

    edges = []
    for e in pm.EDGES:
        path, mid = _route(e, pos, w, vertical)
        edges.append({"id": e.id, "d": path, "mid": mid})

    bands = []
    if vertical:  # each stage's label above its first (highest) box; two-word labels on two lines
        tops = [min(pos[n.id][1] for n in pm.NODES if n.column == c) for c in range(stages)] + [pos[support[0].id][1]]
        names = [name.rsplit(" ", 1) if " " in name else [name] for name in pm.COLUMNS] + [["Supporting — used throughout"]]
        inline = [i < stages and pm.COLUMNS[i] in INLINE_LABELS for i in range(len(tops))]
        labels = [(PAD, top + 13 if at_side else top - 12 - 14 * (len(lines) - 1), lines)
                  for top, lines, at_side in zip(tops, names, inline)]
        width = PAD * 2 + max(x for x, _ in pos.values()) - PAD + w
        height = pos[support[0].id][1] + NODE_H + PAD
        # a band per stage, from just above its label (or, inline, its first box) to the next one's
        starts = [top - 10 if at_side else y - 18 for (_, y, _), top, at_side in zip(labels, tops, inline)] + [height]
        bands = [(0.0 if i == 0 else starts[i], starts[i + 1]) for i in range(len(labels))]
    else:
        labels = [(PAD + c * d["stage_step"], d["top"] - 18, [name]) for c, name in enumerate(pm.COLUMNS)]
        labels.append((PAD, pos[support[0].id][1] - 14, ["Supporting — used throughout"]))
        width = PAD * 2 + (stages - 1) * d["stage_step"] + w
        height = pos[support[0].id][1] + NODE_H + PAD
    return {"pos": pos, "edges": edges, "labels": labels, "bands": bands, "width": width, "height": height, "node_w": w}


def _blocked(e, pos, w, ax, ay, bx, by) -> bool:
    """Does another box sit across the straight drop from (ax, ay) to (bx, by)?"""
    lo_x, hi_x, lo_y, hi_y = min(ax, bx) - 4, max(ax, bx) + 4, min(ay, by), max(ay, by)
    return any(x < hi_x and x + w > lo_x and y < hi_y and y + NODE_H > lo_y
               for nid, (x, y) in pos.items() if nid not in (e.source, e.target))


def _route(e, pos, w: float, vertical: bool) -> tuple[str, tuple[float, float]]:
    """
    An edge's SVG path and midpoint. Horizontal layout: side to side between columns, bottom to top
    within one. Vertical layout:
    - boxes side by side: side to side;
    - the target wholly to one side: an elbow, out of the source's side and down into the target's top;
    - otherwise a straight drop, bottom to top — or, if a box is in the way, a loop round its left side
      (or, with Edge.route "behind", straight on behind it).
    """
    (x1, y1), (x2, y2) = pos[e.source], pos[e.target]
    down = y2 >= y1
    if vertical and e.route == "behind":  # straight down, a little right of centre, behind boxes in the way
        ax, bx = x1 + w * BEHIND_AT, x2 + w * BEHIND_AT
        ay, by = (y1 + NODE_H, y2) if down else (y1, y2 + NODE_H)
        return f"M{ax},{ay} L{bx},{by}", (ax, (ay + by) / 2)
    same_stage = pm.node(e.source).column == pm.node(e.target).column
    side_by_side = abs(y1 - y2) < NODE_H if vertical else not same_stage
    if side_by_side:
        ax, bx = (x1 + w, x2) if x2 >= x1 else (x1, x2 + w)
        ay, by = y1 + NODE_H / 2, y2 + NODE_H / 2
        k = max(24.0, abs(bx - ax) * 0.5) * (1 if bx >= ax else -1)
        return f"M{ax},{ay} C{ax + k},{ay} {bx - k},{by} {bx},{by}", ((ax + bx) / 2, (ay + by) / 2)
    ax, bx = x1 + w / 2, x2 + w / 2
    ay, by = (y1 + NODE_H, y2) if down else (y1, y2 + NODE_H)
    if vertical and (x2 >= x1 + w or x2 + w <= x1):  # elbow
        ax = x1 + w if x2 > x1 else x1
        ay = y1 + NODE_H / 2
        path = f"M{ax},{ay} C{ax + (bx - ax) * 0.7},{ay} {bx},{ay + (by - ay) * 0.3} {bx},{by}"
        return path, (bx, (ay + by) / 2)
    if vertical and _blocked(e, pos, w, ax, ay, bx, by):  # loop round the left
        ax, bx, ay, by = x1, x2, y1 + NODE_H / 2, y2 + NODE_H / 2
        cx = min(x1, x2) - 30
        return f"M{ax},{ay} C{cx},{ay} {cx},{by} {bx},{by}", (cx + 8, (ay + by) / 2)
    k = max(24.0, abs(by - ay) * 0.5) * (1 if down else -1)
    return f"M{ax},{ay} C{ax},{ay + k} {bx},{by - k} {bx},{by}", ((ax + bx) / 2, (ay + by) / 2)


def _spec() -> dict:
    """The map as plain data for the page's script, with modules resolved to files and pages to paths."""
    nodes = []
    for n in pm.NODES:
        page = PAGES.get(n.page) if n.page else None
        nodes.append({"id": n.id, "column": n.column, "title": n.title, "summary": n.summary, "status": n.status,
                      "kind": pm.COLUMNS[n.column] if n.column is not None else "Supporting",
                      "details": n.details, "modules": [(m, module_file(m)) for m in n.modules],
                      "datasets": n.datasets, "files": n.files, "docs": n.docs,
                      "page": {"title": page.title, "path": page.path} if page else None})
    edges = [{"id": e.id, "source": e.source, "target": e.target, "process": e.process, "summary": e.summary,
              "commands": e.commands, "modules": [(m, module_file(m)) for m in e.modules], "config": e.config,
              "runs": e.runs, "details": e.details, "status": e.status} for e in pm.EDGES]
    return {"nodes": nodes, "edges": edges}


def subtitle(n: pm.Node) -> str:
    """The second line of a box: its table(s), else its first module, else nothing; 'planned' if so."""
    if n.datasets:
        text = ", ".join(n.datasets)
    elif n.modules:
        text = n.modules[0] + (f" +{len(n.modules) - 1}" if len(n.modules) > 1 else "")
    elif n.files:
        text = n.files[0].split("/")[-1] + (f" +{len(n.files) - 1}" if len(n.files) > 1 else "")
    else:
        text = ""
    if n.status == "planned":
        text = f"{text} · planned" if text else "planned"
    return text if len(text) <= SUBTITLE_MAX else text[:SUBTITLE_MAX - 1] + "…"


def _svg(lay: dict, theme: style.Theme) -> str:
    out = [f'<svg id="map" viewBox="0 0 {lay["width"]} {lay["height"]}" style="max-width:{lay["width"] * MAX_SCALE:.0f}px" '
           f'xmlns="http://www.w3.org/2000/svg" '
           f'role="img" aria-label="Project map: sources to datasets to pre-CWV models to the CWV model to outputs">',
           '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
           f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{theme.muted}"/></marker>'
           '<marker id="arrow-on" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
           f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{theme.accent}"/></marker></defs>',
           f'<rect class="bg" x="0" y="0" width="{lay["width"]}" height="{lay["height"]}" fill="transparent"/>']
    for i, (y0, y1) in enumerate(lay["bands"]):  # alternate stages shaded
        if i % 2:
            out.append(f'<rect class="band" x="0" y="{y0}" width="{lay["width"]}" height="{y1 - y0}"/>')
    for x, y, lines in lay["labels"]:
        spans = "".join(f'<tspan x="{x}" dy="{0 if i == 0 else 14}">{html.escape(t)}</tspan>' for i, t in enumerate(lines))
        out.append(f'<text class="col" x="{x}" y="{y}">{spans}</text>')
    w = lay["node_w"]
    for e, geo in zip(pm.EDGES, lay["edges"]):
        dash = ' stroke-dasharray="5 4"' if e.status == "planned" else ""
        out.append(f'<g class="edge" data-id="{html.escape(e.id)}">'
                   f'<path class="line" d="{geo["d"]}"{dash} marker-end="url(#arrow)"/>'
                   f'<path class="hit" d="{geo["d"]}"/>'
                   f'<title>{html.escape(e.process)}: {html.escape(e.summary)}</title></g>')
    for n in pm.NODES:
        x, y = lay["pos"][n.id]
        colour = theme.series[n.column] if n.column is not None else theme.muted
        dash = ' stroke-dasharray="5 4"' if n.status == "planned" else ""
        title = html.escape(n.title)
        sub = html.escape(subtitle(n))
        if STRIPE == "top":
            bar, tx, ty = f'<rect x="{x + 1}" y="{y + 1}" width="{w - 2}" height="3" rx="1.5" fill="{colour}"/>', x + 12, y + 27
        else:
            bar, tx, ty = f'<rect x="{x}" y="{y + 8}" width="4" height="{NODE_H - 16}" rx="2" fill="{colour}"/>', x + 14, y + 25
        sub_text = f'<text class="s" x="{tx}" y="{ty + 18}">{sub}</text>' if sub else ""
        out.append(f'<g class="node" data-id="{n.id}" tabindex="0" role="button" aria-label="{title}">'
                   f'<rect class="box" x="{x}" y="{y}" width="{w}" height="{NODE_H}" rx="6"{dash}/>{bar}'
                   f'<text class="t" x="{tx}" y="{ty if sub else ty + 6}">{title}</text>{sub_text}</g>')
    out.append("</svg>")
    return "".join(out)


_SCRIPT = r"""
const spec = JSON.parse(document.getElementById('spec').textContent);
const nodes = Object.fromEntries(spec.nodes.map(n => [n.id, n]));
const edges = Object.fromEntries(spec.edges.map(e => [e.id, e]));
const svg = document.getElementById('map'), panel = document.getElementById('panel'), body = document.getElementById('body');
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));

function reach(start, forward) {
  const seen = new Set([start]), todo = [start];
  while (todo.length) {
    const id = todo.pop();
    for (const e of spec.edges) {
      const [from, to] = forward ? [e.source, e.target] : [e.target, e.source];
      if (from === id && !seen.has(to)) { seen.add(to); todo.push(to); }
    }
  }
  return seen;
}

function light(nodeIds, edgeIds) {
  svg.classList.add('focus');
  svg.querySelectorAll('.node').forEach(g => g.classList.toggle('on', nodeIds.has(g.dataset.id)));
  svg.querySelectorAll('.edge').forEach(g => {
    const on = edgeIds.has(g.dataset.id);
    g.classList.toggle('on', on);
    g.querySelector('.line').setAttribute('marker-end', on ? 'url(#arrow-on)' : 'url(#arrow)');
  });
}

let moved = false;  // once dragged, the panel stays where it was put
function place(x) {  // open the panel on the side away from what was clicked
  if (moved) return;
  const left = x > svg.viewBox.baseVal.width / 2;
  panel.style.left = left ? '8px' : 'auto';
  panel.style.right = left ? 'auto' : '8px';
}

function clear() {
  svg.classList.remove('focus');
  svg.querySelectorAll('.on').forEach(g => g.classList.remove('on'));
  svg.querySelectorAll('.edge .line').forEach(p => p.setAttribute('marker-end', 'url(#arrow)'));
  panel.hidden = true;
}

const section = (label, html) => html ? `<h3>${label}</h3>${html}` : '';
const list = items => items.length ? `<ul>${items.join('')}</ul>` : '';
const details = d => d.length ? `<dl>${d.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('')}</dl>` : '';
const PREFIX = 'src/ldz_demand/';  // every module and model file lives here: shown once, as a note, not on each path
const short = f => f.startsWith(PREFIX) ? f.slice(PREFIX.length) : f;
const modules = ms => list(ms.map(([m, f]) => `<li><code>${esc(short(f || m))}</code></li>`));
const files = fs => list(fs.map(f => `<li><code>${esc(short(f))}</code></li>`));
const note = (ms, fs = []) => ms.length || fs.some(f => f.startsWith(PREFIX))
  ? `<p class="note">Code and file paths are under <code>${PREFIX}</code></p>` : '';
const links = ids => ids.map(id => `<a href="#" data-node="${id}">${esc(nodes[id].title)}</a>`).join(', ');

function showNode(id) {
  const n = nodes[id], up = reach(id, false), down = reach(id, true);
  place(spec.pos[id][0] + spec.nodeW / 2);
  const all = new Set([...up, ...down]);
  light(all, new Set(spec.edges.filter(e => all.has(e.source) && all.has(e.target) &&
    ((up.has(e.source) && up.has(e.target)) || (down.has(e.source) && down.has(e.target)))).map(e => e.id)));
  const from = spec.edges.filter(e => e.target === id).map(e => e.source);
  const into = spec.edges.filter(e => e.source === id).map(e => e.target);
  body.innerHTML = `<p class="kind">${esc(n.kind)}${n.status === 'planned' ? ' · planned' : ''}</p>
    <h2>${esc(n.title)}</h2><p>${esc(n.summary)}</p>${details(n.details)}
    ${section('Tables', list(n.datasets.map(d => `<li><code>${esc(d)}</code></li>`)))}
    ${section('Code', modules(n.modules))}
    ${section('Files', files(n.files))}
    ${section('Docs', list(n.docs.map(d => `<li>${esc(d)}</li>`)))}
    ${n.page ? section('Dashboard', `<p><a href="${n.page.path}" target="_top">${esc(n.page.title)} →</a></p>`) : ''}
    ${section('Fed by', from.length ? `<p>${links(from)}</p>` : '')}
    ${section('Feeds', into.length ? `<p>${links(into)}</p>` : '')}${note(n.modules, n.files)}`;
  panel.hidden = false;
}

function showEdge(id) {
  const e = edges[id];
  place(spec.edgeMid[id][0]);
  light(new Set([e.source, e.target]), new Set([id]));
  body.innerHTML = `<p class="kind">Process · ${esc(e.process)}${e.status === 'planned' ? ' · planned' : ''}</p>
    <h2>${esc(nodes[e.source].title)} → ${esc(nodes[e.target].title)}</h2><p>${esc(e.summary)}</p>${details(e.details)}
    ${section('Commands', e.commands.length ? `<pre>${e.commands.map(esc).join('\n')}</pre>` : '')}
    ${section('Code', modules(e.modules))}
    ${section('Config', e.config.length ? `<p>${e.config.map(c => `<code>[${esc(c)}]</code>`).join(' ')} in config/default.ini</p>` : '')}
    ${section('Runs', e.runs ? `<p>${esc(e.runs)}</p>` : '')}
    ${section('Ends', `<p>${links([e.source, e.target])}</p>`)}${note(e.modules)}`;
  panel.hidden = false;
}

svg.addEventListener('click', ev => {
  const n = ev.target.closest('.node'), e = ev.target.closest('.edge');
  if (n) showNode(n.dataset.id); else if (e) showEdge(e.dataset.id); else clear();
});
svg.addEventListener('keydown', ev => {
  const n = ev.target.closest('.node');
  if (n && (ev.key === 'Enter' || ev.key === ' ')) { ev.preventDefault(); showNode(n.dataset.id); }
});
body.addEventListener('click', ev => {
  const a = ev.target.closest('a[data-node]');
  if (a) { ev.preventDefault(); showNode(a.dataset.node); }
});
document.getElementById('close').addEventListener('click', clear);

// drag the panel by its top strip, kept inside the map
const handle = document.getElementById('handle'), MIN_PANEL = 160;
handle.addEventListener('pointerdown', ev => {
  ev.preventDefault();
  const wrap = panel.offsetParent.getBoundingClientRect(), r = panel.getBoundingClientRect();
  const dx = ev.clientX - r.left, dy = ev.clientY - r.top;
  handle.setPointerCapture(ev.pointerId);
  handle.onpointermove = e => {
    const x = Math.min(Math.max(0, e.clientX - wrap.left - dx), wrap.width - r.width);
    const y = Math.min(Math.max(0, e.clientY - wrap.top - dy), Math.max(0, wrap.height - MIN_PANEL));
    // lower down, the panel shrinks to the space left and scrolls inside
    Object.assign(panel.style, {left: x + 'px', top: y + 'px', right: 'auto', maxHeight: (wrap.height - y - 8) + 'px'});
    moved = true;
  };
  handle.onpointerup = () => { handle.onpointermove = null; };
});

// the map scales to the frame's width, so the frame follows the page's height
function fit() {
  try { const f = window.frameElement; if (f) f.style.height = Math.ceil(document.body.getBoundingClientRect().height) + 'px'; } catch (e) {}
}
new ResizeObserver(fit).observe(document.body);
window.addEventListener('load', fit);
document.addEventListener('keydown', ev => { if (ev.key === 'Escape') clear(); });
"""


def _css(theme: style.Theme) -> str:
    return f"""
:root {{ color-scheme: {theme.mode}; }}
html, body {{ margin: 0; background: {theme.page}; color: {theme.ink}; font-family: {theme.font}; }}
html {{ overflow: hidden; }}  /* the frame is sized to the page (fit() in the script) */
body {{ padding: 1px 0; }}     /* keeps the hint's margin inside the body, so it is measured */
.wrap {{ position: relative; }}
svg {{ display: block; width: 100%; height: auto; }}
.band {{ fill: {theme.ink}; fill-opacity: .035; }}
.col {{ fill: {theme.muted}; font-size: 12px; font-weight: 600; letter-spacing: .04em; text-transform: uppercase; }}
.node {{ cursor: pointer; outline: none; }}
.node .box {{ fill: {theme.surface}; stroke: {theme.axis}; stroke-width: 1; }}
.node:hover .box, .node:focus-visible .box {{ stroke: {theme.ink_2}; }}
.node .t {{ fill: {theme.ink}; font-size: 12px; font-weight: 600; }}
.node .s {{ fill: {theme.muted}; font-size: 11px; }}
.edge {{ cursor: pointer; }}
.edge .line {{ fill: none; stroke: {theme.muted}; stroke-width: 1.5; }}
.edge .hit {{ fill: none; stroke: transparent; stroke-width: 14; }}
.edge:hover .line {{ stroke: {theme.ink_2}; stroke-width: 2.5; }}
svg.focus .node:not(.on), svg.focus .edge:not(.on) {{ opacity: .22; }}
svg.focus .node.on .box {{ stroke: {theme.accent}; stroke-width: 1.5; }}
svg.focus .edge.on .line {{ stroke: {theme.accent}; stroke-width: 2.5; }}
#panel {{ position: absolute; top: 8px; right: 8px; width: min(340px, calc(100% - 16px)); max-height: calc(100% - 16px);
  overflow: auto; box-sizing: border-box; background: {theme.surface}; border: 1px solid {theme.axis};
  border-radius: 8px; padding: 18px 16px 14px; box-shadow: 0 8px 28px rgba(0,0,0,.35); font-size: 13px; line-height: 1.45; }}
#panel h2 {{ margin: 2px 0 6px; font-size: 16px; }}
#panel h3 {{ margin: 12px 0 4px; font-size: 11px; color: {theme.muted}; text-transform: uppercase; letter-spacing: .05em; }}
#panel p {{ margin: 4px 0; color: {theme.ink_2}; }}
#panel .kind {{ color: {theme.muted}; font-size: 11px; text-transform: uppercase; letter-spacing: .05em; margin: 0; }}
#panel ul {{ margin: 2px 0; padding-left: 0; list-style: none; color: {theme.ink_2}; }}
#panel li + li {{ margin-top: 2px; }}
#panel dl {{ margin: 8px 0 0; display: grid; grid-template-columns: max-content 1fr; gap: 3px 10px; }}
#panel dt {{ color: {theme.muted}; }}
#panel dd {{ margin: 0; color: {theme.ink_2}; }}
#panel code, #panel pre {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; color: {theme.ink}; }}
#panel pre {{ background: {theme.page}; border: 1px solid {theme.grid}; border-radius: 6px; padding: 8px; overflow-x: auto;
  white-space: pre; margin: 4px 0; }}
#panel a {{ color: {theme.accent}; }}
#panel .note {{ margin-top: 12px; padding-top: 8px; border-top: 1px solid {theme.grid}; font-size: 11px; color: {theme.muted}; }}
#panel .note code {{ font-size: 11px; color: {theme.muted}; }}
#panel li code, #panel p code, #panel dd {{ overflow-wrap: anywhere; }}  /* long file paths wrap in the narrow panel */
#handle {{ position: absolute; top: 0; left: 0; right: 32px; height: 14px; cursor: move; touch-action: none; }}
#handle::after {{ content: ""; position: absolute; left: 50%; top: 5px; width: 36px; height: 4px; margin-left: -18px;
  border-radius: 2px; background: {theme.axis}; }}
#handle:hover::after {{ background: {theme.muted}; }}
#close {{ position: absolute; top: 8px; right: 10px; background: none; border: 0; color: {theme.muted}; font-size: 18px;
  cursor: pointer; line-height: 1; }}
#close:hover {{ color: {theme.ink}; }}
.hint {{ color: {theme.muted}; font-size: 12px; margin: 4px {PAD}px 8px; }}
"""


def html_page(theme: style.Theme | None = None) -> str:
    """The whole map as one HTML document."""
    theme = theme or style.active()
    lay = layout()
    spec = json.dumps({**_spec(), "pos": lay["pos"], "edgeMid": {e["id"]: e["mid"] for e in lay["edges"]},
                       "nodeW": lay["node_w"]}).replace("</", "<\\/")
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1"><title>Project map</title>'
            f'<style>{_css(theme)}</style></head><body>'
            f'<p class="hint">Click a box for what\'s in it and everything it feeds or is fed by; click an arrow for '
            f'the process behind it. Dashed: planned. Esc clears.</p>'
            f'<div class="wrap">{_svg(lay, theme)}'
            f'<aside id="panel" hidden><div id="handle" title="Drag to move"></div>'
            f'<button id="close" aria-label="Close">×</button><div id="body"></div></aside></div>'
            f'<script type="application/json" id="spec">{spec}</script><script>{_SCRIPT}</script></body></html>')


def height_px() -> int:
    """Starting iframe height (the map at its natural size, plus the hint line). The page then sets its
    frame's height to fit, as the map scales with the width."""
    return int(layout()["height"]) + 48
