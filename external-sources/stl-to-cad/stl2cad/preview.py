"""Tessellate results into glTF/GLB for the web viewer."""

from __future__ import annotations

import numpy as np
import trimesh

from OCC.Core.BRepMesh import BRepMesh_IncrementalMesh
from OCC.Core.TopLoc import TopLoc_Location
from OCC.Core.BRep import BRep_Tool
from OCC.Core.TopAbs import TopAbs_FACE
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopoDS import topods

from .occ_util import face_kind

# colour per analytic surface type (RGBA 0-255)
KIND_COLOR = {
    "plane":      (154, 166, 184, 255),
    "cylinder":   ( 76, 154, 255, 255),
    "cone":       ( 62, 207, 142, 255),
    "sphere":     (255, 180,  84, 255),
    "torus":      (197, 138, 249, 255),
    "bspline":    (255, 107, 107, 255),
    "bezier":     (255, 107, 107, 255),
    "revolution": (255, 150, 200, 255),
    "extrusion":  (255, 150, 200, 255),
    "other":      (120, 128, 140, 255),
}


def _mesh_shape(shape, lin_defl: float | None = None, ang_defl: float = 0.7):
    """Tessellate ``shape`` in place. Uses relative deflection so busy features
    (many small holes, trimmed B-splines) don't blow up the triangle count."""
    from OCC.Core.Bnd import Bnd_Box
    from OCC.Core.BRepBndLib import brepbndlib
    if lin_defl is None:
        box = Bnd_Box()
        brepbndlib.Add(shape, box)
        try:
            diag = box.CornerMin().Distance(box.CornerMax())
        except Exception:
            diag = 100.0
        lin_defl = max(0.15, diag / 350.0)
    BRepMesh_IncrementalMesh(shape, lin_defl, False, ang_defl, True)
    return lin_defl


def shape_to_trimesh(shape, lin_defl: float | None = None, ang_defl: float = 0.7,
                     colour_by_kind: bool = True):
    """Mesh an OCC shape -> single Trimesh (all faces concatenated).

    When ``colour_by_kind`` the returned mesh carries per-face colours keyed to
    the analytic surface type of the B-rep face each triangle came from.
    """
    _mesh_shape(shape, lin_defl, ang_defl)
    all_v: list[np.ndarray] = []
    all_f: list[np.ndarray] = []
    all_c: list[np.ndarray] = []
    kinds_seen: set[str] = set()
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        face = topods.Face(ex.Current())
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation(face, loc)
        ex.Next()
        if tri is None:
            continue
        trsf = loc.Transformation()
        n = tri.NbNodes()
        verts = np.empty((n, 3))
        for i in range(1, n + 1):
            p = tri.Node(i).Transformed(trsf)
            verts[i - 1] = (p.X(), p.Y(), p.Z())
        m = tri.NbTriangles()
        faces = np.empty((m, 3), dtype=np.int64)
        reversed_ = face.Orientation() == 1  # TopAbs_REVERSED
        for i in range(1, m + 1):
            a, b, c = tri.Triangle(i).Get()
            faces[i - 1] = (a - 1, c - 1, b - 1) if reversed_ else (a - 1, b - 1, c - 1)
        all_f.append(faces + sum(len(v) for v in all_v))
        all_v.append(verts)
        if colour_by_kind:
            k = face_kind(face)
            kinds_seen.add(k)
            col = KIND_COLOR.get(k, KIND_COLOR["other"])
            all_c.append(np.tile(col, (m, 1)))
    if not all_v:
        return trimesh.Trimesh()
    tm = trimesh.Trimesh(np.vstack(all_v), np.vstack(all_f), process=False)
    if colour_by_kind and all_c:
        tm.visual.face_colors = np.vstack(all_c).astype(np.uint8)
        tm.metadata["kinds"] = sorted(kinds_seen)
    return tm


def _ramp(t: np.ndarray) -> np.ndarray:
    """blue -> cyan -> green -> yellow -> red, t in [0,1] -> (N,4) uint8 RGBA."""
    t = np.clip(t, 0, 1)
    r = np.clip(np.minimum(4 * t - 1.5, -4 * t + 4.5), 0, 1)
    g = np.clip(np.minimum(4 * t - 0.5, -4 * t + 3.5), 0, 1)
    b = np.clip(np.minimum(4 * t + 0.5, -4 * t + 2.5), 0, 1)
    out = np.zeros((len(t), 4), dtype=np.uint8)
    out[:, 0] = (r * 255)
    out[:, 1] = (g * 255)
    out[:, 2] = (b * 255)
    out[:, 3] = 255
    return out


def mesh_with_deviation(src_mesh: trimesh.Trimesh, result_shape, vmax: float,
                        result_mesh: trimesh.Trimesh | None = None) -> trimesh.Trimesh:
    """Return the source mesh coloured by distance to the reconstructed solid.

    Pass ``result_mesh`` (an already-tessellated solid) to skip re-meshing.
    """
    m = trimesh.Trimesh(src_mesh.vertices.copy(), src_mesh.faces.copy(), process=False)
    try:
        res = result_mesh if result_mesh is not None else shape_to_trimesh(result_shape)
        if len(res.vertices) >= 3:
            from scipy.spatial import cKDTree
            d = cKDTree(res.vertices).query(m.vertices, workers=-1)[0]
            m.visual.vertex_colors = _ramp(d / max(vmax, 1e-6))
            m.metadata["dev_max"] = float(d.max())
    except Exception:
        pass
    return m


def to_glb(mesh: trimesh.Trimesh) -> bytes:
    if mesh is None or len(mesh.faces) == 0:
        mesh = trimesh.creation.box(extents=(1, 1, 1))
    # glTF viewers need vertex normals for lit materials
    try:
        _ = mesh.vertex_normals  # forces computation & caches
    except Exception:
        pass
    return trimesh.Scene([mesh]).export(file_type="glb")
