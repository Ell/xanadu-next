"""Generate monsters.html — full bestiary with stats, drops and area cross-refs.

Sources:
- DATA/chr/Object.tbl                 stats + EN names + drop tables
- DATA/chr/monster/M_xxxx/M_xxxx.alg  per-monster JP name + AI behaviour notes
- DATA/chr/monster/M_xxxx/M_xxxx.png  sprite (extracted from G32)
- DATA/Map/areaXX/areaXX.inf          area names + monster spawn slots

Page layout:
- Sidebar: searchable list of every monster (sprite thumbnail + EN/JP names).
- Detail pane: large sprite, full stats, drop table, area appearances,
  AI summary translated.
"""

from __future__ import annotations

import argparse
import html
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from . import _layout
from .objects import (
    EquipRecord,
    ObjRecord,
    index_by_id,
    lookup_drop_object,
    normalize_drops,
    parse_drop_table,
    parse_equip_tbl,
    parse_object_tbl,
    special_drop_label,
)


_KIND_LABELS = {
    "SL1": "1H Sword",
    "SL2": "2H Sword",
    "AX1": "1H Axe",
    "AX2": "2H Axe",
    "HMR": "Hammer",
    "THR": "Throwing",
    "SHT": "Bow / Shot",
    "ARM": "Armor",
    "HLM": "Helmet",
    "SHD": "Shield",
    "BTS": "Boots",
    "GLB": "Gloves",
    "ACS": "Accessory",
    "MAG": "Spell",
    "ITM": "Item",
}


@dataclass
class Monster:
    rec: ObjRecord
    jp: str = ""
    ai_summary: str = ""
    sprite_rel: str = ""
    families: list[str] = field(default_factory=list)
    sprites: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Data assembly

def _read_alg(path: Path) -> tuple[str, str]:
    """Return (jp_name, ai_summary) parsed from an .alg file's header comments."""
    if not path.exists():
        return "", ""
    raw = path.read_bytes().decode("cp932", errors="replace")
    jp = ""
    notes: list[str] = []
    for line in raw.splitlines()[:30]:
        line = line.strip()
        if not line.startswith("//"):
            continue
        body = line.lstrip("/").strip()
        m = re.search(r'(?:M_\w+\s*[-－])?\s*[「"]([^」"]+)[」"]', body)
        if m and not jp:
            jp = m.group(1)
            continue
        if body.startswith("->") or body.startswith("→"):
            notes.append(body.lstrip("->→").strip())
        elif body.startswith(("ATK", "ATTACK")):
            notes.append(body)
    return jp, "\n".join(notes)


def _build_monsters(out_root: Path, records: list[ObjRecord]) -> list[Monster]:
    """Object.tbl ships duplicate M_xxxx rows for level-scaled variants — we
    keep one row per id, choosing the highest-Lv variant (the area-scaled
    boss-tier one) and stash the lower-Lv variant Lvs for display."""
    monster_root = out_root / "DATA" / "chr" / "monster"
    by_id: dict[str, Monster] = {}
    variants: dict[str, list[ObjRecord]] = defaultdict(list)
    for rec in records:
        if not rec.id.startswith("M_"):
            continue
        variants[rec.id].append(rec)
    for mid, recs in variants.items():
        recs.sort(key=lambda r: r.lv)
        rec = recs[-1]  # highest Lv
        folder = monster_root / rec.id
        # Some monsters have variant textures (M_xxxxa.png, M_xxxxb.png) and
        # no canonical M_xxxx.png — surface every PNG so the bestiary shows
        # them all, with the canonical one (if any) listed first.
        # Catch any PNG in the folder (e.g. M_xxxxa.png variants, or oddly
        # named ones like core.png) — Falcom isn't consistent.
        all_pngs = sorted(folder.glob("*.png")) if folder.is_dir() else []
        canonical = folder / f"{rec.id}.png"
        if canonical in all_pngs:
            all_pngs.remove(canonical)
            all_pngs.insert(0, canonical)
        sprites = [
            f"DATA/chr/monster/{rec.id}/{p.name}" for p in all_pngs
        ]
        alg = folder / f"{rec.id}.alg"
        jp, ai = _read_alg(alg)
        m = Monster(
            rec=rec,
            jp=jp,
            ai_summary=ai,
            sprite_rel=sprites[0] if sprites else "",
            sprites=sprites,
        )
        m.families = [f"Lv{r.lv}/HP{r.hp}/ATK{r.atk}" for r in recs]
        by_id[mid] = m
    return list(by_id.values())


