"""Build OCC AIS objects for the GUI (mesh triangulation, deviation colouring)."""

from __future__ import annotations

import numpy as np

from OCC.Core.Poly import Poly_Triangulation, Poly_Triangle
from OCC.Core.TColgp import TColgp_Array1OfPnt
from OCC.Core.Poly import Poly_Array1OfTriangle
from OCC.Core.AIS import AIS_Triangulation
from OCC.Core.TColStd import TColStd_Array1OfInteger
from OCC.Core.gp import gp_Pnt


def _triangulation(vertices: np.ndarray, faces: np.ndarray) -> Poly_Triangulation:
    nodes = TColgp_Array1OfPnt(1, len(vertices))
    for i, p in enumerate(vertices, start=1):
        nodes.SetValue(i, gp_Pnt(float(p[0]), float(p[1]), float(p[2])))
    tris = Poly_Array1OfTriangle(1, len(faces))
    for i, t in enumerate(faces, start=1):
        tris.SetValue(i, Poly_Triangle(int(t[0]) + 1, int(t[1]) + 1, int(t[2]) + 1))
    tri = Poly_Triangulation(nodes, tris)
    return tri


def _turbo(v: np.ndarray) -> np.ndarray:
    """Cheap blue->green->red colour ramp for v in [0,1]. Returns (N,3) 0..255."""
    v = np.clip(v, 0, 1)
    r = np.clip(1.5 - abs(2 * v - 1) * 2 + (v > 0.5) * 0, 0, 1)
    r = np.clip(2 * v, 0, 1)
    g = np.clip(1 - abs(v - 0.5) * 2, 0, 1)
    b = np.clip(2 * (0.5 - v), 0, 1)
    return (np.c_[r, g, b] * 255).astype(int)


def mesh_ais(vertices: np.ndarray, faces: np.ndarray,
             scalar: np.ndarray | None = None, vmax: float | None = None):
    """AIS_Triangulation; if `scalar` (per-vertex) given, colour by it."""
    tri = _triangulation(vertices, faces)
    ais = AIS_Triangulation(tri)
    if scalar is not None and len(scalar) == len(vertices):
        vmax = vmax or (float(np.percentile(scalar, 99)) or 1.0)
        cols = _turbo(scalar / vmax)
        arr = TColStd_Array1OfInteger(1, len(vertices))
        for i, (rr, gg, bb) in enumerate(cols, start=1):
            packed = (int(rr) << 16) | (int(gg) << 8) | int(bb)
            arr.SetValue(i, packed)
        try:
            ais.SetColors(arr)
        except Exception:
            pass
    return ais
