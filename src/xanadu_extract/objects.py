"""Parse DATA/chr/Object.tbl — the master table of monsters, objects and NPCs.

Format (reverse-engineered from the binary):
- 2-byte file prefix, then fixed-size 1108-byte records.
- Each record:
    +0x000  16 bytes   ID, null-padded (e.g. "M_0000", "O_0226", "N_0270")
    +0x011  ~24 bytes  English name (null-terminated)
    +0x030  uint32     flags / record kind (0x01010000 for monsters)
    +0x034  uint32     Lv  (high 16 bits)
    +0x038  uint32     HP
    +0x03c  uint32     MP
    +0x040  uint32     XP
    +0x044  uint32     Gold
    +0x048  uint32     ATK
    +0x04c  uint32     DEF
    +0x050..+0x06c     additional stat fields (resistances, attack rate, etc.)
    +0x2fe  ascii      drop table:  "<id>(<weight>) ..."  null-terminated
    +0x31f  ascii      secondary drop / chest table

Drop entries:
- positive id `nnn` references object record `O_NNNN` (a breakable/pickup).
- negative id is a special pool: gold/exp tiers (the absolute value is roughly
  scaled to the monster's level).
- the parenthesised number is a *weight*, not a percent, so a row like
  `001(20) 226(20) 210(50) -20(100)` is normalized to those weights.
"""

from __future__ import annotations

import json
import re
import struct
from dataclasses import asdict, dataclass, field
from pathlib import Path

REC_SIZE = 1108
EQUIP_REC_SIZE = 692


@dataclass
class EquipRecord:
    """One row of DATA/equip/equip/EQUIP.tbl, the item registry that monster
    drop ids index into."""

    idx: int
    id: str  # eg "SL1_0020", "ITM_0000", "ARM_0002"
    en: str  # eg "Gladius", "Heal Potion S"
    desc: str
    stats: dict[str, int] = field(default_factory=dict)

    @property
    def kind(self) -> str:
        return self.id.split("_", 1)[0] if "_" in self.id else "?"


@dataclass
class ObjRecord:
    id: str
    en: str
    flags: int
    lv: int
    hp: int
    mp: int
    xp: int
    gold: int
    atk: int
    df: int
    extras: list[int] = field(default_factory=list)
    drops: str = ""
    drops_after: str = ""

    @property
    def kind(self) -> str:
        return self.id.split("_", 1)[0] if "_" in self.id else "?"


def parse_object_tbl(path: Path) -> list[ObjRecord]:
    raw = path.read_bytes()
    records: list[ObjRecord] = []
    n = (len(raw) - 2) // REC_SIZE
    for i in range(n):
        off = 2 + i * REC_SIZE
        rec = raw[off : off + REC_SIZE]
        rid = rec[0:16].split(b"\x00", 1)[0].decode("cp932", "replace").strip()
        if not rid:
            continue
        en = (
            rec[0x11 : 0x11 + 24]
            .split(b"\x00", 1)[0]
            .decode("cp932", "replace")
            .strip()
        )
        s = struct.unpack_from("<16I", rec, 0x30)
        records.append(
            ObjRecord(
                id=rid,
                en=en,
                flags=s[0],
                lv=s[1] >> 16,
                hp=s[2] >> 16,
                mp=s[3] >> 16,
                xp=s[4] >> 16,
                gold=s[5] >> 16,
                atk=s[6] >> 16,
                df=s[7] >> 16,
                extras=[v >> 16 for v in s[8:16]],
                drops=rec[0x2FE : 0x2FE + 200]
                .split(b"\x00", 1)[0]
                .decode("latin1", "replace")
                .strip(),
                drops_after=rec[0x31F : 0x31F + 200]
                .split(b"\x00", 1)[0]
                .decode("latin1", "replace")
                .strip(),
            )
        )
    return records


_DROP_RE = re.compile(r"(-?\d+)\((\d+)\)")


def parse_drop_table(s: str) -> list[tuple[int, int]]:
    """Returns list of (item_id, weight). Negative ids are tiered gold/exp pools."""
    return [(int(a), int(b)) for a, b in _DROP_RE.findall(s)]


def normalize_drops(drops: list[tuple[int, int]]) -> list[tuple[int, float]]:
    total = sum(w for _, w in drops)
    if total == 0:
        return [(i, 0.0) for i, _ in drops]
    return [(i, 100.0 * w / total) for i, w in drops]


def special_drop_label(neg_id: int) -> str:
    """The negative drop ids are tiered loot pools.  We don't have an exact
    decode for them, but the *magnitude* tracks roughly with monster level —
    so describing them as 'small/medium/large' pools is the most useful
    presentation in the absence of the engine's runtime mapping."""
    n = -neg_id
    if n < 30:
        tier = "tier 1"
    elif n < 100:
        tier = "tier 2"
    elif n < 300:
        tier = "tier 3"
    elif n < 800:
        tier = "tier 4"
    else:
        tier = "tier 5"
    return f"loot pool {tier} (#{n})"


def index_by_id(records: list[ObjRecord]) -> dict[str, ObjRecord]:
    return {r.id: r for r in records}


def parse_equip_tbl(path: Path) -> list[EquipRecord]:
    """Parse the item registry.  692-byte records: id at +0x06, English
    name at +0x17, description at +0x58, stat block of uint32 fields at
    +0x250 (atk-min/atk-max/def + ability requirements) and +0x280 (buy/sell
    prices and weight). Drop ids index directly into this list."""
    raw = path.read_bytes()
    out: list[EquipRecord] = []
    n = len(raw) // EQUIP_REC_SIZE
    for i in range(n):
        off = i * EQUIP_REC_SIZE
        rec = raw[off : off + EQUIP_REC_SIZE]
        rid = rec[6:18].split(b"\x00", 1)[0].decode("cp932", "replace").strip()
        en = (
            rec[0x17 : 0x17 + 24]
            .split(b"\x00", 1)[0]
            .decode("cp932", "replace")
            .strip()
        )
        desc = (
            rec[0x58 : 0x58 + 256]
            .split(b"\x00", 1)[0]
            .decode("cp932", "replace")
            .strip()
        )
        s = struct.unpack_from("<8I", rec, 0x250)
        s2 = struct.unpack_from("<8I", rec, 0x280)
        stats = {
            "atk_min": s[0],
            "atk_max": s[1],
            "def_": s[2],
            "req_a": s[3],
            "req_b": s[4],
            "req_c": s[5],
            "req_d": s[6],
            "buy": s2[0],
            "sell": s2[2],
            "weight": s2[4],
        }
        out.append(EquipRecord(idx=i, id=rid, en=en, desc=desc, stats=stats))
    return out


def lookup_drop_object(item_id: int, by_id: dict[str, ObjRecord]) -> ObjRecord | None:
    """Drop-table positive ids reference O_NNNN entries in the same table."""
    return by_id.get(f"O_{item_id:04d}")


def dump_json(records: list[ObjRecord], path: Path) -> None:
    path.write_text(
        json.dumps([asdict(r) for r in records], ensure_ascii=False, indent=1)
    )