def _build_area_index(out_root: Path) -> dict[str, list[str]]:
    """Map: area_id -> [list of JP monster names declared in that area's .inf]"""
    by_area: dict[str, list[str]] = {}
    for inf in sorted((out_root / "DATA" / "Map").glob("area*/area*.inf")):
        area = inf.parent.name
        text = inf.read_bytes().decode("cp932", errors="replace")
        names: list[str] = []
        for line in text.splitlines():
            m = re.match(r"\s*M[1-8]\s+\d+\s*//\s*(.+?)\s*$", line)
            if m:
                names.append(m.group(1).strip())
        if names:
            by_area[area] = names
    return by_area


def _build_area_blocks(out_root: Path) -> list[dict]:
    """Map: area metadata — area_id, EN name, blocks list."""
    out: list[dict] = []
    for inf in sorted((out_root / "DATA" / "Map").glob("area*/area*.inf")):
        area = inf.parent.name
        text = inf.read_bytes().decode("cp932", errors="replace")
        blocks: list[str] = []
        for line in text.splitlines():
            m = re.match(r'\s*BLOCK\("([^"]+)"', line)
            if m and m.group(1) not in blocks:
                blocks.append(m.group(1))
        # also count drops + monsters in spawn table
        drop_count = len(re.findall(r"\bDROP\(", text))
        spawn_count = len(re.findall(r"^\s*M[1-8]\s+\d+", text, re.M))
        out.append(
            {
                "id": area,
                "blocks": blocks,
                "drop_count": drop_count,
                "spawn_count": spawn_count,
            }
        )
    return out


# ---------------------------------------------------------------------------
# Per-monster detail rendering

def _render_drops(rec: ObjRecord, equips: list[EquipRecord]) -> str:
    drops = parse_drop_table(rec.drops)
    if not drops:
        return '<div class="empty">— no recorded drop table —</div>'
    norm = normalize_drops(drops)
    rows = []
    for (did, w), (_, pct) in zip(drops, norm):
        sub = ""
        kind_pill = ""
        if did < 0:
            label = special_drop_label(did)
            cls = "drop-tier"
        elif 0 <= did < len(equips):
            it = equips[did]
            label = it.en or it.id or f"item #{did:03d}"
            kind = _KIND_LABELS.get(it.kind, it.kind)
            if kind:
                kind_pill = f'<span class="d-kind">{html.escape(kind)}</span>'
            if it.desc and it.desc != label and "？" not in it.desc:
                sub = it.desc
            cls = "drop-item"
        else:
            label = f"item #{did:03d} (out of range)"
            cls = "drop-item"
        bar_w = max(3, min(100, int(pct)))
        sub_html = f'<div class="d-sub">{html.escape(sub)}</div>' if sub else ""
        rows.append(
            f'<tr class="{cls}">'
            f'<td class="d-bar"><div style="width:{bar_w}%"></div></td>'
            f'<td class="d-pct">{pct:.1f}%</td>'
            f'<td class="d-lbl"><div class="d-name">'
            f'{kind_pill}{html.escape(label)}'
            f'<span class="d-id">#{did:+04d}</span></div>'
            f"{sub_html}</td>"
            f"</tr>"
        )
    return f'<table class="drops"><tbody>{"".join(rows)}</tbody></table>'


