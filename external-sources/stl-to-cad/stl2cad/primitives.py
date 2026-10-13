"""Least-squares fitting of analytic primitives to point sets.

Every fitter takes an ``(N, 3)`` array of points (mm) and, optionally, an
``(N, 3)`` array of unit normals. It returns a :class:`PrimitiveFit` or ``None``.

``PrimitiveFit.deviations`` holds the signed/absolute distance of each input
point from the fitted surface, in mm.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from scipy.optimize import least_squares


# --------------------------------------------------------------------------- #
#  result container
# --------------------------------------------------------------------------- #
@dataclass
class PrimitiveFit:
    kind: str                       # plane | cylinder | cone | sphere | torus
    params: dict                    # geometry parameters (see per-kind docs)
    deviations: np.ndarray          # (N,) absolute distance to surface, mm
    dof: int                        # relative complexity for tie-breaking

    @property
    def max_dev(self) -> float:
        return float(np.max(self.deviations)) if len(self.deviations) else 0.0

    @property
    def rms_dev(self) -> float:
        return float(np.sqrt(np.mean(self.deviations ** 2))) if len(self.deviations) else 0.0

    def summary(self) -> str:
        return f"{self.kind}(max={self.max_dev:.3f} rms={self.rms_dev:.3f})"


_DOF = {"plane": 0, "cylinder": 1, "cone": 2, "sphere": 3, "torus": 4}


# --------------------------------------------------------------------------- #
#  helpers
# --------------------------------------------------------------------------- #
def _unit(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    n[n == 0] = 1.0
    return v / n


def _principal_axis_from_normals(normals: np.ndarray) -> np.ndarray:
    """Direction most orthogonal to all normals (cylinder/torus axis seed)."""
    c = normals.T @ normals
    w, v = np.linalg.eigh(c)
    return _unit(v[:, 0])          # eigenvector of smallest eigenvalue


def _basis_from_axis(axis: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    axis = _unit(axis)
    ref = np.array([1.0, 0.0, 0.0]) if abs(axis[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    u = _unit(np.cross(axis, ref))
    v = np.cross(axis, u)
    return u, v


# --------------------------------------------------------------------------- #
#  plane
# --------------------------------------------------------------------------- #
def fit_plane(points: np.ndarray, normals: Optional[np.ndarray] = None) -> Optional[PrimitiveFit]:
    if len(points) < 3:
        return None
    c = points.mean(axis=0)
    u, s, vt = np.linalg.svd(points - c, full_matrices=False)
    normal = _unit(vt[2])
    if normals is not None and np.dot(normal, normals.mean(axis=0)) < 0:
        normal = -normal
    dev = np.abs((points - c) @ normal)
    return PrimitiveFit("plane", {"point": c, "normal": normal}, dev, _DOF["plane"])


# --------------------------------------------------------------------------- #
#  sphere
# --------------------------------------------------------------------------- #
def fit_sphere(points: np.ndarray, normals: Optional[np.ndarray] = None) -> Optional[PrimitiveFit]:
    if len(points) < 4:
        return None
    A = np.c_[2 * points, np.ones(len(points))]
    b = np.sum(points ** 2, axis=1)
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    center = sol[:3]
    r2 = sol[3] + center @ center
    if r2 <= 0:
        return None
    radius = float(np.sqrt(r2))
    dev = np.abs(np.linalg.norm(points - center, axis=1) - radius)
    return PrimitiveFit("sphere", {"center": center, "radius": radius}, dev, _DOF["sphere"])


# --------------------------------------------------------------------------- #
#  cylinder
# --------------------------------------------------------------------------- #
def _circle_2d(pts2: np.ndarray) -> tuple[np.ndarray, float]:
    A = np.c_[2 * pts2, np.ones(len(pts2))]
    b = np.sum(pts2 ** 2, axis=1)
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    center = sol[:2]
    r = np.sqrt(max(sol[2] + center @ center, 1e-12))
    return center, float(r)


def fit_cylinder(points: np.ndarray, normals: Optional[np.ndarray] = None) -> Optional[PrimitiveFit]:
    if len(points) < 6:
        return None
    c = points.mean(axis=0)
    P = points - c

    if normals is not None and len(normals) == len(points):
        axis0 = _principal_axis_from_normals(normals)
    else:
        _, _, vt = np.linalg.svd(P, full_matrices=False)
        axis0 = vt[0]

    def residuals(x):
        axis = _unit(x[:3])
        u, v = _basis_from_axis(axis)
        proj = np.c_[P @ u, P @ v]
        cen = x[3:5]
        rad = x[5]
        return np.linalg.norm(proj - cen, axis=1) - rad

    u0, v0 = _basis_from_axis(axis0)
    proj0 = np.c_[P @ u0, P @ v0]
    cen0, r0 = _circle_2d(proj0)
    x0 = np.r_[axis0, cen0, r0]
    try:
        res = least_squares(residuals, x0, method="lm", max_nfev=400)
    except Exception:
        return None

    axis = _unit(res.x[:3])
    u, v = _basis_from_axis(axis)
    cen2d = res.x[3:5]
    radius = float(abs(res.x[5]))
    if radius <= 0 or radius > 1e6:
        return None
    center = c + cen2d[0] * u + cen2d[1] * v
    dev = np.abs(residuals(res.x))
    return PrimitiveFit(
        "cylinder",
        {"point": center, "axis": axis, "radius": radius},
        dev,
        _DOF["cylinder"],
    )


# --------------------------------------------------------------------------- #
#  cone
# --------------------------------------------------------------------------- #
def fit_cone(points: np.ndarray, normals: Optional[np.ndarray] = None) -> Optional[PrimitiveFit]:
    if len(points) < 8:
        return None
    c = points.mean(axis=0)
    P = points - c
    _, _, vt = np.linalg.svd(P, full_matrices=False)
    axis0 = vt[0]

    # seed apex offset and half-angle from a coarse cylinder-like projection
    u0, v0 = _basis_from_axis(axis0)
    t = P @ axis0
    rho = np.linalg.norm(np.c_[P @ u0, P @ v0], axis=1)
    # linear fit rho = a * t + b  -> half angle from slope
    a, b = np.polyfit(t, rho, 1)
    half_angle0 = np.arctan(a)
    if not np.isfinite(half_angle0) or abs(half_angle0) < 1e-4:
        return None
    apex_t0 = -b / a if abs(a) > 1e-9 else 0.0

    def residuals(x):
        axis = _unit(x[:3])
        apex = x[3:6]
        ha = x[6]
        d = P - (apex - c)
        L = np.linalg.norm(d, axis=1)
        L[L == 0] = 1e-9
        cos_t = (d @ axis) / L
        return L * (np.cos(ha) - np.abs(cos_t))

    apex0 = c + axis0 * apex_t0
    x0 = np.r_[axis0, apex0, abs(half_angle0)]
    try:
        res = least_squares(residuals, x0, method="lm", max_nfev=600)
    except Exception:
        return None
    ha = float(abs(res.x[6]))
    if ha <= 1e-3 or ha >= (np.pi / 2 - 1e-3):
        return None
    axis = _unit(res.x[:3])
    apex = res.x[3:6]
    dev = np.abs(residuals(res.x))
    return PrimitiveFit(
        "cone",
        {"apex": apex, "axis": axis, "half_angle": ha},
        dev,
        _DOF["cone"],
    )


# --------------------------------------------------------------------------- #
#  torus
# --------------------------------------------------------------------------- #
def fit_torus(points: np.ndarray, normals: Optional[np.ndarray] = None) -> Optional[PrimitiveFit]:
    if len(points) < 10:
        return None
    c = points.mean(axis=0)
    P = points - c
    if normals is not None and len(normals) == len(points):
        axis0 = _principal_axis_from_normals(normals)
    else:
        _, _, vt = np.linalg.svd(P, full_matrices=False)
        axis0 = vt[2]

    u0, v0 = _basis_from_axis(axis0)
    planar = np.c_[P @ u0, P @ v0]
    R0 = float(np.mean(np.linalg.norm(planar, axis=1)))
    r0 = float(np.mean(np.abs(np.linalg.norm(planar, axis=1) - R0)) + 1e-3)

    def residuals(x):
        axis = _unit(x[:3])
        cen = x[3:6]
        R = x[6]
        r = x[7]
        d = P - (cen - c)
        w = d @ axis
        rho = np.linalg.norm(d - np.outer(w, axis), axis=1)
        return np.sqrt((rho - R) ** 2 + w ** 2) - r

    x0 = np.r_[axis0, c, R0, r0]
    try:
        res = least_squares(residuals, x0, method="lm", max_nfev=800)
    except Exception:
        return None
    R = float(abs(res.x[6]))
    r = float(abs(res.x[7]))
    if r <= 1e-3 or R <= r:
        return None
    axis = _unit(res.x[:3])
    center = res.x[3:6]
    dev = np.abs(residuals(res.x))
    return PrimitiveFit(
        "torus",
        {"center": center, "axis": axis, "major_radius": R, "minor_radius": r},
        dev,
        _DOF["torus"],
    )


_FITTERS = {
    "plane": fit_plane,
    "cylinder": fit_cylinder,
    "cone": fit_cone,
    "sphere": fit_sphere,
    "torus": fit_torus,
}


def best_fit(
    points: np.ndarray,
    normals: Optional[np.ndarray],
    tol: float,
    try_types: tuple[str, ...],
) -> Optional[PrimitiveFit]:
    """Return the simplest primitive whose max deviation is within ``tol``.

    If none qualify, return the one with the smallest max deviation (caller
    decides whether to accept it or treat the patch as freeform).
    """
    candidates: list[PrimitiveFit] = []
    for name in try_types:
        try:
            fit = _FITTERS[name](points, normals)
        except Exception:
            fit = None
        if fit is not None and np.all(np.isfinite(fit.deviations)):
            candidates.append(fit)
    if not candidates:
        return None
    within = [f for f in candidates if f.max_dev <= tol]
    if within:
        within.sort(key=lambda f: (f.dof, f.rms_dev))
        return within[0]
    candidates.sort(key=lambda f: f.max_dev)
    return candidates[0]
