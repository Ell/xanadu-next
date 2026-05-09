"""Shared layout primitives for the static viewer pages.

All generators (cli, viewer, scripts, debug) share the same header, nav, and
color palette so the site reads as one product instead of three loosely
linked pages.
"""

from __future__ import annotations

import html

# Palette: warm dark, gold accent — picks up the area-name golds inside the
# game's own UI art (see DATA/picture/picture/AREANAME*.png).
CSS = """
:root {
  --bg: #0f1014;
  --panel: #181a21;
  --panel-2: #1f222b;
  --border: #262a35;
  --fg: #e7e7ea;
  --muted: #8a8e9c;
  --accent: #c7a86b;
  --accent-soft: #f6e5b8;
  --link: #9bb6e0;
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: var(--bg); color: var(--fg);
              font: 13px/1.5 ui-sans-serif, system-ui,
              "Hiragino Sans", "Noto Sans CJK JP", sans-serif; }
a { color: var(--link); text-decoration: none; }
a:hover { color: var(--accent); }
code { font: 12px ui-monospace, monospace; background: #0c0d10;
       padding: 1px 6px; border-radius: 3px; color: var(--fg); }
b { font-weight: 600; }

.top { display: flex; align-items: center; gap: 18px; padding: 10px 18px;
       background: var(--panel); border-bottom: 1px solid var(--border);
       position: sticky; top: 0; z-index: 50; }
.top h1 { margin: 0; font-size: 14px; font-weight: 600;
          letter-spacing: 0.02em; }
.top h1 a { color: var(--fg); }
.top h1 a:hover { color: var(--accent); }
.top nav { display: flex; gap: 4px; flex-wrap: wrap; }
.top nav a { color: var(--muted); padding: 4px 10px; border-radius: 4px;
             font-size: 12px; }
.top nav a:hover { color: var(--fg); background: var(--panel-2); }
.top nav a.active { color: var(--accent); background: var(--panel-2); }
.top .spacer { flex: 1; }
.top .meta { color: var(--muted); font-size: 11px; }

main { padding: 22px; max-width: 1200px; margin: 0 auto; }
h2 { font-size: 13px; text-transform: uppercase; letter-spacing: 0.06em;
     color: var(--accent); margin: 28px 0 8px; font-weight: 600; }
h2 .count { color: var(--muted); font-weight: 400; }
.lede { color: var(--muted); margin: 0 0 12px; max-width: 80ch; }
.panel { background: var(--panel); border: 1px solid var(--border);
         border-radius: 4px; padding: 14px 16px; margin-bottom: 14px; }
"""

NAV_PAGES = [
    ("index.html", "Assets"),
    ("monsters.html", "Bestiary"),
    ("areas.html", "Areas"),
    ("debug.html", "Debug"),
]


def render_top(active: str, *, meta: str = "") -> str:
    """Render the top nav bar; `active` is the basename of the current page."""
    items = []
    for href, label in NAV_PAGES:
        cls = "active" if href == active else ""
        items.append(f'<a href="{href}" class="{cls}">{html.escape(label)}</a>')
    meta_html = (
        f'<span class="meta">{meta}</span>' if meta else ""
    )
    return (
        '<div class="top">'
        '<h1><a href="index.html">Xanadu Next</a></h1>'
        f'<nav>{"".join(items)}</nav>'
        '<div class="spacer"></div>'
        f'{meta_html}'
        '</div>'
    )


def page(*, title: str, active: str, body: str, extra_css: str = "",
         extra_js: str = "", meta: str = "") -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<style>
{CSS}
{extra_css}
</style>
</head>
<body>
{render_top(active, meta=meta)}
<main>
{body}
</main>
{f'<script>{extra_js}</script>' if extra_js else ''}
</body>
</html>
"""