def _render_one(m: Monster, equips: list[EquipRecord], areas_for: dict[str, list[str]]) -> str:
    rec = m.rec
    if m.sprites:
        if len(m.sprites) == 1:
            sprite = (
                f'<img src="{html.escape(m.sprites[0])}" '
                f'alt="{html.escape(rec.id)}" />'
            )
        else:
            sprite = (
                '<div class="m-sprite-strip">'
                + "".join(
                    f'<img src="{html.escape(s)}" '
                    f'alt="{html.escape(rec.id)} variant" '
                    f'title="{html.escape(s.rsplit("/", 1)[-1])}" />'
                    for s in m.sprites
                )
                + "</div>"
            )
    else:
        sprite = (
            '<div class="no-sprite">texture-only<br>(check .chr)</div>'
        )
    stat = lambda k, v: f'<div class="stat"><span class="k">{k}</span><span class="v">{v}</span></div>'
    stats_grid = "".join(
        [
            stat("Lv", rec.lv or "—"),
            stat("HP", rec.hp or "—"),
            stat("MP", rec.mp or "—") if rec.mp else "",
            stat("ATK", rec.atk or "—"),
            stat("DEF", rec.df or "—"),
            stat("XP", rec.xp or "—"),
            stat("Gold", rec.gold or "—"),
        ]
    )
    drops_html = _render_drops(rec, equips)
    areas = sorted(a for a, names in areas_for.items() if rec.jp_name in names) if False else []
    # match by JP name to area inf
    if m.jp:
        areas = sorted(a for a, names in areas_for.items() if m.jp in names)
    area_html = (
        '<div class="areas">'
        + " ".join(
            f'<a href="areas.html#{a}" class="area-pill">{a}</a>' for a in areas
        )
        + "</div>"
        if areas
        else '<div class="empty">— no area cross-reference recovered —</div>'
    )
    ai_html = (
        f'<pre class="ai">{html.escape(m.ai_summary)}</pre>'
        if m.ai_summary
        else '<div class="empty">— no AI commentary in alg —</div>'
    )
    variants_html = ""
    if len(m.families) > 1:
        pills = " ".join(
            f'<span class="vary">{html.escape(v)}</span>' for v in m.families
        )
        variants_html = f'<div class="m-variants">variants: {pills}</div>'
    title_jp = (
        f'<span class="t-jp">{html.escape(m.jp)}</span>' if m.jp else ""
    )
    return f"""
<section class="m-detail" id="m-{rec.id}" data-id="{rec.id}">
  <div class="m-head">
    <div class="m-sprite">{sprite}</div>
    <div class="m-title">
      <div class="m-id">{html.escape(rec.id)}</div>
      <h2 class="m-name">{html.escape(rec.en or rec.id)} {title_jp}</h2>
      <div class="m-stats">{stats_grid}</div>
      {variants_html}
    </div>
  </div>
  <div class="m-body">
    <div class="m-block">
      <h3>Drop table</h3>
      {drops_html}
    </div>
    <div class="m-block">
      <h3>Appears in</h3>
      {area_html}
    </div>
    <div class="m-block">
      <h3>AI / behaviour</h3>
      {ai_html}
    </div>
  </div>
</section>
""".strip()


# ---------------------------------------------------------------------------
# CSS / JS extra for this page

