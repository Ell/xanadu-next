"""Emit minimal .glb (binary glTF 2.0) for each monster .chr.

We pick a single mesh per monster (the first kind=2/3 skinned mesh in
the scene graph — that's the visual body in every Xanadu Next monster
file we've inspected) and write:
- one positions accessor (vec3 float)
- one normals accessor (vec3 float)
- one uvs accessor (vec2 float)
- one indices accessor (u16)
- one material with baseColorTexture pointing at the extracted PNG
- one mesh with one primitive

We do not export bones / skinning / animation — getting a static
posed model into the bestiary viewer is the goal here.

Vertex format on disk (32 bytes / vertex):
    +0   pos.x  float
    +4   pos.y  float
    +8   pos.z  float
    +12  normal.x  float
    +16  normal.y  float
    +20  normal.z  float
    +24  uv.u   float
    +28  uv.v   float
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

from .chr_format import Frame, Mesh, collect_meshes, parse_chr


def _pick_mesh(root: Frame) -> tuple[Frame, Mesh] | None:
    meshes = collect_meshes(root)
    if not meshes:
        return None
    # Prefer the largest mesh by vertex count.
    meshes.sort(key=lambda fm: -(len(fm[1].verts) // 32))
    return meshes[0]


def _resolve_texture(monster_dir: Path, tex_name: str) -> str | None:
    """The .chr stores textures as .bmp filenames; we have .png versions
    of those textures from the G32 → PNG extraction.  Try a few common
    name variants (M_xxxx.png / M_xxxx_lower.png / variant suffixes)."""
    if not tex_name:
        return None
    base = tex_name.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
    stem = base.rsplit(".", 1)[0]
    # Direct match
    for cand in (f"{stem}.png", f"{stem.lower()}.png", f"{stem.upper()}.png"):
        if (monster_dir / cand).exists():
            return cand
    # Glob fallback — any png in the folder containing the stem
    for p in monster_dir.glob("*.png"):
        if stem.lower() in p.name.lower():
            return p.name
    # Otherwise pick any png
    pngs = sorted(monster_dir.glob("*.png"))
    return pngs[0].name if pngs else None


def _pad4(b: bytes) -> bytes:
    pad = (-len(b)) % 4
    return b + b"\x00" * pad


def write_glb(chr_path: Path, glb_path: Path, texture_path: Path | None) -> bool:
    """Convert one monster .chr to a .glb at ``glb_path``.  Returns True
    on success, False if the chr has no mesh."""
    root = parse_chr(chr_path)
    pick = _pick_mesh(root)
    if pick is None:
        return False
    _, mesh = pick

    vert_count = len(mesh.verts) // 32
    idx_count = len(mesh.indices) // 2

    # Reinterpret vertex stream into separate position/normal/uv streams.
    pos_buf = bytearray()
    nrm_buf = bytearray()
    uv_buf = bytearray()
    pmin = [float("inf")] * 3
    pmax = [float("-inf")] * 3
    for i in range(vert_count):
        off = i * 32
        px, py, pz = struct.unpack_from("<3f", mesh.verts, off)
        nx, ny, nz = struct.unpack_from("<3f", mesh.verts, off + 12)
        u, v = struct.unpack_from("<2f", mesh.verts, off + 24)
        pos_buf += struct.pack("<3f", px, py, pz)
        nrm_buf += struct.pack("<3f", nx, ny, nz)
        # glTF uv origin is upper-left; the engine's uv origin appears
        # to also be upper-left, so leave as-is.
        uv_buf += struct.pack("<2f", u, v)
        for c, val in enumerate((px, py, pz)):
            if val < pmin[c]: pmin[c] = val
            if val > pmax[c]: pmax[c] = val
    if not (pmin[0] < float("inf")):
        pmin = [0.0, 0.0, 0.0]
        pmax = [0.0, 0.0, 0.0]

    idx_buf = bytes(mesh.indices)

    # Build texture as embedded image URI when we have one
    has_tex = texture_path is not None and texture_path.exists()
    image_data = texture_path.read_bytes() if has_tex else None

    # Lay out binary buffer: positions, normals, uvs, indices, [image]
    parts = [bytes(pos_buf), bytes(nrm_buf), bytes(uv_buf), idx_buf]
    if image_data is not None:
        parts.append(image_data)
    binary = b""
    bv_offsets: list[tuple[int, int]] = []  # (offset, length)
    for p in parts:
        bv_offsets.append((len(binary), len(p)))
        binary += _pad4(p)
    binary_padded = binary  # already 4-byte aligned

    buffer_views = [
        {"buffer": 0, "byteOffset": bv_offsets[0][0], "byteLength": bv_offsets[0][1], "target": 34962},  # ARRAY_BUFFER
        {"buffer": 0, "byteOffset": bv_offsets[1][0], "byteLength": bv_offsets[1][1], "target": 34962},
        {"buffer": 0, "byteOffset": bv_offsets[2][0], "byteLength": bv_offsets[2][1], "target": 34962},
        {"buffer": 0, "byteOffset": bv_offsets[3][0], "byteLength": bv_offsets[3][1], "target": 34963},  # ELEMENT_ARRAY_BUFFER
    ]
    if image_data is not None:
        buffer_views.append({
            "buffer": 0,
            "byteOffset": bv_offsets[4][0],
            "byteLength": bv_offsets[4][1],
        })

    accessors = [
        {"bufferView": 0, "componentType": 5126, "count": vert_count, "type": "VEC3", "min": pmin, "max": pmax},
        {"bufferView": 1, "componentType": 5126, "count": vert_count, "type": "VEC3"},
        {"bufferView": 2, "componentType": 5126, "count": vert_count, "type": "VEC2"},
        {"bufferView": 3, "componentType": 5123, "count": idx_count, "type": "SCALAR"},
    ]

    images: list[dict] = []
    textures: list[dict] = []
    materials: list[dict] = []
    if image_data is not None:
        images.append({"bufferView": 4, "mimeType": "image/png"})
        textures.append({"source": 0, "sampler": 0})
        materials.append({
            "name": "monster",
            "pbrMetallicRoughness": {
                "baseColorTexture": {"index": 0},
                "metallicFactor": 0.0,
                "roughnessFactor": 1.0,
            },
            "alphaMode": "MASK",
            "alphaCutoff": 0.5,
            "doubleSided": True,
        })
    else:
        materials.append({
            "name": "monster",
            "pbrMetallicRoughness": {
                "baseColorFactor": [0.7, 0.7, 0.7, 1.0],
                "metallicFactor": 0.0,
                "roughnessFactor": 1.0,
            },
            "doubleSided": True,
        })

    samplers = [{"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497}]

    gltf = {
        "asset": {"version": "2.0", "generator": "xanadu-extract"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": chr_path.stem}],
        "meshes": [{
            "name": chr_path.stem,
            "primitives": [{
                "attributes": {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2},
                "indices": 3,
                "material": 0,
            }],
        }],
        "buffers": [{"byteLength": len(binary_padded)}],
        "bufferViews": buffer_views,
        "accessors": accessors,
        "materials": materials,
        "samplers": samplers,
    }
    if textures:
        gltf["textures"] = textures
    if images:
        gltf["images"] = images

    json_text = json.dumps(gltf, separators=(",", ":")).encode("ascii")
    json_padded = _pad4(json_text + b" " * ((-(len(json_text)) % 4)))
    # GLB header
    glb_path.parent.mkdir(parents=True, exist_ok=True)
    with glb_path.open("wb") as f:
        total_length = 12 + 8 + len(json_padded) + 8 + len(binary_padded)
        f.write(b"glTF")
        f.write(struct.pack("<II", 2, total_length))
        f.write(struct.pack("<I", len(json_padded)))
        f.write(b"JSON")
        f.write(json_padded)
        f.write(struct.pack("<I", len(binary_padded)))
        f.write(b"BIN\x00")
        f.write(binary_padded)
    return True


def emit_all(out_root: Path) -> dict[str, str]:
    """Convert every monster .chr to a .glb under out/models/.
    Returns a {monster_id: relative-glb-path} map for the viewer."""
    monster_root = out_root / "DATA" / "chr" / "monster"
    glb_root = out_root / "models"
    glb_root.mkdir(exist_ok=True)
    result: dict[str, str] = {}

    for d in sorted(monster_root.iterdir()):
        if not d.is_dir():
            continue
        chr_path = d / f"{d.name}.chr"
        if not chr_path.exists():
            continue
        try:
            tex_name = ""
            try:
                root = parse_chr(chr_path)
                from .chr_format import collect_meshes
                meshes = collect_meshes(root)
                if meshes:
                    meshes.sort(key=lambda fm: -(len(fm[1].verts) // 32))
                    _, mesh = meshes[0]
                    if mesh.materials and mesh.materials[0].texture:
                        tex_name = mesh.materials[0].texture
            except Exception:
                pass
            tex_rel = _resolve_texture(d, tex_name) if tex_name else None
            tex_path = (d / tex_rel) if tex_rel else None
            glb_path = glb_root / f"{d.name}.glb"
            if write_glb(chr_path, glb_path, tex_path):
                result[d.name] = f"models/{d.name}.glb"
        except Exception as e:
            print(f"  ! {d.name}: {type(e).__name__}: {e}")
    return result


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[2] / "out")
    args = p.parse_args()
    emit_all(args.out)
