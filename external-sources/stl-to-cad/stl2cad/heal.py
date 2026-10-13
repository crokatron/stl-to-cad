"""Mesh healing and decimation.

Pipeline: weld -> remove junk -> repair non-manifold -> close holes ->
quadric-decimate (fast_simplification) -> close holes again -> coherent normals.
pymeshlab does the topological repair; fast_simplification does decimation.
"""

from __future__ import annotations

import numpy as np
import trimesh

from .config import HealConfig

try:
    import pymeshlab  # type: ignore
    _HAS_MESHLAB = True
except Exception:  # pragma: no cover
    _HAS_MESHLAB = False

try:
    import fast_simplification as _fs  # type: ignore
    _HAS_FS = True
except Exception:  # pragma: no cover
    _HAS_FS = False


def _ms_from(mesh: trimesh.Trimesh):
    ms = pymeshlab.MeshSet()
    ms.add_mesh(pymeshlab.Mesh(
        vertex_matrix=np.asarray(mesh.vertices, dtype=np.float64),
        face_matrix=np.asarray(mesh.faces, dtype=np.int32)), "m")
    return ms


def _ms_to(ms) -> trimesh.Trimesh:
    m = ms.current_mesh()
    return trimesh.Trimesh(
        vertices=np.asarray(m.vertex_matrix(), dtype=np.float64),
        faces=np.asarray(m.face_matrix(), dtype=np.int64),
        process=False)


def _repair(ms, cfg: HealConfig, diag: float):
    def run(name, **kw):
        try:
            ms.apply_filter(name, **kw)
            return True
        except Exception:
            return False

    run("meshing_remove_duplicate_vertices")
    run("meshing_remove_null_faces")
    run("meshing_remove_duplicate_faces")
    # weld vertices within a small absolute distance
    thr = max(cfg.merge_distance, diag * 1e-5)
    try:
        ms.apply_filter("meshing_merge_close_vertices",
                        threshold=pymeshlab.PureValue(thr)
                        if hasattr(pymeshlab, "PureValue") else thr)
    except Exception:
        run("meshing_merge_close_vertices")
    run("meshing_remove_unreferenced_vertices")
    run("meshing_repair_non_manifold_edges")
    run("meshing_repair_non_manifold_vertices")
    if cfg.max_hole_edges > 0:
        run("meshing_close_holes", maxholesize=int(cfg.max_hole_edges),
            newfaceselected=False, selfintersection=False)


def heal_mesh(mesh: trimesh.Trimesh, cfg: HealConfig) -> trimesh.Trimesh:
    diag = float(np.linalg.norm(mesh.bounds[1] - mesh.bounds[0])) or 1.0
    m = mesh

    # Decimate very large meshes FIRST: pymeshlab hole-closing / non-manifold
    # repair is O(faces) with a large constant and can hang on million-triangle
    # inputs (dense grilles especially).
    pre_cap = max(4 * (cfg.target_faces or 60_000), 250_000)
    if _HAS_FS and len(m.faces) > pre_cap:
        try:
            v, f = _fs.simplify(np.asarray(m.vertices, np.float64),
                                np.asarray(m.faces, np.int64),
                                target_count=int(pre_cap), agg=8)
            if len(f) < len(m.faces):
                m = trimesh.Trimesh(v, f, process=False)
        except Exception:
            pass

    if _HAS_MESHLAB and len(m.faces) <= 400_000:
        try:
            ms = _ms_from(m)
            _repair(ms, cfg, diag)
            m = _ms_to(ms)
        except Exception:
            pass

    n = len(m.faces)
    if (_HAS_FS and cfg.target_faces and n > cfg.target_faces
            and n > cfg.decimate_skip_below):
        try:
            verts = np.asarray(m.vertices, np.float64)
            faces = np.asarray(m.faces, np.int64)
            reduction = 1.0 - min(0.98, cfg.target_faces / len(faces))
            v, f = _fs.simplify(verts, faces, target_reduction=reduction,
                                lossless=False, agg=7)
            if len(f) > cfg.target_faces * 1.6:
                v, f = _fs.simplify(v, f,
                                    target_count=int(cfg.target_faces),
                                    lossless=False, agg=9)
            m = trimesh.Trimesh(v, f, process=False)
            if _HAS_MESHLAB:
                ms = _ms_from(m)
                for name, kw in (
                    ("meshing_remove_duplicate_vertices", {}),
                    ("meshing_repair_non_manifold_edges", {}),
                    ("meshing_close_holes",
                     {"maxholesize": int(max(cfg.max_hole_edges, 200))}),
                ):
                    try:
                        ms.apply_filter(name, **kw)
                    except Exception:
                        pass
                m = _ms_to(ms)
        except Exception:
            pass

    # Hard cap: dense meshes (grilles) resist topology-preserving decimation and
    # would make downstream OCC work hang. Force the count down, accepting
    # quality loss; hole-filling is deliberately NOT attempted here.
    hard = int((cfg.target_faces or 40_000) * 2.0)
    if _HAS_FS and len(m.faces) > hard:
        try:
            v, f = _fs.simplify(np.asarray(m.vertices, np.float64),
                                np.asarray(m.faces, np.int64),
                                target_count=hard, agg=9)
            if len(f) < len(m.faces):
                m = trimesh.Trimesh(v, f, process=False)
        except Exception:
            pass

    m.merge_vertices()
    m.update_faces(m.nondegenerate_faces())
    m.update_faces(m.unique_faces())
    m.remove_unreferenced_vertices()
    trimesh.repair.fix_normals(m)
    if not m.is_watertight:
        trimesh.repair.fill_holes(m)
        trimesh.repair.fix_normals(m)
    return m
