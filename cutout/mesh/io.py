"""Mesh loading for product-fragment images (STL / OBJ / PLY / GLB / STEP)."""
from __future__ import annotations

from pathlib import Path

MESH_EXTS = {".stl", ".obj", ".ply", ".glb", ".gltf", ".step", ".stp", ".igs", ".iges"}
TRIMESH_EXTS = {".stl", ".obj", ".ply", ".glb", ".gltf"}

#: Fusion's native project files cannot be parsed outside Fusion; the
#: documented workaround isExport ("File -> Export -> .STEP/.STL").
FUSION_EXTS = {".f3d", ".f3z"}


def _require_trimesh():
    try:
        import trimesh  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(
            "3D Model loading needs the `trimesh` package:  pip install trimesh"
        ) from exc
    return trimesh


def load_mesh(path: str | Path):
    """Load a 3D model into a trimesh.Scene with a single square mesh.

    STEP/IGES support requires the optional `cadquery-ocp` extra:
      pip install "deepvertex-cutout-studio[step]"
    """
    p = Path(path).expanduser()
    if not p.is_file():
        raise FileNotFoundError(f"no such file: {p}")
    suffix = p.suffix.lower()

    if suffix in FUSION_EXTS:
        raise RuntimeError(
            f"Fusion native files ({', '.join(sorted(FUSION_EXTS))}) can only be read "
            "inside Autodesk Fusion. Export the design first:\n"
            "  Fusion: File -> Export -> type STEP (.stp) or STL\n"
            "then use that file here (STEP keeps exact geometry, STL is a mesh)."
        )

    if suffix in {".step", ".stp"}:
        return _load_step(p)
    if suffix in {".igs", ".iges"}:
        raise RuntimeError("STEP is supported; IGES is not. Export .STEP instead.")

    trimesh = _require_trimesh()
    if suffix not in TRIMESH_EXTS:
        raise RuntimeError(
            f"unsupported 3D format {suffix!r}; supported: STL, OBJ, PLY, GLB/GLTF, STEP"
        )
    scene = trimesh.load(str(p), force="scene", process=True)
    return _as_scene(scene, name=p.stem)


def _load_step(p: Path):
    # geometry via the cadquery/OpenCASCADE bindings (optional extra `[step]`)
    try:
        import cadquery  # noqa: F401 - availability probe
    except ImportError as exc:
        raise RuntimeError(
            "STEP files need the OpenCASCADE bindings (heavy, optional):\n"
            '  pip install "deepvertex-cutout-studio[step]"\n'
            "If you cannot install it, re-export the model as STL / OBJ from your\n"
            "CAD tool (Fusion: File -> Export -> STL) — those load everywhere."
        ) from exc
    return _load_step_cadquery(p)


def attach_vertex_ao(mesh, rays_per_vertex: int = 64):
    """Compute hemisphere-traced ambient occlusion per vertex (bvh-free).

    Classic darkening-for-concavity: each vertex shoots outward rays; blocked
    portions darken it. blend factor lands in ``mesh.ao_array`` (0=closed
    cavity, 1=open). The renderer multiplies the fragment colour by it.
    """
    import numpy as np

    if getattr(mesh, "ao_array", None) is not None:
        return mesh
    import trimesh

    verts = np.asarray(mesh.vertices, dtype=np.float64)
    nv = len(verts)
    nbuf = np.asarray(mesh.vertex_normals, dtype=np.float64)
    rng = np.random.default_rng(11)
    inter = trimesh.ray.ray_triangle.RayMeshIntersector(mesh)
    origin_stack, dir_stack, owner = [], [], []
    for i in range(nv):
        d = rng.normal(size=(rays_per_vertex, 3))
        d /= np.linalg.norm(d, axis=1, keepdims=True)
        # keep the hemisphere facing along the vertex normal
        keep = d @ nbuf[i] > 0.0
        d = d[keep]
        if not len(d):
            continue
        o = np.repeat(verts[i : i + 1] + nbuf[i : i + 1] * 1e-4, len(d), axis=0)
        origin_stack.append(o)
        dir_stack.append(d)
        owner.append(np.full(len(d), i, dtype=np.int64))
    if not owner:
        mesh.ao_array = np.ones(nv, dtype=np.float32)
        return mesh
    origins = np.concatenate(origin_stack)
    dirs = np.concatenate(dir_stack)
    owner = np.concatenate(owner)
    # mark occlusion: any hit closer than a generous max range
    hit_any = inter.intersects_any(origins, dirs)
    blocked = np.zeros(nv, dtype=np.float32)
    np.add.at(blocked, owner[hit_any], 1.0)
    sent = np.zeros(nv, dtype=np.float32)
    np.add.at(sent, owner, 1.0)
    ao = 1.0 - np.divide(blocked, np.maximum(sent, 1e-6))
    ao = 0.25 + 0.75 * ao  # renormalise so open hemispheres stay readable
    mesh.ao_array = np.clip(ao, 0.0, 1.0).astype(np.float32)
    return mesh


def _load_step_cadquery(p: Path):  # pragma: no cover - needs heavy optional deps
    import logging

    import cadquery as cq
    import numpy as np
    import trimesh
    logging.getLogger(__name__).info("tessellating %s via OpenCASCADE ...", p.name)
    try:
        shape = cq.importers.importStep(str(p))
    except Exception as exc:
        raise RuntimeError(f"OpenCASCADE failed to read {p.name}: {exc}") from exc

    solids = shape.solids().vals() or [shape.val()]
    tolerance = 0.3 * max(
        max(s.BoundingBox().xlen, s.BoundingBox().ylen, s.BoundingBox().zlen)
        for s in solids
    ) / 256.0
    parts = []
    for s in solids:
        verts, faces = s.tessellate(tolerance)
        if not faces:
            continue
        parts.append(trimesh.Trimesh(
            vertices=np.array([(v.x, v.y, v.z) for v in verts]),
            faces=np.array(faces),
            process=False,
        ))
    if not parts:
        raise RuntimeError(f"no triangulated faces found in {p.name}")
    return _as_scene(
        trimesh.util.concatenate(parts) if len(parts) > 1 else parts[0], name=p.stem
    )


def _as_scene(scene, name: str):
    """Normalise trimesh output into (dumped mesh, camelCase-friendly name)."""
    trimesh = _require_trimesh()
    if isinstance(scene, trimesh.Scene):
        meshes = [g for g in scene.geometry.values() if isinstance(g, trimesh.Trimesh)]
        if not meshes:
            raise RuntimeError("the file contains no triangle geometry")
        mesh = trimesh.util.concatenate(meshes) if len(meshes) > 1 else meshes[0]
    else:
        mesh = scene
    if not isinstance(mesh, trimesh.Trimesh):
        raise RuntimeError("unsupported geometry type")
    mesh = mesh.copy()
    bounds = mesh.bounds
    mesh.apply_translation(-((bounds[0] + bounds[1]) / 2.0))  # centre on origin
    mesh.name = name
    return mesh


def normalize(mesh):
    """Center the mesh on the origin and grow the floor at y = 0.

    Returns a copy whose bounding box is centered at (0, ?, 0) and whose
    bottom rests on the ground plane y = 0 (studio-footing convention).
    """

    mesh = mesh.copy()
    bounds = mesh.bounds
    center = (bounds[0] + bounds[1]) / 2.0
    mesh.apply_translation([-center[0], -bounds[0][1], -center[2]])
    return mesh
