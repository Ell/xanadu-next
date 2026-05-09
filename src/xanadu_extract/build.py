"""Build the static site: enemies, map, items.  Run once after extraction."""

from __future__ import annotations

import argparse
import html
import shutil
from pathlib import Path

from PIL import Image

from . import _layout
from .items import render_items_page
from .monsters import render_areas_page, render_monsters_page


INDEX_BODY = """
<p class="lede" style="font-size:14px;margin-bottom:24px">
A reverse-engineered field guide to <i>Xanadu Next</i> (Falcom, 2005), built
straight from the shipping data files. Three views:
</p>

<div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(260px,1fr)); gap:14px">
  <a href="monsters.html" class="panel" style="text-decoration:none; color:var(--fg); display:block">
    <div style="font-size:11px;color:var(--accent);text-transform:uppercase;letter-spacing:0.06em;margin-bottom:6px">Enemies</div>
    <div style="font-size:18px;font-weight:600;margin-bottom:6px">Bestiary →</div>
    <div style="font-size:12px;color:var(--muted);line-height:1.5">
      Every monster with stats, full loot tables (item names + percentages),
      sprite, and the areas it appears in.
    </div>
  </a>
  <a href="areas.html" class="panel" style="text-decoration:none; color:var(--fg); display:block">
    <div style="font-size:11px;color:var(--accent);text-transform:uppercase;letter-spacing:0.06em;margin-bottom:6px">Map</div>
    <div style="font-size:18px;font-weight:600;margin-bottom:6px">Areas &amp; spawns →</div>
    <div style="font-size:12px;color:var(--muted);line-height:1.5">
      The 17 areas with their named in-game blocks
      (Floodgate, Lakebed Ruins, Eternal Maze, …), tile previews, and the
      monsters that spawn in each.
    </div>
  </a>
  <a href="items.html" class="panel" style="text-decoration:none; color:var(--fg); display:block">
    <div style="font-size:11px;color:var(--accent);text-transform:uppercase;letter-spacing:0.06em;margin-bottom:6px">Items</div>
    <div style="font-size:18px;font-weight:600;margin-bottom:6px">Item registry →</div>
    <div style="font-size:12px;color:var(--muted);line-height:1.5">
      Weapons, armor, consumables — icon, English name, description,
      ATK/DEF/requirements, and the prices the in-game shops charge.
    </div>
  </a>
</div>

<h2 style="margin-top:36px">How this is built</h2>
<p class="lede">Source on <a href="https://github.com/Ell/xanadu-next">GitHub</a>.
Pages are generated from <code>DATA/chr/Object.tbl</code> (monsters),
<code>DATA/equip/equip/EQUIP.tbl</code> (items), <code>DATA/Map/area*/area*.inf</code>
(area + spawn definitions) and the extracted G32 → PNG sprites.</p>
""".strip()


# Subset of DATA/ that the generated site depends on. Everything else gets
# pruned before deploy so the static site stays compact.
KEEP_RELS = {
    Path("DATA/chr/Object.tbl"),
    Path("DATA/chr/motion.tbl"),
}


def _keep_dir(rel: Path) -> bool:
    s = rel.as_posix()
    if s.startswith("DATA/chr/monster/"):
        return True
    if s.startswith("DATA/Map/area"):
        return True
    return False


def _keep_file(rel: Path) -> bool:
    s = rel.as_posix()
    if rel in KEEP_RELS:
        return True
    if s.startswith("DATA/chr/monster/"):
        return rel.suffix.lower() in {".png", ".alg", ".chr"}
    if s.startswith("DATA/Map/area") and "/" in s.split("/", 2)[2]:
        # keep area*.inf and AREA*_*.png; drop scp, mtn, dec etc.
        return rel.suffix.lower() in {".png", ".inf"}
    if s.startswith("DATA/equip/equip/EQUIP.tbl"):
        return True
    if s.startswith("icons/"):
        return True
    return False


def prune_unused(out_root: Path) -> int:
    """Delete files under out/ that the generated site doesn't reference."""
    removed = 0
    for path in sorted(out_root.rglob("*"), reverse=True):
        if path.is_file():
            rel = path.relative_to(out_root)
            if rel.suffix.lower() in {".html"}:
                continue
            if not _keep_file(rel):
                path.unlink()
                removed += 1
        elif path.is_dir():
            try:
                path.rmdir()  # only removes if empty
            except OSError:
                pass
    return removed


def extract_item_icons(out_root: Path) -> int:
    """Crop DATA/SYSTEM/system/ITEM.png (1024x1024 atlas) into 32x32 PNGs.
    Each non-transparent cell becomes out/icons/NNNN.png; the source atlas
    is then no longer needed in the deploy."""
    src = out_root / "DATA" / "SYSTEM" / "system" / "ITEM.png"
    if not src.is_file():
        return 0
    img = Image.open(src)
    out = out_root / "icons"
    out.mkdir(exist_ok=True)
    n = 0
    for i in range(1024):
        x = (i % 32) * 32
        y = (i // 32) * 32
        cell = img.crop((x, y, x + 32, y + 32))
        if cell.getextrema()[3][1] == 0:
            continue
        cell.save(out / f"{i:04d}.png", optimize=True)
        n += 1
    return n


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="xanadu-build")
    p.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "out",
    )
    p.add_argument(
        "--prune",
        action="store_true",
        help="delete files under out/ that the site doesn't depend on",
    )
    args = p.parse_args(argv)
    out: Path = args.out

    n_icons = extract_item_icons(out)
    print(f"icons: {n_icons}")

    # Render the three core pages + a landing index.
    (out / "monsters.html").write_text(render_monsters_page(out), encoding="utf-8")
    print(f"wrote {out / 'monsters.html'}")
    (out / "areas.html").write_text(render_areas_page(out), encoding="utf-8")
    print(f"wrote {out / 'areas.html'}")
    (out / "items.html").write_text(render_items_page(out), encoding="utf-8")
    print(f"wrote {out / 'items.html'}")
    (out / "index.html").write_text(
        _layout.page(
            title="Xanadu Next — field guide",
            active="",
            body=INDEX_BODY,
        ),
        encoding="utf-8",
    )
    print(f"wrote {out / 'index.html'}")

    if args.prune:
        # Old pages produced by the deleted viewer/debug generators
        for stale in ["debug.html"]:
            p = out / stale
            if p.exists():
                p.unlink()
                print(f"removed stale {stale}")
        n = prune_unused(out)
        print(f"pruned {n} files")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
