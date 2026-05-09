"""Emit minimal .glb (binary glTF 2.0) for each monster .chr.

Walks the full scene graph: every Frame becomes a glTF node, every
mesh-bearing Frame gets a glTF mesh attached.  The Frame's 4x4
transform is preserved as a node matrix so body / head / arms / weapon
all sit in the right place.

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

from .chr_format import Frame, Mesh, parse_chr


def _resolve_texture(monster_dir: Path, tex_name: str) -> str | None:
    """The .chr stores textures as .bmp filenames; we have .png versions
    of those textures from the G32 → PNG extraction.  Try a few common
    name variants (M_xxxx.png / M_xxxx_lower.png / variant suffixes)."""
    if not tex_name:
        return None
    base = tex_name.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
    stem = base.rsplit(".", 1)[0]
    for cand in (f"{stem}.png", f"{stem.lower()}.png", f"{stem.upper()}.png"):
        if (monster_dir / cand).exists():
            return cand
    for p in monster_dir.glob("*.png"):
        if stem.lower() in p.name.lower():
            return p.name
    pngs = sorted(monster_dir.glob("*.png"))
    return pngs[0].name if pngs else None


def _pad4(b: bytes) -> bytes:
    pad = (-len(b)) % 4
    return b + b"\x00" * pad


def _flatten_meshes(root: Frame) -> list[tuple[Mesh, tuple[float, ...]]]:
    """Walk the scene graph multiplying transforms top-down. Return
    (mesh, world_matrix) for every mesh-bearing Frame."""
    out: list[tuple[Mesh, tuple[float, ...]]] = []

    def walk(f: Frame, parent: tuple[float, ...]) -> None:
        world = _mat_mul(parent, f.transform)
        if f.mesh is not None and len(f.mesh.verts) >= 32:
            out.append((f.mesh, world))
        for c in f.children:
            walk(c, world)

    walk(root, _IDENTITY)
    return out


_IDENTITY = (
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
)


def _mat_mul(a: tuple[float, ...], b: tuple[float, ...]) -> tuple[float, ...]:
    # row-major 4x4 multiply
    r = [0.0] * 16
    for i in range(4):
        for j in range(4):
            s = 0.0
            for k in range(4):
                s += a[i * 4 + k] * b[k * 4 + j]
            r[i * 4 + j] = s
    return tuple(r)


def _mat_xform_point(m: tuple[float, ...], p: tuple[float, float, float]) -> tuple[float, float, float]:
    # row-major matrix * (px, py, pz, 1).  Falcom uses row-vector convention:
    # the translation lives in row 4 (m[12..15]), so we compute
    # p' = (px*m[0] + py*m[4] + pz*m[8] + m[12], …).
    px, py, pz = p
    x = px * m[0] + py * m[4] + pz * m[8]  + m[12]
    y = px * m[1] + py * m[5] + pz * m[9]  + m[13]
    z = px * m[2] + py * m[6] + pz * m[10] + m[14]
    return x, y, z


def _mat_xform_vec(m: tuple[float, ...], v: tuple[float, float, float]) -> tuple[float, float, float]:
    vx, vy, vz = v
    x = vx * m[0] + vy * m[4] + vz * m[8]
    y = vx * m[1] + vy * m[5] + vz * m[9]
    z = vx * m[2] + vy * m[6] + vz * m[10]
    return x, y, z


def _mat_inverse_affine(m: tuple[float, ...]) -> tuple[float, ...]:
    """Invert a 4x4 row-major *row-vector* affine matrix (top-left 3x3
    is the rotation/scale, last row is translation, last column is
    [0,0,0,1]).  We assume rotation-only / orthonormal in the 3x3
    block — true for bind-pose bone transforms in this format."""
    # Transpose the 3x3 (which is the inverse of a rotation)
    r = [
        m[0], m[4], m[8],  0.0,
        m[1], m[5], m[9],  0.0,
        m[2], m[6], m[10], 0.0,
        0.0,  0.0,  0.0,   1.0,
    ]
    # Inverse translation = -translation * inverse rotation
    tx, ty, tz = m[12], m[13], m[14]
    r[12] = -(tx * r[0] + ty * r[4] + tz * r[8])
    r[13] = -(tx * r[1] + ty * r[5] + tz * r[9])
    r[14] = -(tx * r[2] + ty * r[6] + tz * r[10])
    return tuple(r)


def _bake_skinning(mesh: Mesh) -> bytes:
    """Apply per-vertex bone weights to produce world-bind-pose vertices.

    The .chr stores vertices in each bone's local bind-pose frame; the
    bone's 4x4 matrix is the *inverse bind* transform (world → bone
    local).  We invert it to get the world-bind transform and apply
    weighted to each influencing vertex.
    """
    if not mesh.bones:
        return mesh.verts

    vert_count = len(mesh.verts) // 32
    # Per-vertex (bone_index, weight) lists
    influences: list[list[tuple[int, float]]] = [[] for _ in range(vert_count)]
    for bi, bone in enumerate(mesh.bones):
        for vi, w in zip(bone.weights_idx, bone.weights_val):
            if 0 <= vi < vert_count and w > 0.0:
                influences[vi].append((bi, w))

    # Pre-invert each bone matrix once.
    inv_bones = [_mat_inverse_affine(b.matrix) for b in mesh.bones]

    out = bytearray(len(mesh.verts))
    bones = mesh.bones
    for i in range(vert_count):
        o = i * 32
        px, py, pz = struct.unpack_from("<3f", mesh.verts, o)
        nx, ny, nz = struct.unpack_from("<3f", mesh.verts, o + 12)
        u, v = struct.unpack_from("<2f", mesh.verts, o + 24)

        infl = influences[i]
        if not infl:
            wp = (px, py, pz)
            wn = (nx, ny, nz)
        else:
            total_w = sum(w for _, w in infl)
            if total_w <= 0:
                wp = (px, py, pz)
                wn = (nx, ny, nz)
            else:
                ax = ay = az = 0.0
                anx = any_ = anz = 0.0
                for bi, w in infl:
                    bm = inv_bones[bi]
                    wpx, wpy, wpz = _mat_xform_point(bm, (px, py, pz))
                    wnx, wny, wnz = _mat_xform_vec(bm, (nx, ny, nz))
                    nw = w / total_w
                    ax += wpx * nw; ay += wpy * nw; az += wpz * nw
                    anx += wnx * nw; any_ += wny * nw; anz += wnz * nw
                wp = (ax, ay, az)
                wn = (anx, any_, anz)

        struct.pack_into("<3f", out, o, *wp)
        struct.pack_into("<3f", out, o + 12, *wn)
        struct.pack_into("<2f", out, o + 24, u, v)
    return bytes(out)


def _row_major_to_column_major(m: tuple[float, ...]) -> list[float]:
    """glTF expects column-major matrices."""
    return [
        m[0],  m[4],  m[8],  m[12],
        m[1],  m[5],  m[9],  m[13],
        m[2],  m[6],  m[10], m[14],
        m[3],  m[7],  m[11], m[15],
    ]


def write_glb(chr_path: Path, glb_path: Path, texture_path: Path | None) -> bool:
    """Convert one monster .chr to a .glb at ``glb_path``.  Returns True
    on success, False if the chr has no usable mesh."""
    root = parse_chr(chr_path)
    items = _flatten_meshes(root)
    if not items:
        return False

    # Build per-mesh vertex/index streams; combine into one buffer.
    # Each mesh becomes one glTF mesh primitive with its own position/
    # normal/uv/index accessors and a node carrying its world matrix.
    pos_buf = bytearray()
    nrm_buf = bytearray()
    uv_buf = bytearray()
    idx_buf = bytearray()

    pmin = [float("inf")] * 3
    pmax = [float("-inf")] * 3

    primitives_meta: list[dict] = []
    for mesh, _world in items:
        vert_count = len(mesh.verts) // 32
        idx_count = len(mesh.indices) // 2

        # Emit raw vertices.  In bind pose the engine's mesh stores
        # vertices already in the correct world-bind position; trying
        # to "bake" the bone matrices made things worse, so we leave
        # them alone and accept some bind-pose offsets in low-poly
        # rigs as a known limitation.
        pos_off = len(pos_buf)
        nrm_off = len(nrm_buf)
        uv_off = len(uv_buf)
        idx_off = len(idx_buf)

        local_pmin = [float("inf")] * 3
        local_pmax = [float("-inf")] * 3
        for i in range(vert_count):
            o = i * 32
            px, py, pz = struct.unpack_from("<3f", mesh.verts, o)
            nx, ny, nz = struct.unpack_from("<3f", mesh.verts, o + 12)
            u, v = struct.unpack_from("<2f", mesh.verts, o + 24)
            pos_buf += struct.pack("<3f", px, py, pz)
            nrm_buf += struct.pack("<3f", nx, ny, nz)
            uv_buf += struct.pack("<2f", u, v)
            for c, val in enumerate((px, py, pz)):
                if val < local_pmin[c]: local_pmin[c] = val
                if val > local_pmax[c]: local_pmax[c] = val
                if val < pmin[c]: pmin[c] = val
                if val > pmax[c]: pmax[c] = val
        idx_buf += bytes(mesh.indices)
        # Pad to 4-byte boundary inside idx_buf so subsequent mesh
        # u16 indices stay aligned for buffer-view byteOffset math.
        while len(idx_buf) % 4:
            idx_buf += b"\x00"

        primitives_meta.append({
            "vert_count": vert_count,
            "idx_count": idx_count,
            "pos_off": pos_off,
            "nrm_off": nrm_off,
            "uv_off": uv_off,
            "idx_off": idx_off,
            "min": local_pmin if local_pmin[0] != float("inf") else [0.0, 0.0, 0.0],
            "max": local_pmax if local_pmax[0] != float("-inf") else [0.0, 0.0, 0.0],
        })

    # Texture
    has_tex = texture_path is not None and texture_path.exists()
    image_data = texture_path.read_bytes() if has_tex else None

    # Layout binary: positions block, normals block, uvs block, indices block, [image]
    parts = [bytes(pos_buf), bytes(nrm_buf), bytes(uv_buf), bytes(idx_buf)]
    if image_data is not None:
        parts.append(image_data)
    binary = b""
    bv_offsets: list[tuple[int, int]] = []
    for p in parts:
        bv_offsets.append((len(binary), len(p)))
        binary += _pad4(p)

    POS_BV, NRM_BV, UV_BV, IDX_BV = 0, 1, 2, 3
    buffer_views = [
        {"buffer": 0, "byteOffset": bv_offsets[POS_BV][0], "byteLength": bv_offsets[POS_BV][1], "byteStride": 12, "target": 34962},
        {"buffer": 0, "byteOffset": bv_offsets[NRM_BV][0], "byteLength": bv_offsets[NRM_BV][1], "byteStride": 12, "target": 34962},
        {"buffer": 0, "byteOffset": bv_offsets[UV_BV][0], "byteLength": bv_offsets[UV_BV][1], "byteStride": 8, "target": 34962},
        {"buffer": 0, "byteOffset": bv_offsets[IDX_BV][0], "byteLength": bv_offsets[IDX_BV][1], "target": 34963},
    ]
    if image_data is not None:
        buffer_views.append({
            "buffer": 0,
            "byteOffset": bv_offsets[4][0],
            "byteLength": bv_offsets[4][1],
        })

    # Per-primitive accessors
    accessors: list[dict] = []
    primitives: list[dict] = []
    for meta in primitives_meta:
        pos_acc = len(accessors)
        accessors.append({
            "bufferView": POS_BV,
            "byteOffset": meta["pos_off"],
            "componentType": 5126,
            "count": meta["vert_count"],
            "type": "VEC3",
            "min": meta["min"],
            "max": meta["max"],
        })
        nrm_acc = len(accessors)
        accessors.append({
            "bufferView": NRM_BV,
            "byteOffset": meta["nrm_off"],
            "componentType": 5126,
            "count": meta["vert_count"],
            "type": "VEC3",
        })
        uv_acc = len(accessors)
        accessors.append({
            "bufferView": UV_BV,
            "byteOffset": meta["uv_off"],
            "componentType": 5126,
            "count": meta["vert_count"],
            "type": "VEC2",
        })
        idx_acc = len(accessors)
        accessors.append({
            "bufferView": IDX_BV,
            "byteOffset": meta["idx_off"],
            "componentType": 5123,  # u16
            "count": meta["idx_count"],
            "type": "SCALAR",
        })
        primitives.append({
            "attributes": {"POSITION": pos_acc, "NORMAL": nrm_acc, "TEXCOORD_0": uv_acc},
            "indices": idx_acc,
            "material": 0,
        })

    # One mesh containing all primitives, one node per mesh-bearing frame.
    # We assign one node per primitive so each mesh keeps its own world
    # transform. (glTF allows multiple nodes referencing one mesh, but we
    # take the simple route and split.)
    nodes: list[dict] = []
    children: list[int] = []
    meshes: list[dict] = []
    for i, (_mesh, world) in enumerate(items):
        mesh_idx = len(meshes)
        meshes.append({
            "name": f"prim_{i}",
            "primitives": [primitives[i]],
        })
        node = {
            "name": f"frame_{i}",
            "mesh": mesh_idx,
        }
        # Only emit a matrix if it's not identity (saves bytes in the JSON)
        identity_world = world == (
            1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0,
        )
        if not identity_world:
            node["matrix"] = _row_major_to_column_major(world)
        nodes.append(node)
        children.append(len(nodes) - 1)

    # Single root node parenting all mesh nodes
    root_idx = len(nodes)
    nodes.append({"name": chr_path.stem, "children": children})

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
        "scenes": [{"nodes": [root_idx]}],
        "nodes": nodes,
        "meshes": meshes,
        "buffers": [{"byteLength": len(binary)}],
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
    json_padded = json_text + b" " * ((-(len(json_text)) % 4))
    binary_padded = binary  # already 4-byte aligned by _pad4 calls above

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
                items = _flatten_meshes(root)
                # Use the texture from the first non-empty material we see.
                for mesh, _ in items:
                    for mat in mesh.materials:
                        if mat.texture:
                            tex_name = mat.texture
                            break
                    if tex_name:
                        break
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