EXTRA_CSS = """
.layout { display: grid; grid-template-columns: 280px 1fr; gap: 16px;
          align-items: start; }
.sidebar { position: sticky; top: 56px; max-height: calc(100vh - 80px);
           overflow: auto; background: var(--panel); border: 1px solid var(--border);
           border-radius: 4px; padding: 8px; }
.sidebar input { width: 100%; background: var(--bg); color: var(--fg);
                 border: 1px solid var(--border); border-radius: 4px;
                 padding: 6px 8px; font: inherit; margin-bottom: 8px; }
.s-list { display: flex; flex-direction: column; gap: 2px; }
.s-list a { display: flex; gap: 8px; align-items: center;
            padding: 4px 6px; border-radius: 3px; color: var(--fg); }
.s-list a:hover, .s-list a.active { background: var(--panel-2);
                                     color: var(--accent); }
.s-list img { width: 28px; height: 28px; object-fit: contain;
              background: #0c0d10; image-rendering: pixelated;
              border-radius: 2px; flex-shrink: 0; }
.s-list .s-meta { display: flex; flex-direction: column;
                  font-size: 11px; line-height: 1.2; min-width: 0; }
.s-list .s-name { color: inherit; white-space: nowrap; overflow: hidden;
                  text-overflow: ellipsis; }
.s-list .s-id { color: var(--muted); font-size: 10px; }

.bestiary { display: flex; flex-direction: column; gap: 22px; }
.m-detail { background: var(--panel); border: 1px solid var(--border);
            border-radius: 4px; padding: 14px 16px; }
.m-head { display: grid; grid-template-columns: auto 1fr; gap: 16px;
          align-items: center; }
.m-sprite { width: 120px; min-height: 96px; background: #0c0d10; border-radius: 3px;
            display: flex; align-items: center; justify-content: center;
            overflow: hidden; padding: 4px; }
.m-sprite img { max-width: 100%; max-height: 96px;
                image-rendering: pixelated; object-fit: contain; }
.m-sprite .no-sprite { color: var(--muted); font-size: 10px;
                       text-align: center; line-height: 1.4;
                       font-style: italic; }
.m-sprite-strip { display: flex; gap: 4px; overflow-x: auto;
                  width: 100%; height: 96px; }
.m-sprite-strip img { flex: 0 0 auto; height: 96px; max-width: 96px;
                      object-fit: contain; image-rendering: pixelated; }
.m-id { color: var(--muted); font: 11px ui-monospace, monospace; }
.m-name { margin: 2px 0 6px; font-size: 16px; font-weight: 600; }
.m-name .t-jp { color: var(--accent-soft); font-weight: 400;
                font-size: 14px; margin-left: 8px; }
.m-stats { display: flex; gap: 14px; flex-wrap: wrap; }
.m-stats .stat { display: flex; gap: 4px; align-items: baseline;
                 font: 12px ui-monospace, monospace; }
.m-stats .k { color: var(--muted); text-transform: uppercase;
              letter-spacing: 0.05em; font-size: 10px; }
.m-stats .v { color: var(--accent); font-weight: 600; }
.m-variants { margin-top: 6px; font: 11px ui-monospace, monospace;
              color: var(--muted); }
.m-variants .vary { color: var(--accent-soft); margin-right: 8px; }

.m-body { display: grid; grid-template-columns: 1.4fr 1fr;
          gap: 14px; margin-top: 14px; }
.m-block { background: var(--panel-2); border: 1px solid var(--border);
           border-radius: 3px; padding: 10px 12px; min-width: 0; }
.m-block h3 { margin: 0 0 8px; font-size: 11px; text-transform: uppercase;
              letter-spacing: 0.06em; color: var(--accent);
              font-weight: 600; }
.m-block .empty { color: var(--muted); font-size: 11px;
                  font-style: italic; }
.m-block:nth-of-type(3) { grid-column: 1 / -1; }

table.drops { border-collapse: collapse; width: 100%;
              font-size: 13px; }
.drops td { padding: 6px 8px; border-bottom: 1px solid var(--border);
            vertical-align: middle; }
.drops tr:last-child td { border-bottom: 0; }
.drops .d-bar { width: 90px; padding-right: 4px; }
.drops .d-bar div { background: var(--accent); height: 6px;
                    border-radius: 1px; opacity: 0.55; }
.drops .d-pct { color: var(--accent); font: 12px ui-monospace, monospace;
                font-weight: 600; width: 56px; text-align: right; }
.drops .d-lbl { color: var(--fg); padding-left: 12px; line-height: 1.35; }
.drops .d-name { font-size: 13px; color: var(--fg); }
.drops .d-id { color: var(--muted); font: 10px ui-monospace, monospace;
               margin-left: 8px; }
.drops .d-kind { display: inline-block; padding: 1px 6px; margin-right: 8px;
                 background: var(--bg); border: 1px solid var(--border);
                 border-radius: 2px; font: 10px ui-monospace, monospace;
                 color: var(--muted); text-transform: uppercase;
                 letter-spacing: 0.04em; }
.drops .d-sub { font-size: 11px; color: var(--muted);
                font-family: "Hiragino Sans", "Noto Sans CJK JP", sans-serif;
                margin-top: 2px; }
.drops .drop-tier .d-name { color: var(--accent-soft); font-style: italic; }
.drops .drop-tier .d-id { color: var(--accent); }

.areas { display: flex; gap: 6px; flex-wrap: wrap; }
.area-pill { padding: 3px 9px; background: var(--bg);
             border: 1px solid var(--border); border-radius: 3px;
             font: 11px ui-monospace, monospace; color: var(--fg); }
.area-pill:hover { color: var(--accent); border-color: var(--accent); }

pre.ai { margin: 0; white-space: pre-wrap; font: 11px/1.55 ui-monospace, monospace;
         color: var(--fg); }
"""

EXTRA_JS = """
const rows = document.querySelectorAll('.bestiary .m-detail');
const links = document.querySelectorAll('.s-list a');
const search = document.getElementById('search');
function filter() {
  const q = search.value.toLowerCase().trim();
  let shown = 0;
  rows.forEach(r => {
    const txt = r.textContent.toLowerCase();
    const ok = !q || txt.includes(q);
    r.style.display = ok ? '' : 'none';
    if (ok) shown++;
  });
  links.forEach(a => {
    const href = a.getAttribute('href').slice(1);
    const r = document.getElementById(href);
    a.style.display = r && r.style.display !== 'none' ? '' : 'none';
  });
  document.getElementById('count').textContent = shown;
}
search?.addEventListener('input', filter);
const obs = new IntersectionObserver(entries => {
  entries.forEach(e => {
    if (e.isIntersecting) {
      const id = e.target.id;
      links.forEach(a => a.classList.toggle('active', a.getAttribute('href') === '#' + id));
    }
  });
}, { rootMargin: '-30% 0px -60% 0px' });
rows.forEach(r => obs.observe(r));
"""


# ---------------------------------------------------------------------------
# Page generation

