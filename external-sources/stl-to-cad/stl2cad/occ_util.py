"""Thin helpers over pythonocc-core (import isolation + version quirks)."""

from __future__ import annotations

import numpy as np

from OCC.Core.gp import (
    gp_Pnt, gp_Dir, gp_Vec, gp_Ax1, gp_Ax2, gp_Ax3, gp_Pln,
)
from OCC.Core.Geom import (
    Geom_Plane, Geom_CylindricalSurface, Geom_ConicalSurface,
    Geom_SphericalSurface, Geom_ToroidalSurface,
)
from OCC.Core.TColgp import TColgp_Array1OfPnt
from OCC.Core.GeomAPI import GeomAPI_PointsToBSpline
from OCC.Core.GProp import GProp_GProps
from OCC.Core.BRepGProp import brepgprop
from OCC.Core.BRepCheck import BRepCheck_Analyzer
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopAbs import TopAbs_SOLID, TopAbs_SHELL, TopAbs_FACE
from OCC.Core.TopoDS import topods


def pnt(p) -> gp_Pnt:
    return gp_Pnt(float(p[0]), float(p[1]), float(p[2]))


def vec_dir(v) -> gp_Dir:
    v = np.asarray(v, float)
    v = v / (np.linalg.norm(v) or 1.0)
    return gp_Dir(float(v[0]), float(v[1]), float(v[2]))


def surface_from_fit(fit):
    """Build an unbounded Geom_Surface from a PrimitiveFit. Returns handle or None."""
    p = fit.params
    k = fit.kind
    try:
        if k == "plane":
            return Geom_Plane(pnt(p["point"]), vec_dir(p["normal"]))
        if k == "cylinder":
            ax = gp_Ax3(pnt(p["point"]), vec_dir(p["axis"]))
            return Geom_CylindricalSurface(ax, float(p["radius"]))
        if k == "sphere":
            ax = gp_Ax3(pnt(p["center"]), gp_Dir(0, 0, 1))
            return Geom_SphericalSurface(ax, float(p["radius"]))
        if k == "cone":
            ax = gp_Ax3(pnt(p["apex"]), vec_dir(p["axis"]))
            return Geom_ConicalSurface(ax, float(p["half_angle"]), 0.0)
        if k == "torus":
            ax = gp_Ax3(pnt(p["center"]), vec_dir(p["axis"]))
            return Geom_ToroidalSurface(ax, float(p["major_radius"]), float(p["minor_radius"]))
    except Exception:
        return None
    return None


def bspline_from_points(points: np.ndarray):
    """Approximating B-spline curve through an ordered point list."""
    pts = np.asarray(points, float)
    arr = TColgp_Array1OfPnt(1, len(pts))
    for i, pp in enumerate(pts, start=1):
        arr.SetValue(i, pnt(pp))
    return GeomAPI_PointsToBSpline(arr).Curve()


def volume(shape) -> float:
    g = GProp_GProps()
    brepgprop.VolumeProperties(shape, g)
    return float(g.Mass())


def is_valid(shape) -> bool:
    try:
        return bool(BRepCheck_Analyzer(shape).IsValid())
    except Exception:
        return False


def count_solids(shape) -> int:
    n = 0
    ex = TopExp_Explorer(shape, TopAbs_SOLID)
    while ex.More():
        n += 1
        ex.Next()
    return n


def iter_faces(shape):
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        yield topods.Face(ex.Current())
        ex.Next()


def face_kind(face) -> str:
    from OCC.Core.BRepAdaptor import BRepAdaptor_Surface
    from OCC.Core.GeomAbs import (
        GeomAbs_Plane, GeomAbs_Cylinder, GeomAbs_Cone, GeomAbs_Sphere,
        GeomAbs_Torus, GeomAbs_BSplineSurface, GeomAbs_BezierSurface,
        GeomAbs_SurfaceOfRevolution, GeomAbs_SurfaceOfExtrusion,
    )
    try:
        t = BRepAdaptor_Surface(face).GetType()
    except Exception:
        return "other"
    return {
        GeomAbs_Plane: "plane",
        GeomAbs_Cylinder: "cylinder",
        GeomAbs_Cone: "cone",
        GeomAbs_Sphere: "sphere",
        GeomAbs_Torus: "torus",
        GeomAbs_BSplineSurface: "bspline",
        GeomAbs_BezierSurface: "bezier",
        GeomAbs_SurfaceOfRevolution: "revolution",
        GeomAbs_SurfaceOfExtrusion: "extrusion",
    }.get(t, "other")


def face_kind_histogram(shape) -> dict[str, int]:
    hist: dict[str, int] = {}
    for f in iter_faces(shape):
        k = face_kind(f)
        hist[k] = hist.get(k, 0) + 1
    return hist
