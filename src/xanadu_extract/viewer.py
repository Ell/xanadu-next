"""Generate a static HTML viewer that browses the extracted assets."""

from __future__ import annotations

import argparse
import html
import json
import sys
from collections import defaultdict
from pathlib import Path

INDEX_NAME = "index.html"

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Xanadu Next assets</title>
<style>
  :root {{
    --bg: #0f1014;
    --panel: #181a21;
    --border: #262a35;
    --fg: #e7e7ea;
    --muted: #8a8e9c;
    --accent: #c7a86b;
  }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; background: var(--bg); color: var(--fg);
                font: 13px/1.4 ui-sans-serif, system-ui, sans-serif; }}
  header {{ padding: 14px 18px; background: var(--panel);
            border-bottom: 1px solid var(--border); display: flex;
            align-items: baseline; gap: 16px; flex-wrap: wrap; }}
  header h1 {{ margin: 0; font-size: 16px; font-weight: 600; }}
  header .meta {{ color: var(--muted); font-size: 12px; }}
  nav {{ display: flex; gap: 6px; padding: 10px 18px; background: var(--panel);
         border-bottom: 1px solid var(--border); flex-wrap: wrap; }}
  nav button {{ background: transparent; border: 1px solid var(--border);
                color: var(--fg); padding: 4px 10px; border-radius: 4px;
                cursor: pointer; font: inherit; }}
  nav button.active {{ border-color: var(--accent); color: var(--accent); }}
  nav input {{ flex: 1; min-width: 200px; background: var(--bg);
               color: var(--fg); border: 1px solid var(--border);
               border-radius: 4px; padding: 4px 8px; font: inherit; }}
  main {{ padding: 16px 18px 60px; }}
  .section {{ margin-bottom: 28px; }}
  .section h2 {{ font-size: 13px; text-transform: uppercase; letter-spacing: 0.06em;
                 color: var(--muted); margin: 0 0 10px; font-weight: 600; }}
  .grid {{ display: grid; gap: 10px;
           grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); }}
  .tile {{ background: var(--panel); border: 1px solid var(--border);
           border-radius: 4px; padding: 8px; overflow: hidden;
           display: flex; flex-direction: column; gap: 6px;
           cursor: zoom-in; transition: border-color 0.1s; }}
  .tile:hover {{ border-color: var(--accent); }}
  .tile img {{ width: 100%; height: 100px; object-fit: contain;
               background: repeating-conic-gradient(#1d1f27 0 25%, #14161c 0 50%) 50%/12px 12px;
               image-rendering: pixelated; }}
  .tile .name {{ font-size: 11px; color: var(--fg); word-break: break-all;
                 line-height: 1.3; }}
  .tile .dim {{ font-size: 10px; color: var(--muted); }}
  /* Lightbox */
  .lb {{ position: fixed; inset: 0; background: rgba(8, 9, 12, 0.94);
         display: none; flex-direction: column; z-index: 100; }}
  .lb.open {{ display: flex; }}
  .lb-bar {{ display: flex; align-items: center; gap: 12px; padding: 10px 16px;
             background: var(--panel); border-bottom: 1px solid var(--border);
             color: var(--fg); }}
  .lb-bar .lb-name {{ flex: 1; font-size: 12px; word-break: break-all;
                      color: var(--fg); }}
  .lb-bar .lb-meta {{ font-size: 11px; color: var(--muted); white-space: nowrap; }}
  .lb-bar button {{ background: transparent; border: 1px solid var(--border);
                    color: var(--fg); padding: 4px 10px; border-radius: 4px;
                    cursor: pointer; font: inherit; }}
  .lb-bar button:hover {{ border-color: var(--accent); color: var(--accent); }}
  .lb-stage {{ flex: 1; overflow: hidden; cursor: grab; position: relative;
               background: repeating-conic-gradient(#1d1f27 0 25%, #14161c 0 50%) 50%/24px 24px; }}
  .lb-stage.dragging {{ cursor: grabbing; }}
  .lb-stage img {{ position: absolute; left: 50%; top: 50%;
                   transform-origin: 0 0; image-rendering: pixelated;
                   user-select: none; -webkit-user-drag: none; }}
  .audio-row {{ display: flex; align-items: center; gap: 10px; padding: 6px 0;
                border-bottom: 1px solid var(--border); }}
  .audio-row .name {{ flex: 1; font-size: 12px; color: var(--fg); }}
  .audio-row audio {{ height: 28px; }}
  details {{ background: var(--panel); border: 1px solid var(--border);
             border-radius: 4px; margin-bottom: 8px; }}
  details summary {{ padding: 8px 12px; cursor: pointer; font-weight: 500;
                     color: var(--fg); }}
  details[open] summary {{ border-bottom: 1px solid var(--border); }}
  details .body {{ padding: 12px; }}
  .video-list a {{ color: var(--accent); display: block; padding: 4px 0; }}
  .hidden {{ display: none !important; }}
</style>
</head>
<body>
<header>
  <h1>Xanadu Next — assets</h1>
  <div class="meta">{counts}</div>
  <a href="debug.html" style="margin-left:auto;color:var(--accent);font-size:12px">debug ↗</a>
</header>
<nav>
  <button data-view="images" class="active">Images</button>
  <button data-view="audio">Audio</button>
  <button data-view="video">Video</button>
  <input id="filter" type="search" placeholder="Filter by name…">
</nav>
<main>
  <div id="view-images">{images_html}</div>
  <div id="view-audio" class="hidden">{audio_html}</div>
  <div id="view-video" class="hidden">{video_html}</div>
</main>

<div class="lb" id="lb" role="dialog" aria-modal="true" hidden>
  <div class="lb-bar">
    <div class="lb-name" id="lb-name"></div>
    <div class="lb-meta" id="lb-meta"></div>
    <button id="lb-zoom-out" title="Zoom out (-)">−</button>
    <button id="lb-zoom-fit" title="Fit to window (0)">fit</button>
    <button id="lb-zoom-1" title="Actual size (1)">1:1</button>
    <button id="lb-zoom-in" title="Zoom in (+)">+</button>
    <button id="lb-prev" title="Previous (←)">‹</button>
    <button id="lb-next" title="Next (→)">›</button>
    <a id="lb-open" target="_blank" rel="noreferrer">open ↗</a>
    <button id="lb-close" title="Close (Esc)">close</button>
  </div>
  <div class="lb-stage" id="lb-stage">
    <img id="lb-img" alt="">
  </div>
</div>

<script>
const buttons = document.querySelectorAll('nav button');
const views = {{
  images: document.getElementById('view-images'),
  audio:  document.getElementById('view-audio'),
  video:  document.getElementById('view-video'),
}};
buttons.forEach(b => b.addEventListener('click', () => {{
  buttons.forEach(x => x.classList.toggle('active', x === b));
  Object.entries(views).forEach(([k, el]) => el.classList.toggle('hidden', k !== b.dataset.view));
}}));

const filter = document.getElementById('filter');
filter.addEventListener('input', () => {{
  const q = filter.value.trim().toLowerCase();
  document.querySelectorAll('[data-name]').forEach(el => {{
    const match = !q || el.dataset.name.toLowerCase().includes(q);
    el.classList.toggle('hidden', !match);
  }});
  document.querySelectorAll('.section').forEach(sec => {{
    const visible = [...sec.querySelectorAll('[data-name]')].some(el => !el.classList.contains('hidden'));
    sec.classList.toggle('hidden', !visible);
  }});
}});

// ---- Lightbox -----------------------------------------------------
const lb = document.getElementById('lb');
const lbImg = document.getElementById('lb-img');
const lbName = document.getElementById('lb-name');
const lbMeta = document.getElementById('lb-meta');
const lbStage = document.getElementById('lb-stage');
const lbOpen = document.getElementById('lb-open');

let tiles = [];          // visible image tiles
let currentIdx = -1;     // index into `tiles`
let scale = 1;           // current zoom
let tx = 0, ty = 0;      // translation in CSS px
let natW = 0, natH = 0;  // natural image dims

function refreshTiles() {{
  tiles = [...document.querySelectorAll('#view-images .tile')]
    .filter(t => !t.classList.contains('hidden'));
}}

function applyTransform() {{
  lbImg.style.transform =
    `translate(-50%, -50%) translate(${{tx}}px, ${{ty}}px) scale(${{scale}})`;
}}

function fitToStage() {{
  const r = lbStage.getBoundingClientRect();
  const pad = 32;
  const sx = (r.width - pad) / natW;
  const sy = (r.height - pad) / natH;
  scale = Math.max(0.05, Math.min(sx, sy));
  // For tiny pixel-art (sub-100px), prefer integer-step zoom up.
  if (natW < 200 && natH < 200) {{
    scale = Math.max(1, Math.floor(scale));
  }}
  tx = 0; ty = 0;
  applyTransform();
}}

function zoomAt(factor, cx, cy) {{
  const r = lbStage.getBoundingClientRect();
  // Convert cursor position to centered-stage coords.
  const sx = cx - r.left - r.width / 2;
  const sy = cy - r.top - r.height / 2;
  const newScale = Math.max(0.05, Math.min(64, scale * factor));
  // Keep cursor anchor stable: solve for new tx/ty.
  tx = sx - (sx - tx) * (newScale / scale);
  ty = sy - (sy - ty) * (newScale / scale);
  scale = newScale;
  applyTransform();
}}

function openLightbox(idx) {{
  if (idx < 0 || idx >= tiles.length) return;
  refreshTiles();
  currentIdx = idx;
  const tile = tiles[idx];
  const src = tile.dataset.src;
  const name = tile.dataset.name;
  lbName.textContent = name;
  lbMeta.textContent = '';
  lbOpen.href = src;
  lb.hidden = false;
  lb.classList.add('open');
  lbImg.onload = () => {{
    natW = lbImg.naturalWidth;
    natH = lbImg.naturalHeight;
    lbMeta.textContent = `${{natW}} × ${{natH}}`;
    fitToStage();
  }};
  lbImg.src = src;
}}

function closeLightbox() {{
  lb.classList.remove('open');
  lb.hidden = true;
  lbImg.src = '';
  currentIdx = -1;
}}

function step(d) {{
  if (currentIdx < 0) return;
  refreshTiles();
  const next = (currentIdx + d + tiles.length) % tiles.length;
  openLightbox(next);
}}

document.addEventListener('click', (e) => {{
  const tile = e.target.closest('#view-images .tile');
  if (!tile) return;
  refreshTiles();
  openLightbox(tiles.indexOf(tile));
}});

document.getElementById('lb-close').addEventListener('click', closeLightbox);
document.getElementById('lb-zoom-in').addEventListener('click', () => {{
  const r = lbStage.getBoundingClientRect();
  zoomAt(2, r.left + r.width / 2, r.top + r.height / 2);
}});
document.getElementById('lb-zoom-out').addEventListener('click', () => {{
  const r = lbStage.getBoundingClientRect();
  zoomAt(0.5, r.left + r.width / 2, r.top + r.height / 2);
}});
document.getElementById('lb-zoom-fit').addEventListener('click', fitToStage);
document.getElementById('lb-zoom-1').addEventListener('click', () => {{
  scale = 1; tx = 0; ty = 0; applyTransform();
}});
document.getElementById('lb-prev').addEventListener('click', () => step(-1));
document.getElementById('lb-next').addEventListener('click', () => step(1));

document.addEventListener('keydown', (e) => {{
  if (lb.hidden) return;
  if (e.key === 'Escape') closeLightbox();
  else if (e.key === 'ArrowLeft') step(-1);
  else if (e.key === 'ArrowRight') step(1);
  else if (e.key === '+' || e.key === '=') {{
    const r = lbStage.getBoundingClientRect();
    zoomAt(2, r.left + r.width / 2, r.top + r.height / 2);
  }} else if (e.key === '-' || e.key === '_') {{
    const r = lbStage.getBoundingClientRect();
    zoomAt(0.5, r.left + r.width / 2, r.top + r.height / 2);
  }} else if (e.key === '0') fitToStage();
  else if (e.key === '1') {{
    scale = 1; tx = 0; ty = 0; applyTransform();
  }}
}});

// Click-outside-image to close.
lbStage.addEventListener('mousedown', (e) => {{
  if (e.target === lbImg) return;
  // Plain click on empty area closes; drag still works because we only close
  // if the mouse hasn't moved much by mouseup.
  let moved = false;
  const onMove = () => {{ moved = true; }};
  const onUp = () => {{
    document.removeEventListener('mousemove', onMove);
    document.removeEventListener('mouseup', onUp);
    if (!moved) closeLightbox();
  }};
  document.addEventListener('mousemove', onMove);
  document.addEventListener('mouseup', onUp);
}});

// Wheel zoom (anchored at cursor).
lbStage.addEventListener('wheel', (e) => {{
  if (lb.hidden) return;
  e.preventDefault();
  const factor = e.deltaY < 0 ? 1.25 : 0.8;
  zoomAt(factor, e.clientX, e.clientY);
}}, {{ passive: false }});

// Drag to pan.
let dragging = false, dragStart = null;
lbImg.addEventListener('mousedown', (e) => {{
  e.preventDefault();
  dragging = true;
  dragStart = {{ x: e.clientX - tx, y: e.clientY - ty }};
  lbStage.classList.add('dragging');
}});
document.addEventListener('mousemove', (e) => {{
  if (!dragging) return;
  tx = e.clientX - dragStart.x;
  ty = e.clientY - dragStart.y;
  applyTransform();
}});
document.addEventListener('mouseup', () => {{
  dragging = false;
  lbStage.classList.remove('dragging');
}});

window.addEventListener('resize', () => {{
  if (!lb.hidden && currentIdx >= 0) fitToStage();
}});
</script>
</body>
</html>
"""


def find_assets(root: Path) -> dict[str, dict[str, list[Path]]]:
    """Group assets by (kind, top-level archive)."""
    groups: dict[str, dict[str, list[Path]]] = {
        "images": defaultdict(list),
        "audio": defaultdict(list),
        "video": defaultdict(list),
    }
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        ext = path.suffix.lower()
        # Group key = first two parts (e.g. "DATA/picture") or the first part.
        key = "/".join(rel.parts[:2]) if len(rel.parts) > 1 else rel.parts[0]
        if ext == ".png":
            groups["images"][key].append(path)
        elif ext == ".wav":
            groups["audio"][key].append(path)
        elif ext == ".avi":
            groups["video"][key].append(path)
    return groups


def render_image_section(group: str, paths: list[Path], root: Path) -> str:
    tiles: list[str] = []
    paths.sort()
    for p in paths:
        rel = p.relative_to(root).as_posix()
        name = p.relative_to(root / group.split("/")[0]).as_posix() if "/" in group else p.name
        tiles.append(
            f'<div class="tile" data-name="{html.escape(rel)}" '
            f'data-src="{html.escape(rel)}">'
            f'<img loading="lazy" src="{html.escape(rel)}" alt="">'
            f'<div class="name">{html.escape(name)}</div>'
            f'</div>'
        )
    body = f'<div class="grid">{"".join(tiles)}</div>'
    return (
        f'<details open class="section"><summary>{html.escape(group)} '
        f'<span style="color:var(--muted);font-weight:400">({len(paths)})</span>'
        f'</summary><div class="body">{body}</div></details>'
    )


def render_audio_section(group: str, paths: list[Path], root: Path) -> str:
    paths.sort()
    rows: list[str] = []
    for p in paths:
        rel = p.relative_to(root).as_posix()
        rows.append(
            f'<div class="audio-row" data-name="{html.escape(rel)}">'
            f'<div class="name">{html.escape(p.name)}</div>'
            f'<audio controls preload="none" src="{html.escape(rel)}"></audio>'
            f'</div>'
        )
    return (
        f'<details open class="section"><summary>{html.escape(group)} '
        f'<span style="color:var(--muted);font-weight:400">({len(paths)})</span>'
        f'</summary><div class="body">{"".join(rows)}</div></details>'
    )


def render_video_section(group: str, paths: list[Path], root: Path) -> str:
    paths.sort()
    rows: list[str] = []
    for p in paths:
        rel = p.relative_to(root).as_posix()
        rows.append(
            f'<div class="audio-row" data-name="{html.escape(rel)}">'
            f'<div class="name">{html.escape(p.name)}</div>'
            f'<a href="{html.escape(rel)}">open</a>'
            f'</div>'
        )
    return (
        f'<details open class="section"><summary>{html.escape(group)} '
        f'<span style="color:var(--muted);font-weight:400">({len(paths)})</span>'
        f'</summary><div class="body">{"".join(rows)}</div></details>'
    )


def build_html(root: Path) -> str:
    groups = find_assets(root)
    img_html = "".join(
        render_image_section(g, paths, root)
        for g, paths in sorted(groups["images"].items())
    ) or "<p>No PNGs extracted.</p>"
    aud_html = "".join(
        render_audio_section(g, paths, root)
        for g, paths in sorted(groups["audio"].items())
    ) or "<p>No audio extracted.</p>"
    vid_html = "".join(
        render_video_section(g, paths, root)
        for g, paths in sorted(groups["video"].items())
    ) or "<p>No video extracted.</p>"
    n_img = sum(len(v) for v in groups["images"].values())
    n_aud = sum(len(v) for v in groups["audio"].values())
    n_vid = sum(len(v) for v in groups["video"].values())
    counts = f"{n_img} images · {n_aud} audio · {n_vid} video"
    return PAGE.format(
        counts=html.escape(counts),
        images_html=img_html,
        audio_html=aud_html,
        video_html=vid_html,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="xanadu-viewer")
    p.add_argument(
        "out",
        nargs="?",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "out",
        help="extracted-assets directory (default: ./out)",
    )
    args = p.parse_args(argv)
    if not args.out.is_dir():
        p.error(f"not a directory: {args.out}")
    page = build_html(args.out)
    target = args.out / INDEX_NAME
    target.write_text(page, encoding="utf-8")
    print(f"wrote {target} ({len(page) // 1024} KB)")
    print(f"open: file://{target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