def render_monsters_page(out_root: Path) -> str:
    obj_path = out_root / "DATA" / "chr" / "Object.tbl"
    equip_path = out_root / "DATA" / "equip" / "equip" / "EQUIP.tbl"
    records = parse_object_tbl(obj_path)
    equips = parse_equip_tbl(equip_path)
    by_id = index_by_id(records)
    monsters = _build_monsters(out_root, records)
    monsters.sort(key=lambda m: m.rec.id)
    areas_for = _build_area_index(out_root)

    # sidebar
    s_items = []
    for m in monsters:
        thumb = (
            f'<img src="{html.escape(m.sprite_rel)}" alt="" loading="lazy" />'
            if m.sprite_rel
            else '<div style="width:28px;height:28px;background:#0c0d10;border-radius:2px"></div>'
        )
        s_items.append(
            f'<a href="#m-{m.rec.id}">{thumb}'
            f'<span class="s-meta">'
            f'<span class="s-name">{html.escape(m.rec.en or m.rec.id)}</span>'
            f'<span class="s-id">{html.escape(m.rec.id)} '
            f'· Lv{m.rec.lv}</span>'
            f"</span></a>"
        )

    bestiary = "\n".join(_render_one(m, equips, areas_for) for m in monsters)
    body = f"""
<div class="layout">
  <aside class="sidebar">
    <input id="search" placeholder="filter by name, id, drop, area..." autofocus>
    <div class="s-list">{"".join(s_items)}</div>
  </aside>
  <div class="bestiary">
    <p class="lede">Every monster pulled from <code>DATA/chr/Object.tbl</code> (1108-byte
    records). Stats decoded from the binary (Lv/HP/MP/ATK/DEF/XP/Gold high
    16 bits of consecutive uint32 fields). Drop ids are resolved against the
    same table — positive ids reference world props that act as pickups,
    negative ids reference engine-internal gold/exp pools whose magnitude
    scales with the monster's level. JP names &amp; AI summaries pulled from
    each <code>M_xxxx.alg</code> file.</p>
    {bestiary}
  </div>
</div>
""".strip()
    meta = f'<span id="count">{len(monsters)}</span>&nbsp;monsters'
    return _layout.page(
        title="Xanadu Next — Bestiary",
        active="monsters.html",
        body=body,
        extra_css=EXTRA_CSS,
        extra_js=EXTRA_JS,
        meta=meta,
    )


def render_areas_page(out_root: Path) -> str:
    areas = _build_area_blocks(out_root)
    rows = []
    for a in areas:
        blocks = ", ".join(html.escape(b) for b in a["blocks"]) or "(no blocks)"
        rows.append(
            f'<tr id="{a["id"]}"><td><code>{a["id"]}</code></td>'
            f'<td>{blocks}</td>'
            f'<td>{a["spawn_count"]}</td>'
            f'<td>{a["drop_count"]}</td></tr>'
        )
    body = f"""
<p class="lede">17 area definitions from <code>DATA/Map/area*/area*.inf</code>.
Each one declares one or more named <em>blocks</em> (the English names that
appear in-game, like &ldquo;Floodgate&rdquo; or &ldquo;Eternal Maze&rdquo;), a list of
monster slots that the area's encounter system can roll, and DROP() entries
for breakable scenery. Monster pages cross-link in here.</p>
<div class="panel">
<table style="width:100%; font: 12px ui-monospace, monospace; border-collapse: collapse;">
<thead><tr><th style="text-align:left">area</th><th style="text-align:left">blocks (in-game names)</th>
<th>spawn slots</th><th>DROP() entries</th></tr></thead>
<tbody>{"".join(rows)}</tbody>
</table>
</div>
""".strip()
    return _layout.page(
        title="Xanadu Next — Areas",
        active="areas.html",
        body=body,
        meta=f"{len(areas)} areas",
    )


# ---------------------------------------------------------------------------
# CLI

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="xanadu-monsters")
    p.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "out",
        help="output directory holding the extracted DATA/ tree",
    )
    args = p.parse_args(argv)
    out: Path = args.out
    if not (out / "DATA" / "chr" / "Object.tbl").exists():
        p.error(f"Object.tbl missing under {out}; run xanadu-extract first")

    monsters_html = out / "monsters.html"
    monsters_html.write_text(render_monsters_page(out), encoding="utf-8")
    print(f"wrote {monsters_html}")
    areas_html = out / "areas.html"
    areas_html.write_text(render_areas_page(out), encoding="utf-8")
    print(f"wrote {areas_html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
