# xanadu-extract

Asset extractor and bestiary viewer for **Xanadu Next** (Falcom, 2005).

The Steam build of Xanadu Next ships every asset in Falcom's proprietary
`.arc`/`.dir` archive pairs, with images stored in the planar-RGBA `G32` format
that almost no general-purpose tooling understands. This project reverse
engineers the archives, decodes the G32 images, parses the binary
`Object.tbl` to recover monster stats and drop tables, and emits a static
HTML site you can browse — including a complete bestiary cross-referenced
against the per-area encounter tables.

A live build of the site is published from this repo's `gh-pages` branch.

## Pages

- **`monsters.html`** — bestiary with sprite, stats (Lv/HP/MP/ATK/DEF/XP/Gold),
  drop table with normalized weights, area cross-references, and the
  AI-script commentary from each monster's `.alg` file.
- **`areas.html`** — every area declaration from `area*.inf`: the in-game
  English block names, encounter slot count, and DROP() entries for
  breakable scenery in that map.
- **`index.html`** — image / audio / video grids over every extracted asset
  with a click-to-open lightbox (mouse-wheel zoom, drag-pan, prev/next).
- **`debug.html`** — the dev cruft Falcom shipped: bilingual rendering of all
  Japanese commentary in `sound.tbl`, `bgm.tbl`, the AI scripts, and
  effects tables, plus an inventory of backup folders, test maps, and
  scenario placeholders left in the data files.

## Reverse-engineered formats

- **`.arc`/`.dir` pair** — parallel files; each `.dir` record is 108 bytes
  (100-byte filename + uint32 size + uint32 dummy), files are packed into
  the `.arc` in declaration order. (`src/xanadu_extract/archive.py`)
- **`.G32` image** — 16-byte header (uint32 w, h, then two flag words) +
  RLE-compressed body interleaving four R/G/B/A planes. Eight opcodes:
  literal-copy and three flavors of run (RLE byte / RLE 0x00 / RLE 0xFF).
  Decoder ported from `G32_DecompressBody` at 0x004e4880 in `XANADU.exe`.
  (`src/xanadu_extract/g32.py`)
- **`Object.tbl`** — 1108-byte fixed-size records: 16 byte ID +
  (English/JP) name + 16×uint32 stats with the actual value in the high
  16 bits + an ASCII drop table at offset 0x2FE. Drops use
  `<id>(<weight>)` syntax; positive ids reference world props that act as
  pickups, negatives are engine-internal gold/exp pools.
  (`src/xanadu_extract/objects.py`)

## Building

```sh
uv sync                 # install dependencies (Python 3.12+, Pillow)
uv run xanadu-extract   # walk DATA/, decode archives + G32 → out/
uv run xanadu-viewer    # generate the asset browser (out/index.html)
uv run xanadu-monsters  # generate the bestiary + areas pages
uv run xanadu-debug     # generate the dev-cruft commentary page
```

Default game path is `~/.local/share/Steam/steamapps/common/Xanadu Next` —
override with `--game DIR` if you have it installed elsewhere. Default
output is `./out/`.

## Acknowledgements

Reverse engineering performed in Ghidra against the Steam binary. No game
assets are checked into this repository — the extracted output (`out/`) is
deployed to the `gh-pages` branch only, and is built from the user's local
copy of the game.
