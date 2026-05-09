"""Parse Falcom's .chr scene-graph format used in Xanadu Next.

Reverse-engineered from XANADU.exe (Steam build):
- entry point: FUN_004f4650 (the public CD3DFile loader)
- recursive parser: FUN_004f4130 (parses one Frame node)
- mesh payload: FUN_004f3650 (kind=1, the only path we currently emit)

File layout
-----------

  uint32   header_dword                (read once at file start, ignored —
                                        the loader allocates a buffer based
                                        on it but does not validate it)

Then a tree of Frame nodes, each:

  uint8    kind                        0 = empty, 1 = mesh,
                                       2 = bone-skin variant (ignored),
                                       3 = bone-skin variant 2 (ignored)
  char[32] name                        utf-cp932, null-padded
  char[32] child_name                  recurse if first byte != 0
  char[32] sibling_name                recurse if first byte != 0
  float[16] transform                  4x4 row-major matrix
  uint32   count1
  if count1 > 2:                       count1 records of 20 bytes each
  uint32   count2
  if count2 > 2:                       count2 records of 16 bytes each
  uint32   count3
  if count3 > 2:                       count3 records of 16 bytes each
  if kind == 1:
      char[32] mesh_name
      uint32   vert_count
      vert     verts[vert_count]       32 bytes each: pos(12)+normal(12)+uv(8)
      uint32   idx_count
      uint16   indices[idx_count]
      uint32   face_count
      uint32   face_attr[face_count]   per-face material index
      uint32   mat_count
      mat      mats[mat_count]         0xa0 bytes each (D3D material + texture
                                       name — partially decoded below)
  if child_name != "":  recurse
  if sibling_name != "": recurse

Materials (0xa0 bytes per record)
---------------------------------
The loader reads them in two halves: 0x44 bytes then 0x40 bytes. The first
half contains an FVF descriptor and the texture filename string; the
second is D3D state (diffuse/ambient/etc).  Texture filename is at offset
~0x14 within the second half — we extract any null-terminated ASCII string
we find as the texture name.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path


@dataclass
class Mesh:
    name: str
    verts: bytes  # vert_count * 32 bytes (pos[3], normal[3], uv[2])
    indices: bytes  # idx_count * uint16
    face_attrs: bytes  # face_count * uint32
    materials: list[bytes]  # each 0xa0 bytes


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
        raise ChrParseError(f"truncated: wanted {n}, got {len(b)} at {buf.tell()}")
    return b


def _u32(buf: BytesIO) -> int:
    return struct.unpack("<I", _read(buf, 4))[0]


def _u8(buf: BytesIO) -> int:
    return _read(buf, 1)[0]


def _read_name(buf: BytesIO) -> str:
    raw = _read(buf, 32)
    return raw.split(b"\x00", 1)[0].decode("cp932", errors="replace")


def _read_frame(buf: BytesIO) -> Frame:
    kind = _u8(buf)
    name = _read_name(buf)
    child_name = _read_name(buf)
    sibling_name = _read_name(buf)
    transform = struct.unpack("<16f", _read(buf, 64))

    # three pre-payload arrays — the engine over-allocates by 2 records, so
    # only sizes > 2 actually carry data on disk.
    for stride in (20, 16, 16):
        count = _u32(buf)
        if count > 2:
            _read(buf, count * stride)

    mesh = None
    if kind == 1:
        mesh = _read_mesh(buf)
    elif kind in (2, 3):
        # We don't decode skinned variants yet — surface that as missing
        # mesh and let the caller decide.  The arrays are still consumed
        # by the kind=1 reader above, so we don't fall out of sync here.
        pass

    frame = Frame(name=name, transform=transform, mesh=mesh)
    if child_name:
        frame.children.append(_read_frame(buf))
    if sibling_name:
        frame.children.append(_read_frame(buf))
    return frame


def _read_mesh(buf: BytesIO) -> Mesh:
    name = _read_name(buf)
    vert_count = _u32(buf)
    verts = _read(buf, vert_count * 32)
    idx_count = _u32(buf)
    indices = _read(buf, idx_count * 2)
    face_count = _u32(buf)
    face_attrs = _read(buf, face_count * 4)
    mat_count = _u32(buf)
    materials = [_read(buf, 0xA0) for _ in range(mat_count)]
    return Mesh(
        name=name,
        verts=verts,
        indices=indices,
        face_attrs=face_attrs,
        materials=materials,
    )


def parse_chr(path: Path) -> Frame:
    raw = path.read_bytes()
    buf = BytesIO(raw)
    _u32(buf)  # leading header word, ignored (allocation hint in engine)
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


def material_texture_name(mat: bytes) -> str:
    """Pluck a likely texture filename out of a 160-byte material record.

    Format isn't fully decoded yet — we scan for the longest plausible
    null-terminated ascii / cp932 string in the second half of the
    record. Empty if nothing readable is present (some materials don't
    carry a texture)."""
    best = ""
    i = 0
    while i < len(mat):
        if 32 <= mat[i] < 127:
            j = i
            while j < len(mat) and 32 <= mat[j] < 127:
                j += 1
            if j - i >= 4 and j - i > len(best):
                best = mat[i:j].decode("latin1", errors="ignore")
            i = j + 1
        else:
            i += 1
    return best
