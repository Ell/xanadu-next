"""Xanadu Next .arc/.dir archive reader.

Format (per QuickBMS script + sum-of-sizes verification across every shipped
archive): the .dir is a flat array of 108-byte records,

    offset 0x00  char[100]  filename (null-padded, sometimes Shift-JIS)
    offset 0x64  uint32 LE  file size
    offset 0x68  uint32 LE  reserved (always zero in shipped data)

followed by a trailing uint32 file count. Files are concatenated in the .arc
in dir order with no padding.
"""

from __future__ import annotations

import struct
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

RECORD_SIZE = 108
NAME_LEN = 100


@dataclass(frozen=True, slots=True)
class Entry:
    name: str
    offset: int
    size: int


def _decode_name(raw: bytes) -> str:
    raw = raw.split(b"\x00", 1)[0]
    try:
        return raw.decode("cp932")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def read_dir(dir_path: Path) -> list[Entry]:
    blob = dir_path.read_bytes()
    n_records = len(blob) // RECORD_SIZE
    entries: list[Entry] = []
    offset = 0
    for i in range(n_records):
        rec = blob[i * RECORD_SIZE : (i + 1) * RECORD_SIZE]
        name = _decode_name(rec[:NAME_LEN])
        size = struct.unpack_from("<I", rec, NAME_LEN)[0]
        entries.append(Entry(name=name, offset=offset, size=size))
        offset += size
    return entries


def iter_arc(dir_path: Path, arc_path: Path) -> Iterator[tuple[Entry, bytes]]:
    """Yield (entry, raw_bytes) for every file in an archive."""
    entries = read_dir(dir_path)
    with arc_path.open("rb") as f:
        for e in entries:
            f.seek(e.offset)
            yield e, f.read(e.size)


def find_pairs(data_root: Path) -> list[tuple[Path, Path]]:
    """Find all .dir/.arc pairs under data_root (case-insensitive on extension)."""
    pairs: list[tuple[Path, Path]] = []
    for dir_path in sorted(data_root.rglob("*")):
        if not dir_path.is_file() or dir_path.suffix.lower() != ".dir":
            continue
        arc_path = dir_path.with_suffix(".arc")
        if not arc_path.exists():
            arc_path = dir_path.with_suffix(".ARC")
        if arc_path.exists():
            pairs.append((dir_path, arc_path))
    return pairs
