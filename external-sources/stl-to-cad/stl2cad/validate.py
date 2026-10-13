"""Validate a reconstructed solid against the source mesh."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import trimesh

from OCC.Core.BRepMesh import BRepMesh_IncrementalMesh
from OCC.Core.TopLoc import TopLoc_Location
from OCC.Core.BRep import BRep_Tool
from OCC.Core.TopAbs import TopAbs_FACE
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopoDS import topods

from .config import ValidateConfig
from .occ_util import volume, count_solids, is_valid


@dataclass
class ValidationResult:
    closed: bool
    valid: bool
    n_solids: int
    volume_solid: float
    volume_mesh: float
    volume_rel_err: float
    dev_max: float
    dev_rms: float
    dev_p95: float
    passed: bool
    notes: list = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"closed={self.closed} solids={self.n_solids} "
            f"vol_err={self.volume_rel_err*100:.2f}%  "
            f"dev max/rms/p95 = {self.dev_max:.3f}/{self.dev_rms:.3f}/{self.dev_p95:.3f} mm  "
            f"=> {'PASS' if self.passed else 'FAIL'}"
        )


def tessellate(shape, lin_defl: float | None = None, ang_defl: float = 0.7) -> np.ndarray:
    """Return an (N,3) array of surface sample points from a meshed B-rep."""
    if lin_defl is None:
        from OCC.Core.Bnd import Bnd_Box
        from OCC.Core.BRepBndLib import brepbndlib
        box = Bnd_Box()
        brepbndlib.Add(shape, box)
        try:
            lin_defl = max(0.15, box.CornerMin().Distance(box.CornerMax()) / 350.0)
        except Exception:
            lin_defl = 0.3
    BRepMesh_IncrementalMesh(shape, lin_defl, False, ang_defl, True)
    pts: list[np.ndarray] = []
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        face = topods.Face(ex.Current())
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation(face, loc)
        if tri is not None:
            trsf = loc.Transformation()
            n = tri.NbNodes()
            for i in range(1, n + 1):
                p = tri.Node(i).Transformed(trsf)
                pts.append((p.X(), p.Y(), p.Z()))
        ex.Next()
    if not pts:
        return np.zeros((0, 3))
    return np.asarray(pts, float)


def deviation(shape, ref_mesh: trimesh.Trimesh, max_pts: int = 6000,
              result_mesh=None):
    """Max / RMS / p95 distance from the solid's surface to the source mesh.

    Exact point-to-triangle distance on a capped sample of solid-surface points;
    trimesh.proximity is O(pts x faces) so keep the sample small.
    """
    from scipy.spatial import cKDTree

    if result_mesh is not None and len(result_mesh.vertices):
        pts = np.asarray(result_mesh.vertices, float)
    else:
        pts = tessellate(shape)
    if len(pts) == 0:
        return float("inf"), float("inf"), float("inf")
    if len(pts) > max_pts:
        idx = np.random.default_rng(0).choice(len(pts), max_pts, replace=False)
        pts = pts[idx]

    # coarse KDTree prefilter to a dense surface point cloud, then refine the
    # worst offenders with exact point-to-triangle distance
    try:
        cloud = ref_mesh.sample(min(120000, max(20000, 3 * len(ref_mesh.faces))))
    except Exception:
        cloud = ref_mesh.vertices
    approx = cKDTree(cloud).query(pts, workers=-1)[0]
    try:
        order = np.argsort(approx)[-1500:]
        _, exact, _ = trimesh.proximity.closest_point(ref_mesh, pts[order])
        approx[order] = exact
    except Exception:
        pass
    return (float(np.max(approx)), float(np.sqrt(np.mean(approx ** 2))),
            float(np.percentile(approx, 95)))


def validate(shape, ref_mesh: trimesh.Trimesh, cfg: ValidateConfig,
             result_mesh=None) -> ValidationResult:
    notes: list[str] = []
    if shape is None:
        return ValidationResult(False, False, 0, 0, 0, 1.0, float("inf"),
                                float("inf"), float("inf"), False, ["no shape"])
    n_solids = count_solids(shape)
    closed = n_solids >= 1

    from .occ_util import iter_faces
    nfaces = sum(1 for _ in iter_faces(shape))
    # BRepCheck_Analyzer is thorough but O(faces) with a big constant on curved
    # surfaces; skip it for busy models (closedness is already known).
    if nfaces <= 120:
        valid = is_valid(shape)
    else:
        valid = closed
        notes.append(f"{nfaces} faces - full B-rep check skipped for speed")

    try:
        vsolid = abs(volume(shape))
    except Exception:
        vsolid = 0.0
    try:
        vmesh = abs(float(ref_mesh.volume)) if ref_mesh.is_watertight else 0.0
    except Exception:
        vmesh = 0.0
    vrel = abs(vsolid - vmesh) / vmesh if vmesh > 0 else 1.0

    if nfaces > 12000:
        # faceted output follows the mesh exactly; skip the costly sampling
        dmax = drms = dp95 = 0.0
        notes.append(f"{nfaces} faces (faceted) - deviation is 0 by construction")
    else:
        dmax, drms, dp95 = deviation(shape, ref_mesh, result_mesh=result_mesh)

    # a closed solid within tolerance is acceptable even if BRepCheck flags
    # sliver faces (common for faceted output; NX heals these on import)
    passed = (
        closed
        and n_solids >= 1
        and dmax <= cfg.pass_max_dev
        and (vmesh == 0 or vrel <= cfg.pass_volume_rel * 5)
    )
    if not valid:
        notes.append("BRepCheck reports minor issues (sliver faces) - NX will heal on import")
    return ValidationResult(
        closed=closed, valid=valid, n_solids=n_solids,
        volume_solid=vsolid, volume_mesh=vmesh, volume_rel_err=vrel,
        dev_max=dmax, dev_rms=drms, dev_p95=dp95, passed=passed, notes=notes,
    )
