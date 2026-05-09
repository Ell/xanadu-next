"""Parse Falcom's .chr scene-graph format used in Xanadu Next.

Reverse-engineered from XANADU.exe (Steam build):
- entry point: FUN_004f4650 (the public CD3DFile loader)
- per-Frame parser: FUN_004f4130
- mesh payloads: FUN_004f3650 (kind=1, rigid) / FUN_004f2d90 (kind=2,
  skinned variant 1) / FUN_004f3ba0 (kind=3, skinned variant 2)

The on-disk file is compressed (see ``chr_decompress``); this module
operates on the *decompressed* buffer.

File layout
-----------

  uint32   header_dword                ignored by the parser

Then a tree of Frame nodes, each:

  uint8    kind                        0 = empty, 1 = rigid mesh,
                                       2/3 = skinned mesh variants
  char[32] name                        utf-cp932, null-padded
  char[32] child_name                  recurse if first byte != 0
  char[32] sibling_name                recurse if first byte != 0
  float[16] transform                  4x4 row-major matrix
  uint32   count1
  if count1 > 2:                       count1 records of 20 bytes
  uint32   count2
  if count2 > 2:                       count2 records of 16 bytes
  uint32   count3
  if count3 > 2:                       count3 records of 16 bytes
  if kind == 1: rigid mesh payload     (FUN_004f3650 layout)
  if kind == 2: skinned mesh payload   (FUN_004f2d90 layout)
  if kind == 3: skinned mesh payload   (FUN_004f3ba0 layout — same as 2)
  if child_name  != "":  recurse
  if sibling_name != "": recurse

Mesh payload (kind=1, rigid)
----------------------------
  char[32]  mesh_name
  uint32    vert_count
  vert      verts[vert_count]          32 bytes each: pos[3], normal[3],
                                       uv[2] floats
  uint32    idx_count
  uint16    indices[idx_count]
  uint32    face_count
  uint32    face_attrs[face_count]
  uint32    mat_count
  byte[160] mats[mat_count]            D3D material + texture filename

Mesh payload (kind=2/3, skinned)
--------------------------------
Identical leading layout to kind=1 (name, verts, indices, face_attrs,
materials), then a bone block:

  uint32    bone_count
  bone      bones[bone_count]:
    char[32]  bone_name
    float[16] inverse_bind_matrix
    uint32    weight_count
    uint32    weight_indices[weight_count]
    float     weight_values[weight_count]      (the source code reads
                                                ``weight_count*4`` then
                                                another ``weight_count*4``
                                                — here treated as a
                                                vertex-id list and a
                                                float weight list)
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

from .chr_decompress import ChrDecompressError, decompress


@dataclass
class Material:
    """One material record. Read as 0x44 + 0x40 = 132 bytes from disk
    (the engine's in-memory struct is 0xa0 bytes, but the trailing 28
    bytes are runtime-initialized to constants — see FUN_004f3650
    around the per-material loop)."""

    raw: bytes
    texture: str = ""

    @classmethod
    def parse(cls, raw: bytes) -> "Material":
        # Texture filename lives in the second half (offset +0x44).
        # Pluck the longest printable ASCII run of length >= 4 as a
        # best-effort.
        best = ""
        i = 0x44
        while i < len(raw):
            if 32 <= raw[i] < 127:
                j = i
                while j < len(raw) and 32 <= raw[j] < 127:
                    j += 1
                if j - i >= 4 and j - i > len(best):
                    best = raw[i:j].decode("latin1", errors="ignore")
                i = j + 1
            else:
                i += 1
        return cls(raw=raw, texture=best)


@dataclass
class Bone:
    name: str
    matrix: tuple[float, ...]  # 16 floats, inverse-bind
    weights_idx: list[int] = field(default_factory=list)
    weights_val: list[float] = field(default_factory=list)


@dataclass
class Mesh:
    name: str
    verts: bytes  # vert_count * 32 bytes (pos[3], normal[3], uv[2])
    indices: bytes  # idx_count * uint16
    face_attrs: bytes  # face_count * uint32
    materials: list[Material]
    bones: list[Bone] = field(default_factory=list)
    skinned: bool = False


@dataclass
class Frame:
    name: str
    transform: tuple[float, ...]  # 16 floats, row-major
    children: list["Frame"] = field(default_factory=list)
    mesh: Mesh | None = None


class ChrParseError(Exception):
    pass


def _read(buf: BytesIO, n: int) -> bytes:
    b = buf.read(n)
    if len(b) != n:
        raise ChrParseError(
            f"truncated: wanted {n}, got {len(b)} at {buf.tell()}"
        )
    return b


def _u32(buf: BytesIO) -> int:
    return struct.unpack("<I", _read(buf, 4))[0]


def _u8(buf: BytesIO) -> int:
    return _read(buf, 1)[0]


def _read_name(buf: BytesIO) -> str:
    raw = _read(buf, 32)
    return raw.split(b"\x00", 1)[0].decode("cp932", errors="replace")


def _read_mesh_common(buf: BytesIO) -> Mesh:
    """Read the leading-common portion of a mesh (kind 1/2/3): name +
    verts + indices + face attrs + materials."""
    name = _read_name(buf)
    vert_count = _u32(buf)
    verts = _read(buf, vert_count * 32)
    idx_count = _u32(buf)
    indices = _read(buf, idx_count * 2)
    face_count = _u32(buf)
    face_attrs = _read(buf, face_count * 4)
    mat_count = _u32(buf)
    # 0x84 bytes per material on disk (0x44 + 0x40), not 0xa0.
    materials = [Material.parse(_read(buf, 0x84)) for _ in range(mat_count)]
    return Mesh(
        name=name,
        verts=verts,
        indices=indices,
        face_attrs=face_attrs,
        materials=materials,
    )


def _read_skin_block(buf: BytesIO, mesh: Mesh) -> None:
    """Append bone/skin data to mesh (kind 2/3 only)."""
    bone_count = _u32(buf)
    for _ in range(bone_count):
        bone_name = _read_name(buf)
        matrix = struct.unpack("<16f", _read(buf, 64))
        weight_count = _u32(buf)
        weights_idx = list(struct.unpack(
            f"<{weight_count}I", _read(buf, weight_count * 4)
        ))
        weights_val = list(struct.unpack(
            f"<{weight_count}f", _read(buf, weight_count * 4)
        ))
        mesh.bones.append(
            Bone(
                name=bone_name,
                matrix=matrix,
                weights_idx=weights_idx,
                weights_val=weights_val,
            )
        )
    mesh.skinned = True


def _read_frame(buf: BytesIO) -> Frame:
    kind = _u8(buf)
    name = _read_name(buf)
    child_name = _read_name(buf)
    sibling_name = _read_name(buf)
    transform = struct.unpack("<16f", _read(buf, 64))

    # three pre-payload arrays — the engine over-allocates by 2 records,
    # so only sizes > 2 actually carry data on disk.
    for stride in (20, 16, 16):
        count = _u32(buf)
        if count > 2:
            _read(buf, count * stride)

    mesh: Mesh | None = None
    if kind == 1:
        mesh = _read_mesh_common(buf)
    elif kind in (2, 3):
        mesh = _read_mesh_common(buf)
        _read_skin_block(buf, mesh)

    frame = Frame(name=name, transform=transform, mesh=mesh)
    # Recursion order matches the engine: 3rd name (sibling) first,
    # then 2nd name (child).  Both are appended as children of this
    # frame in the in-memory tree.
    if sibling_name:
        frame.children.append(_read_frame(buf))
    if child_name:
        frame.children.append(_read_frame(buf))
    return frame


def parse_chr(path: Path) -> Frame:
    """Parse a .chr file from disk: decompress + parse the scene graph."""
    raw = path.read_bytes()
    decompressed = decompress(raw)
    buf = BytesIO(decompressed)
    _u32(buf)  # leading header word, ignored
    return _read_frame(buf)


def collect_meshes(root: Frame) -> list[tuple[Frame, Mesh]]:
    out: list[tuple[Frame, Mesh]] = []

    def walk(f: Frame) -> None:
        if f.mesh is not None:
            out.append((f, f.mesh))
        for c in f.children:
            walk(c)

    walk(root)
    return out
