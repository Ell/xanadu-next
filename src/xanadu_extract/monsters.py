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
    """Per-area metadata for the area page.

    Pulls from each ``area*.inf``:
      - the named BLOCK declarations with their tile-id ranges
        ``BLOCK("Floodgate", (86,88), "MP_00_A", 0, ...)`` → tiles 0x86–0x88
      - the M1-M8 spawn slots (numeric id + JP name in trailing comment)
      - DROP() count (breakable-scenery loot, bookkeeping only)
    """
    out: list[dict] = []
    for inf in sorted((out_root / "DATA" / "Map").glob("area*/area*.inf")):
        area = inf.parent.name
        text = inf.read_bytes().decode("cp932", errors="replace")
        blocks: list[dict] = []
        seen_block_keys: set[tuple[str, str, str]] = set()
        for line in text.splitlines():
            m = re.match(
                r'\s*BLOCK\(\s*"([^"]+)"\s*,\s*\(([0-9a-fA-F]+)\s*,\s*([0-9a-fA-F]+)\)',
                line,
            )
            if not m:
                continue
            name, lo, hi = m.group(1), m.group(2), m.group(3)
            key = (name, lo, hi)
            if key in seen_block_keys:
                continue
            seen_block_keys.add(key)
            blocks.append(
                {"name": name, "lo": int(lo, 16), "hi": int(hi, 16)}
            )
        spawns: list[dict] = []
        for line in text.splitlines():
            m = re.match(r"\s*(M[1-8])\s+(\d+)\s*//\s*(.+?)\s*$", line)
            if m:
                spawns.append(
                    {
                        "slot": m.group(1),
                        "id": int(m.group(2)),
                        "jp": m.group(3).strip(),
                    }
                )
        drop_count = len(re.findall(r"\bDROP\(", text))
        out.append(
            {
                "id": area,
                "blocks": blocks,
                "spawns": spawns,
                "drop_count": drop_count,
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


def _render_one(
    m: Monster,
    equips: list[EquipRecord],
    areas_for: dict[str, list[str]],
    spawns_in: dict[str, list[tuple[str, int]]] | None = None,
) -> str:
    rec = m.rec
    # Prefer the 3D model if we have a glb for this monster, fall back to
    # texture sprite(s) otherwise.
    glb_rel = f"models/{rec.id}.glb"
    has_glb = (Path(__file__).resolve().parents[2] / "out" / glb_rel).exists()
    if has_glb:
        # Google's <model-viewer> web component (loaded once at the top
        # of the page).  No poster img — the texture sheet shows through
        # if the canvas isn't ready, which looks worse than a black box.
        sprite = (
            f'<model-viewer src="{glb_rel}" alt="{html.escape(rec.id)}" '
            f'camera-controls auto-rotate auto-rotate-delay="1500" '
            f'rotation-per-second="20deg" '
            f'shadow-intensity="0.6" exposure="1.0" '
            f'loading="lazy" reveal="auto" '
            f'style="width:100%;height:100%;background:#0c0d10">'
            f"</model-viewer>"
        )
    elif m.sprites:
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

    # Areas pulled from real PUT_MONSTER spawn data; fall back to area .inf
    # comment matching when no static spawn was found (a few monsters are
    # only declared via the encounter-table M1-M8 slots).
    spawns_in = spawns_in or {}
    if spawns_in:
        area_blocks = []
        for area in sorted(spawns_in):
            map_pills = " ".join(
                f'<a href="areas.html#{area}" class="map-pill" '
                f'title="{count} spawn{"s" if count > 1 else ""}">'
                f"{html.escape(map_id)}</a>"
                for map_id, count in sorted(spawns_in[area])
            )
            area_blocks.append(
                f'<div class="area-grp">'
                f'<a href="areas.html#{area}" class="area-pill">{area}</a>'
                f'<div class="map-pills">{map_pills}</div>'
                f"</div>"
            )
        area_html = '<div class="areas-list">' + "".join(area_blocks) + "</div>"
    elif m.jp:
        areas = sorted(a for a, names in areas_for.items() if m.jp in names)
        if areas:
            area_html = (
                '<div class="areas">'
                + " ".join(
                    f'<a href="areas.html#{a}" class="area-pill">{a}</a>'
                    for a in areas
                )
                + "</div>"
            )
        else:
            area_html = (
                '<div class="empty">— no static spawn / encounter slot —</div>'
            )
    else:
        area_html = '<div class="empty">— no static spawn / encounter slot —</div>'
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
.m-sprite { width: 200px; height: 200px; background: #0c0d10; border-radius: 3px;
            display: flex; align-items: center; justify-content: center;
            overflow: hidden; padding: 0; }
.m-sprite model-viewer { width: 100%; height: 100%; }
.m-sprite img { max-width: 100%; max-height: 192px;
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

.areas, .areas-list { display: flex; flex-direction: column; gap: 8px; }
.area-grp { display: flex; gap: 8px; align-items: flex-start; }
.area-pill { padding: 3px 9px; background: var(--bg);
             border: 1px solid var(--border); border-radius: 3px;
             font: 11px ui-monospace, monospace; color: var(--fg);
             flex-shrink: 0; }
.area-pill:hover { color: var(--accent); border-color: var(--accent); }
.map-pills { display: flex; flex-wrap: wrap; gap: 3px; }
.map-pill { padding: 1px 6px; background: var(--panel-2);
            border: 1px solid var(--border); border-radius: 2px;
            font: 10px ui-monospace, monospace; color: var(--muted); }
.map-pill:hover { color: var(--accent); border-color: var(--accent); }

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
    # Drop monsters with no recorded drop table — these are mostly cinematic
    # bosses, body parts (Scoltula's Foot), and placeholder rows that don't
    # function as combat encounters and would just be padding in the page.
    monsters = [m for m in monsters if parse_drop_table(m.rec.drops)]
    monsters.sort(key=lambda m: m.rec.id)
    areas_for = _build_area_index(out_root)

    # Cross-reference: where does each monster id actually spawn in scp?
    # Builds {M_xxxx: {area: [(map_id, count), ...]}}
    spawn_data = _parse_map_spawns(out_root)
    spawns_for: dict[str, dict[str, list[tuple[str, int]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for area, by_map in spawn_data.items():
        for map_id, spawns in by_map.items():
            agg: dict[int, int] = defaultdict(int)
            for sp in spawns:
                agg[sp["id"]] += 1
            for spid, count in agg.items():
                if 0 <= spid < len(records):
                    row = records[spid]
                    if row.id.startswith("M_"):
                        spawns_for[row.id][area].append((map_id, count))

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

    bestiary = "\n".join(
        _render_one(m, equips, areas_for, spawns_for.get(m.rec.id, {}))
        for m in monsters
    )
    body = f"""
<script type="module" src="https://ajax.googleapis.com/ajax/libs/model-viewer/3.5.0/model-viewer.min.js"></script>
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


_AREAS_EXTRA_CSS = """
.area { background: var(--panel); border: 1px solid var(--border);
        border-radius: 4px; padding: 16px 18px; margin-bottom: 22px; }
.area h2 { margin: 0 0 4px; font-size: 16px; color: var(--accent);
           font-weight: 600; text-transform: none; letter-spacing: 0; }
.area h2 .id { color: var(--muted); font-size: 12px;
               font-family: ui-monospace, monospace; margin-left: 10px;
               font-weight: 400; text-transform: uppercase; letter-spacing: 0.04em; }
.area .a-blocks { display: flex; flex-wrap: wrap; gap: 6px; margin: 10px 0; }
.area .a-block { background: var(--panel-2); border: 1px solid var(--border);
                 border-radius: 3px; padding: 4px 9px; font-size: 12px;
                 color: var(--fg); display: inline-flex; align-items: center;
                 gap: 6px; }
.area .a-block .range { color: var(--muted); font-size: 10px;
                         font-family: ui-monospace, monospace; }
.area .a-map { background: var(--panel-2); border: 1px solid var(--border);
               border-radius: 3px; padding: 10px 12px; margin: 10px 0; }
.area .a-map-id { font: 12px ui-monospace, monospace; color: var(--accent);
                  margin-bottom: 8px; font-weight: 600; }
.area .a-map-id .a-map-meta { color: var(--muted); font-weight: 400;
                              margin-left: 10px; font-size: 11px;
                              text-transform: uppercase;
                              letter-spacing: 0.04em; }
.area .a-spawns { display: grid; gap: 6px;
                  grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); }
.area .a-mob { display: flex; gap: 8px; align-items: center;
               background: var(--panel-2); border: 1px solid var(--border);
               border-radius: 3px; padding: 6px 8px;
               text-decoration: none; color: var(--fg); }
.area .a-mob:hover { border-color: var(--accent); color: var(--accent); }
.area .a-mob img { width: 36px; height: 36px; object-fit: contain;
                   image-rendering: pixelated; background: #0c0d10;
                   border-radius: 2px; flex-shrink: 0; }
.area .a-mob .a-meta { font-size: 12px; line-height: 1.25; min-width: 0; }
.area .a-mob .a-name { white-space: nowrap; overflow: hidden;
                       text-overflow: ellipsis; }
.area .a-mob .a-id { color: var(--muted); font: 10px ui-monospace, monospace; }
.area .a-tiles { display: flex; gap: 3px; flex-wrap: wrap;
                 margin-top: 6px; }
.area .a-tiles img { width: 64px; height: 64px; object-fit: cover;
                     image-rendering: pixelated; border-radius: 2px;
                     background: #0c0d10; cursor: pointer; }
.area .a-tiles .more { color: var(--muted); font: 10px ui-monospace, monospace;
                       align-self: center; padding-left: 6px; }
.area details { margin-top: 12px; }
.area details > summary { cursor: pointer; font-size: 11px;
                          color: var(--muted); padding: 4px 0;
                          text-transform: uppercase; letter-spacing: 0.04em; }
.area details > summary:hover { color: var(--accent); }
"""


def _resolve_spawn_to_monster(
    spawns: list[dict], monsters_by_jp: dict[str, "Monster"]
) -> list[dict]:
    out = []
    for sp in spawns:
        m = monsters_by_jp.get(sp["jp"])
        out.append(
            {
                **sp,
                "folder": m.rec.id if m else "",
                "en": m.rec.en if m else "",
                "sprite": m.sprite_rel if m else "",
                "lv": m.rec.lv if m else 0,
            }
        )
    return out


_PUT_MONSTER_RE = re.compile(
    r'\bPUT_MONSTER\s*\(\s*"([^"]+)"\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)',
    re.IGNORECASE,
)


def _parse_map_spawns(out_root: Path) -> dict[str, dict[str, list[dict]]]:
    """Walk every MP_*.scp and pull PUT_MONSTER static-spawn declarations.

    Returns: {area: {map_id: [{slot, id, lv, ...}, ...]}}.
    """
    by_area: dict[str, dict[str, list[dict]]] = defaultdict(dict)
    for scp in sorted((out_root / "DATA" / "Map").glob("area*/MP_*.scp")):
        area = scp.parent.name
        map_id = scp.stem
        text = scp.read_bytes().decode("cp932", errors="replace")
        spawns: list[dict] = []
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("//"):
                continue
            m = _PUT_MONSTER_RE.search(s)
            if not m:
                continue
            slot, mid, lv, a, b, idx = m.groups()
            spawns.append(
                {
                    "slot": slot,
                    "id": int(mid),
                    "lv": int(lv),
                    "_a": int(a),
                    "_b": int(b),
                    "idx": int(idx),
                }
            )
        if spawns:
            by_area[area][map_id] = spawns
    return by_area


def render_areas_page(out_root: Path) -> str:
    obj_path = out_root / "DATA" / "chr" / "Object.tbl"
    records = parse_object_tbl(obj_path)
    # Spawn ids are direct row indices into Object.tbl (verified against
    # known correspondences from area*.inf comments — Goblin=0, Slime=4,
    # Bat=5, Skeleton=6, Lizardman=8, Red Slime=63, Black Slime=177, …).
    by_idx = records  # list, indexable by spawn id
    monsters = _build_monsters(out_root, records)
    monsters_by_jp = {m.jp: m for m in monsters if m.jp}
    monsters_by_id = {m.rec.id: m for m in monsters}
    areas = _build_area_blocks(out_root)
    map_root = out_root / "DATA" / "Map"
    spawn_data = _parse_map_spawns(out_root)

    sections = []
    for a in areas:
        # find tiles for each block (case-insensitive hex match)
        tile_dir = map_root / a["id"]
        all_tiles: dict[int, Path] = {}
        if tile_dir.is_dir():
            for p in tile_dir.glob(f"{a['id'].upper()}_*.png"):
                stem = p.stem.split("_", 1)[1]
                try:
                    all_tiles[int(stem, 16)] = p
                except ValueError:
                    pass

        block_html_parts = []
        for b in a["blocks"]:
            tiles = sorted(
                p for k, p in all_tiles.items() if b["lo"] <= k <= b["hi"]
            )
            tile_imgs = "".join(
                f'<img src="DATA/Map/{a["id"]}/{p.name}" '
                f'alt="{p.stem}" loading="lazy" '
                f'title="{p.name}" />'
                for p in tiles[:8]
            )
            more = (
                f'<span class="more">+{len(tiles) - 8}</span>'
                if len(tiles) > 8
                else ""
            )
            tile_strip = (
                f'<div class="a-tiles">{tile_imgs}{more}</div>'
                if tile_imgs
                else ""
            )
            block_html_parts.append(
                f'<div class="a-block">'
                f'<span>{html.escape(b["name"])}</span>'
                f'<span class="range">0x{b["lo"]:02x}–0x{b["hi"]:02x}</span>'
                f"</div>"
                + tile_strip
            )

        # ----- per-map static spawn lists (from PUT_MONSTER) -----
        maps = spawn_data.get(a["id"], {})
        map_sections: list[str] = []
        for map_id in sorted(maps):
            spawns = maps[map_id]
            # group by spawn id so we don't render the same monster
            # five times for a five-slot spawn block
            agg: dict[int, dict] = {}
            for sp in spawns:
                cur = agg.setdefault(
                    sp["id"], {"id": sp["id"], "count": 0, "lv": sp["lv"]}
                )
                cur["count"] += 1
                cur["lv"] = max(cur["lv"], sp["lv"])

            cards: list[str] = []
            for spid, info in sorted(
                agg.items(), key=lambda x: (-x[1]["count"], x[0])
            ):
                row = (
                    by_idx[info["id"]]
                    if 0 <= info["id"] < len(by_idx)
                    else None
                )
                if row and row.id.startswith("M_") and row.id in monsters_by_id:
                    m = monsters_by_id[row.id]
                    img = (
                        f'<img src="{html.escape(m.sprite_rel)}" alt="" loading="lazy">'
                        if m.sprite_rel
                        else '<div style="width:36px;height:36px;background:#0c0d10;border-radius:2px"></div>'
                    )
                    href = f"monsters.html#m-{row.id}"
                    name = row.en or row.id
                    extra = f"× {info['count']}" if info["count"] > 1 else ""
                    sub = f"{row.id} · Lv{info['lv']} {extra}".strip()
                    cards.append(
                        f'<a class="a-mob" href="{href}">'
                        f"{img}"
                        f'<div class="a-meta">'
                        f'<div class="a-name">{html.escape(name)}</div>'
                        f'<div class="a-id">{html.escape(sub)}</div>'
                        f"</div></a>"
                    )
                elif row:
                    label = row.en or row.id
                    extra = f"× {info['count']}" if info["count"] > 1 else ""
                    cards.append(
                        f'<div class="a-mob" style="opacity:0.55">'
                        f'<div style="width:36px;height:36px;background:#0c0d10;border-radius:2px"></div>'
                        f'<div class="a-meta">'
                        f'<div class="a-name">{html.escape(label)}</div>'
                        f'<div class="a-id">id #{info["id"]} · Lv{info["lv"]} {extra}</div>'
                        f"</div></div>"
                    )
                else:
                    cards.append(
                        f'<div class="a-mob" style="opacity:0.4">'
                        f'<div style="width:36px;height:36px;background:#0c0d10;border-radius:2px"></div>'
                        f'<div class="a-meta">'
                        f'<div class="a-name">unknown #{info["id"]}</div>'
                        f'<div class="a-id">Lv{info["lv"]}</div>'
                        f"</div></div>"
                    )

            map_sections.append(
                f'<div class="a-map">'
                f'<div class="a-map-id">{html.escape(map_id)} '
                f'<span class="a-map-meta">'
                f'{len(spawns)} spawns · {len(agg)} types</span></div>'
                f'<div class="a-spawns">{"".join(cards)}</div>'
                f"</div>"
            )

        if map_sections:
            spawns_html = (
                f'<div style="margin-top:18px;font-size:11px;color:var(--muted);'
                f'text-transform:uppercase;letter-spacing:0.04em">'
                f'maps &amp; static spawns ({len(maps)})</div>'
                + "".join(map_sections)
            )
        else:
            spawns_html = (
                '<div style="margin-top:14px;color:var(--muted);font-style:italic;'
                'font-size:11px">— no static PUT_MONSTER declarations in this area —</div>'
            )

        # all-tiles dropdown
        leftover = sorted(all_tiles.values(), key=lambda p: p.name)
        tiles_summary = (
            f'<details><summary>all {len(leftover)} tiles in {a["id"]}</summary>'
            f'<div class="a-tiles" style="max-height:400px;overflow:auto;margin-top:6px">'
            + "".join(
                f'<img src="DATA/Map/{a["id"]}/{p.name}" '
                f'alt="" loading="lazy" title="{p.name}">'
                for p in leftover
            )
            + "</div></details>"
            if leftover
            else ""
        )

        section = f"""
<section class="area" id="{a["id"]}">
  <h2>{html.escape(a["id"])}<span class="id">{a["drop_count"]} DROP() · {len(a["blocks"])} blocks · {len(a["spawns"])} spawns</span></h2>
  <div class="a-blocks">{"".join(block_html_parts)}</div>
  {spawns_html}
  {tiles_summary}
</section>
""".strip()
        sections.append(section)

    body = f"""
<p class="lede">17 area definitions from <code>DATA/Map/area*/area*.inf</code>.
Each area names its in-game regions (BLOCK declarations), the texture-tile
range each region uses, the M1-M8 monster slots its encounter system can
roll, and DROP() entries for breakable scenery. Monsters cross-link to the
bestiary; tile thumbnails are from the extracted G32 → PNG conversion.</p>
{"".join(sections)}
""".strip()
    return _layout.page(
        title="Xanadu Next — Areas",
        active="areas.html",
        body=body,
        extra_css=_AREAS_EXTRA_CSS,
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
