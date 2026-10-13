"""Fit 3D curves to ordered polylines (segmentation arcs)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def rdp(points: np.ndarray, eps: float) -> np.ndarray:
    """Ramer-Douglas-Peucker simplification of an open polyline (Nx3)."""
    if len(points) < 3:
        return points
    start, end = points[0], points[-1]
    line = end - start
    ll = np.linalg.norm(line)
    if ll < 1e-12:
        d = np.linalg.norm(points - start, axis=1)
    else:
        d = np.linalg.norm(np.cross(points - start, line), axis=1) / ll
    idx = int(np.argmax(d))
    if d[idx] > eps:
        left = rdp(points[: idx + 1], eps)
        right = rdp(points[idx:], eps)
        return np.vstack([left[:-1], right])
    return np.vstack([start, end])


@dataclass
class CurveFit:
    kind: str            # line | circle | polyline
    params: dict
    max_dev: float


def fit_arc(points: np.ndarray, tol: float) -> CurveFit:
    """Classify a polyline as a straight line, circular arc, or generic polyline."""
    if len(points) < 2:
        return CurveFit("polyline", {"points": points}, 0.0)

    start, end = points[0], points[-1]
    line = end - start
    ll = np.linalg.norm(line)
    if ll > 1e-9:
        d = np.linalg.norm(np.cross(points - start, line), axis=1) / ll
        if float(np.max(d)) <= tol:
            return CurveFit("line", {"p0": start, "p1": end}, float(np.max(d)))

    circ = _fit_circle_3d(points)
    if circ is not None and circ.max_dev <= tol:
        return circ

    return CurveFit("polyline", {"points": points}, 0.0)


def _fit_circle_3d(points: np.ndarray):
    if len(points) < 3:
        return None
    c = points.mean(axis=0)
    u, s, vt = np.linalg.svd(points - c, full_matrices=False)
    normal = vt[2]
    e1, e2 = vt[0], vt[1]
    p2 = np.c_[(points - c) @ e1, (points - c) @ e2]
    A = np.c_[2 * p2, np.ones(len(p2))]
    b = np.sum(p2 ** 2, axis=1)
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    cen2 = sol[:2]
    r = np.sqrt(max(sol[2] + cen2 @ cen2, 1e-12))
    center = c + cen2[0] * e1 + cen2[1] * e2
    dev = np.abs(np.linalg.norm(points - center, axis=1) - r)
    # planarity check
    plane_dev = np.abs((points - c) @ normal)
    md = float(max(dev.max(), plane_dev.max()))
    return CurveFit(
        "circle",
        {"center": center, "normal": normal, "radius": float(r),
         "p_start": points[0], "p_end": points[-1]},
        md,
    )
