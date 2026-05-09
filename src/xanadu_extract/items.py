"""Generate items.html — every entry from EQUIP.tbl with icon + stats + flavor.

Sources:
- DATA/equip/equip/EQUIP.tbl   item registry (1024 records of 692 bytes)
- DATA/SYSTEM/system/ITEM.png  32x32-grid sprite atlas, 32x32 cells
                               (extracted to out/icons/NNNN.png at build)
"""

from __future__ import annotations

import argparse
import html
from collections import defaultdict
from pathlib import Path

from . import _layout
from .objects import EquipRecord, parse_equip_tbl

KIND_LABELS = {
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

EXTRA_CSS = """
.layout { display: grid; grid-template-columns: 280px 1fr; gap: 16px;
          align-items: start; }
.sidebar { position: sticky; top: 56px; max-height: calc(100vh - 80px);
           overflow: auto; background: var(--panel); border: 1px solid var(--border);
           border-radius: 4px; padding: 8px; }
.sidebar input { width: 100%; background: var(--bg); color: var(--fg);
                 border: 1px solid var(--border); border-radius: 4px;
                 padding: 6px 8px; font: inherit; margin-bottom: 8px; }
.kindfilter { display: flex; gap: 3px; flex-wrap: wrap; margin-bottom: 8px; }
.kindfilter a { font: 10px ui-monospace, monospace; padding: 3px 7px;
                background: var(--bg); border: 1px solid var(--border);
                border-radius: 3px; color: var(--muted);
                text-transform: uppercase; letter-spacing: 0.04em; }
.kindfilter a.active, .kindfilter a:hover { color: var(--accent);
                                             border-color: var(--accent); }
.s-list { display: flex; flex-direction: column; gap: 2px; }
.s-list a { display: flex; gap: 8px; align-items: center;
            padding: 4px 6px; border-radius: 3px; color: var(--fg); }
.s-list a:hover, .s-list a.active { background: var(--panel-2);
                                     color: var(--accent); }
.s-list .icon { width: 28px; height: 28px; flex-shrink: 0;
                background: #0c0d10; image-rendering: pixelated;
                border-radius: 2px; }
.s-list .icon img { width: 28px; height: 28px; image-rendering: pixelated; }
.s-list .s-meta { display: flex; flex-direction: column;
                  font-size: 11px; line-height: 1.2; min-width: 0; }
.s-list .s-name { color: inherit; white-space: nowrap; overflow: hidden;
                  text-overflow: ellipsis; }
.s-list .s-id { color: var(--muted); font-size: 10px;
                font-family: ui-monospace, monospace; }

.items { display: flex; flex-direction: column; gap: 18px; }
.it { background: var(--panel); border: 1px solid var(--border);
      border-radius: 4px; padding: 14px 16px; }
.it-head { display: grid; grid-template-columns: auto 1fr; gap: 14px;
           align-items: center; }
.it-icon { width: 80px; height: 80px; background: #0c0d10; border-radius: 3px;
           display: flex; align-items: center; justify-content: center;
           padding: 8px; }
.it-icon img { max-width: 100%; max-height: 100%;
               image-rendering: pixelated; }
.it-icon .none { color: var(--muted); font-size: 10px; font-style: italic; }
.it-name { margin: 0 0 4px; font-size: 16px; font-weight: 600;
           color: var(--fg); }
.it-meta { display: flex; gap: 10px; align-items: center;
           font: 11px ui-monospace, monospace; }
.it-id { color: var(--muted); }
.it-kind { padding: 2px 8px; background: var(--panel-2);
           border: 1px solid var(--border); border-radius: 2px;
           color: var(--accent); text-transform: uppercase;
           letter-spacing: 0.04em; font-weight: 600; }

.it-body { display: grid; grid-template-columns: 1fr 1fr;
           gap: 12px; margin-top: 12px; }
.it-block { background: var(--panel-2); border: 1px solid var(--border);
            border-radius: 3px; padding: 10px 12px; }
.it-block h3 { margin: 0 0 6px; font-size: 11px; text-transform: uppercase;
               letter-spacing: 0.06em; color: var(--accent); font-weight: 600; }
.it-block p { margin: 0; white-space: pre-wrap; line-height: 1.45;
              color: var(--fg); font-size: 12px; }
.it-block .empty { color: var(--muted); font-style: italic; font-size: 11px; }
.stats-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(110px,1fr)); gap: 6px; }
.stats-grid .stat { display: flex; justify-content: space-between;
                    background: var(--bg); border: 1px solid var(--border);
                    border-radius: 2px; padding: 3px 8px; font: 11px ui-monospace, monospace; }
.stats-grid .k { color: var(--muted); text-transform: uppercase;
                 letter-spacing: 0.04em; font-size: 10px; }
.stats-grid .v { color: var(--accent); font-weight: 600; }
"""

EXTRA_JS = """
const rows = document.querySelectorAll('.items .it');
const links = document.querySelectorAll('.s-list a');
const search = document.getElementById('search');
let kindFilter = '';

function applyFilters() {
  const q = (search.value || '').toLowerCase().trim();
  let shown = 0;
  rows.forEach(r => {
    const txt = r.textContent.toLowerCase();
    const k = r.dataset.kind || '';
    const okQ = !q || txt.includes(q);
    const okK = !kindFilter || kindFilter === k;
    const ok = okQ && okK;
    r.style.display = ok ? '' : 'none';
    if (ok) shown++;
  });
  links.forEach(a => {
    const target = a.getAttribute('href').slice(1);
    const r = document.getElementById(target);
    a.style.display = r && r.style.display !== 'none' ? '' : 'none';
  });
  document.getElementById('count').textContent = shown;
}
search?.addEventListener('input', applyFilters);
document.querySelectorAll('.kindfilter a').forEach(a => {
  a.addEventListener('click', e => {
    e.preventDefault();
    document.querySelectorAll('.kindfilter a').forEach(x => x.classList.remove('active'));
    a.classList.add('active');
    kindFilter = a.dataset.kind || '';
    applyFilters();
  });
});
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


def _icon_path(out_root: Path, idx: int) -> str:
    p = out_root / "icons" / f"{idx:04d}.png"
    return f"icons/{idx:04d}.png" if p.exists() else ""


def _is_empty(it: EquipRecord) -> bool:
    """Records that say '空き' (empty slot) or have placeholder names."""
    return (
        it.id.startswith("空き")
        or "？" in (it.en or "")
        or it.en in ("", "EMPTY", "(空き)")
    )


def _render_one(it: EquipRecord, out_root: Path) -> str:
    icon_rel = _icon_path(out_root, it.idx)
    icon_html = (
        f'<img src="{html.escape(icon_rel)}" alt="" loading="lazy">'
        if icon_rel
        else '<div class="none">no icon</div>'
    )
    desc_html = (
        f"<p>{html.escape(it.desc)}</p>"
        if it.desc and "？" not in it.desc
        else '<p class="empty">— no flavor text —</p>'
    )

    s = it.stats
    stat_cells = []

    def cell(label: str, value: int) -> None:
        stat_cells.append(
            f'<div class="stat"><span class="k">{label}</span>'
            f'<span class="v">{value}</span></div>'
        )

    if s.get("atk_min") or s.get("atk_max"):
        if s["atk_min"] == s["atk_max"]:
            cell("ATK", s["atk_min"])
        else:
            cell("ATK", f'{s["atk_min"]}–{s["atk_max"]}')
    if s.get("def_"):
        cell("DEF", s["def_"])
    for label, key in (
        ("STR", "req_a"),
        ("CON", "req_b"),
        ("AGI", "req_c"),
        ("INT", "req_d"),
    ):
        if s.get(key):
            cell(label, s[key])
    if s.get("weight"):
        cell("WT", s["weight"])
    if s.get("buy"):
        cell("BUY", s["buy"])
    if s.get("sell"):
        cell("SELL", s["sell"])

    stats_html = (
        f'<div class="stats-grid">{"".join(stat_cells)}</div>'
        if stat_cells
        else '<p class="empty">— no numeric stats —</p>'
    )
    kind_label = KIND_LABELS.get(it.kind, it.kind)
    name = it.en or it.id or "(unnamed)"
    return f"""
<section class="it" id="i-{it.idx}" data-kind="{html.escape(it.kind)}">
  <div class="it-head">
    <div class="it-icon">{icon_html}</div>
    <div>
      <h2 class="it-name">{html.escape(name)}</h2>
      <div class="it-meta">
        <span class="it-kind">{html.escape(kind_label)}</span>
        <span class="it-id">#{it.idx:04d} · {html.escape(it.id)}</span>
      </div>
    </div>
  </div>
  <div class="it-body">
    <div class="it-block">
      <h3>Stats</h3>
      {stats_html}
    </div>
    <div class="it-block">
      <h3>Description</h3>
      {desc_html}
    </div>
  </div>
</section>
""".strip()


def render_items_page(out_root: Path) -> str:
    items = parse_equip_tbl(out_root / "DATA" / "equip" / "equip" / "EQUIP.tbl")
    items = [it for it in items if not _is_empty(it)]

    # Sidebar
    s_items = []
    for it in items:
        rel = _icon_path(out_root, it.idx)
        thumb = (
            f'<div class="icon"><img src="{html.escape(rel)}" alt=""'
            f' loading="lazy"></div>'
            if rel
            else '<div class="icon"></div>'
        )
        s_items.append(
            f'<a href="#i-{it.idx}">{thumb}'
            f'<div class="s-meta">'
            f'<div class="s-name">{html.escape(it.en or it.id)}</div>'
            f'<div class="s-id">{KIND_LABELS.get(it.kind, it.kind)} '
            f'#{it.idx:04d}</div>'
            f"</div></a>"
        )

    # Kind filter pills
    kinds = []
    counts: dict[str, int] = defaultdict(int)
    for it in items:
        counts[it.kind] += 1
    kind_pills = '<a href="#" class="active" data-kind="">All</a>'
    kind_pills += "".join(
        f'<a href="#" data-kind="{html.escape(k)}">'
        f"{html.escape(KIND_LABELS.get(k, k))} "
        f'<span style="opacity:0.6">{counts[k]}</span></a>'
        for k in sorted(counts, key=lambda k: -counts[k])
    )

    body = f"""
<div class="layout">
  <aside class="sidebar">
    <input id="search" placeholder="filter by name, id, kind..." autofocus>
    <div class="kindfilter">{kind_pills}</div>
    <div class="s-list">{"".join(s_items)}</div>
  </aside>
  <div class="items">
    <p class="lede" style="margin-bottom:18px">Every item from
    <code>DATA/equip/equip/EQUIP.tbl</code> (1024 slots × 692-byte records).
    English names ship in the table; icons come from the
    <code>DATA/SYSTEM/system/ITEM.png</code> 1024×1024 atlas pre-cropped
    to 32×32 cells.  Stats block at +0x250: ATK min/max, DEF, then four
    ability requirements (STR / CON / AGI / INT — best-guess labels);
    +0x280 carries buy/sell prices and weight.  This is the same
    registry that monster drop ids index into.</p>
    {"".join(_render_one(it, out_root) for it in items)}
  </div>
</div>
""".strip()
    return _layout.page(
        title="Xanadu Next — Items",
        active="items.html",
        body=body,
        extra_css=EXTRA_CSS,
        extra_js=EXTRA_JS,
        meta=f'<span id="count">{len(items)}</span>&nbsp;items',
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="xanadu-items")
    p.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "out",
    )
    args = p.parse_args(argv)
    out: Path = args.out
    target = out / "items.html"
    target.write_text(render_items_page(out), encoding="utf-8")
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
