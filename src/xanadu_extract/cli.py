"""xanadu-extract: pull every shipping asset out of Xanadu Next.

Usage:
    xanadu-extract [--game DIR] [--out DIR] [--no-images]
"""

from __future__ import annotations

import argparse
import shutil
import sys
from collections import Counter
from pathlib import Path

from PIL import Image

from .archive import find_pairs, iter_arc
from .g32 import G32Error, decode_to_rgba

DEFAULT_GAME = Path.home() / ".local/share/Steam/steamapps/common/Xanadu Next"
DEFAULT_OUT = Path(__file__).resolve().parents[2] / "out"

LOOSE_VIDEO_DIRS = ("movie",)
# Top-level archive paths whose contents we never want to ship: BGM/WAVE
# carry hundreds of MBs of audio that the bestiary doesn't need.
SKIP_ARCHIVE_PARENTS = {"BGM", "WAVE"}
COPY_ALONGSIDE = {
    Path("DATA/chr/Object.tbl"),
    Path("DATA/chr/motion.tbl"),
    Path("DATA/SYSTEM/system/ITEM.png"),
}
# Per-archive name suffixes we want to ship.  Map archives carry .scp
# script files alongside G32 tiles — the .scp files contain the static
# PUT_MONSTER spawn declarations that drive the map viewer.
ARCHIVE_KEEP_EXT = {
    "Map": {".g32", ".scp", ".inf"},
}


def safe_relpath(name: str) -> Path:
    """Translate an entry name into a safe POSIX path under the output dir."""
    parts: list[str] = []
    for chunk in name.replace("\\", "/").split("/"):
        chunk = chunk.strip()
        if not chunk or chunk in (".", ".."):
            continue
        parts.append(chunk)
    return Path(*parts) if parts else Path("_unnamed")


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def extract_archive(
    dir_path: Path,
    arc_path: Path,
    game_root: Path,
    out_root: Path,
    *,
    do_images: bool,
) -> Counter[str]:
    rel = dir_path.parent.relative_to(game_root)
    archive_out = out_root / rel / dir_path.stem
    parent = rel.parts[1] if len(rel.parts) > 1 else ""
    keep_ext = ARCHIVE_KEEP_EXT.get(parent)
    stats: Counter[str] = Counter()
    for entry, blob in iter_arc(dir_path, arc_path):
        rel_inner = safe_relpath(entry.name)
        target = archive_out / rel_inner
        ext = rel_inner.suffix.lower()
        if keep_ext is not None and ext not in keep_ext:
            stats[f"skip-{ext.lstrip('.')}"] += 1
            continue

        if ext == ".g32" and do_images:
            try:
                w, h, pixels = decode_to_rgba(blob)
            except G32Error as e:
                print(f"  ! {rel_inner}: {e}", file=sys.stderr)
                write_atomic(target, blob)
                stats["g32_failed"] += 1
                continue
            png_target = target.with_suffix(".png")
            png_target.parent.mkdir(parents=True, exist_ok=True)
            Image.frombytes("RGBA", (w, h), pixels).save(png_target, optimize=True)
            stats["png"] += 1
        else:
            write_atomic(target, blob)
            stats[ext.lstrip(".") or "(none)"] += 1
    return stats


def copy_loose(src_dir: Path, dst_dir: Path, *, suffixes: set[str]) -> Counter[str]:
    stats: Counter[str] = Counter()
    if not src_dir.is_dir():
        return stats
    for src in sorted(src_dir.rglob("*")):
        if not src.is_file():
            continue
        if src.suffix.lower() not in suffixes:
            continue
        rel = src.relative_to(src_dir)
        dst = dst_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        stats[src.suffix.lstrip(".").lower() or "(none)"] += 1
    return stats


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="xanadu-extract", description=__doc__)
    p.add_argument(
        "--game", type=Path, default=DEFAULT_GAME, help="game install directory"
    )
    p.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output directory")
    p.add_argument(
        "--no-images", action="store_true", help="skip G32 → PNG conversion"
    )
    args = p.parse_args(argv)

    game: Path = args.game
    out: Path = args.out
    if not game.is_dir():
        p.error(f"game dir not found: {game}")

    data_root = game / "DATA"
    if not data_root.is_dir():
        p.error(f"DATA/ not found under {game}")

    out.mkdir(parents=True, exist_ok=True)
    print(f"game:   {game}")
    print(f"output: {out}")

    do_images = not args.no_images
    overall: Counter[str] = Counter()

    pairs = find_pairs(data_root)
    print(f"\n[archives] {len(pairs)} .arc/.dir pairs (skipping audio)")
    for dir_path, arc_path in pairs:
        rel = dir_path.relative_to(game)
        if rel.parts and rel.parts[1] in SKIP_ARCHIVE_PARENTS:
            print(f"  {rel} → skipped (audio)")
            continue
        stats = extract_archive(
            dir_path,
            arc_path,
            game,
            out,
            do_images=do_images,
        )
        summary = ", ".join(f"{n} {k}" for k, n in sorted(stats.items()))
        print(f"  {rel} → {summary}")
        overall.update(stats)

    for sub in LOOSE_VIDEO_DIRS:
        src = data_root / sub
        stats = copy_loose(src, out / "DATA" / sub, suffixes={".avi"})
        if stats:
            print(
                f"  DATA/{sub} → "
                + ", ".join(f"{n} {k}" for k, n in sorted(stats.items()))
            )
            overall.update(stats)

    # loose tables we want to keep alongside archive output
    for rel in COPY_ALONGSIDE:
        src = game / rel
        if src.is_file():
            dst = out / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            overall[src.suffix.lstrip(".").lower()] += 1

    print("\n[total]")
    for kind, n in sorted(overall.items()):
        print(f"  {kind:>8}  {n}")
    print(f"\nWrote {sum(overall.values())} files under {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
