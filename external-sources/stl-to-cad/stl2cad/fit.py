"""Assign an analytic primitive (or 'freeform') to every patch."""

from __future__ import annotations

import numpy as np

from .config import FitConfig
from .primitives import (
    best_fit, PrimitiveFit, fit_plane, fit_cylinder, fit_cone, fit_sphere,
    fit_torus,
)
from .segment import Segmentation

_FITTERS = {"plane": fit_plane, "cylinder": fit_cylinder, "cone": fit_cone,
           "sphere": fit_sphere, "torus": fit_torus}
_DOF = {"plane": 0, "cylinder": 1, "cone": 2, "sphere": 3, "torus": 4}


def _patch_points_normals(mesh, face_ids):
    faces = mesh.faces[face_ids]
    verts, inv = np.unique(faces.ravel(), return_inverse=True)
    pts = mesh.vertices[verts]

    fn = np.repeat(mesh.face_normals[face_ids], 3, axis=0)
    acc = np.zeros((len(verts), 3))
    np.add.at(acc, inv, fn)
    nrm = acc / (np.linalg.norm(acc, axis=1, keepdims=True) + 1e-12)
    return pts, nrm, verts


def _shortlist(pts, nrm, tol, try_types):
    """Cheap classification -> which primitives are worth least-squares fitting."""
    c = pts.mean(0)
    _, s, vt = np.linalg.svd(pts - c, full_matrices=False)
    diag = float(np.linalg.norm(pts.max(0) - pts.min(0))) + 1e-9
    plane_dev = float(np.abs((pts - c) @ vt[2]).max())
    if plane_dev <= tol or plane_dev / diag < 3e-3:
        return ["plane"]

    n = nrm - nrm.mean(0)
    ns = np.linalg.svd(n, compute_uv=False)
    spread3 = ns[2] / (ns[0] + 1e-9)          # normals fill 3D -> sphere/torus/free
    if spread3 < 0.25:                        # normals ~in a plane -> cyl / cone
        return [t for t in ("cylinder", "cone", "plane") if t in try_types]
    return list(try_types)


def _best_of(names, pts, nrm, tol, try_types):
    names = sorted((n for n in names if n in try_types), key=lambda n: _DOF.get(n, 9))
    cands = []
    for nm in names:
        try:
            f = _FITTERS[nm](pts, nrm)
        except Exception:
            f = None
        if f is not None and np.all(np.isfinite(f.deviations)):
            cands.append(f)
            if f.max_dev <= tol:      # simplest primitive that fits wins - stop
                return f
    if not cands:
        return None
    cands.sort(key=lambda f: f.max_dev)
    return cands[0]


def _sphere_is_degenerate(fit: PrimitiveFit, pts: np.ndarray) -> bool:
    if fit.kind != "sphere":
        return False
    diag = np.linalg.norm(pts.max(0) - pts.min(0)) + 1e-9
    return fit.params["radius"] > 4.0 * diag


def assign_fits(seg: Segmentation, cfg: FitConfig, max_sample: int = 2500) -> dict[int, PrimitiveFit]:
    mesh = seg.mesh
    rng = np.random.default_rng(0)
    fits: dict[int, PrimitiveFit] = {}

    for patch in seg.patches:
        pts, nrm, _ = _patch_points_normals(mesh, patch.faces)
        if len(pts) > max_sample:
            idx = rng.choice(len(pts), max_sample, replace=False)
            spts, snrm = pts[idx], nrm[idx]
        else:
            spts, snrm = pts, nrm

        names = _shortlist(spts, snrm, cfg.analytic_tol, cfg.try_types)
        fit = _best_of(names, spts, snrm, cfg.analytic_tol, cfg.try_types)
        if (fit is None or fit.max_dev > cfg.analytic_tol) and names != list(cfg.try_types):
            fit = best_fit(spts, snrm, cfg.analytic_tol, cfg.try_types)

        if fit is not None and _sphere_is_degenerate(fit, spts):
            pl = fit_plane(spts, snrm)
            fit = pl if pl is not None else fit

        if fit is None or fit.max_dev > cfg.analytic_tol:
            # keep the best analytic guess around for diagnostics but mark freeform
            marker = PrimitiveFit("freeform",
                                  fit.params if fit else {},
                                  fit.deviations if fit is not None else np.array([np.inf]),
                                  99)
            fits[patch.id] = marker
            patch.kind = "freeform"
        else:
            fits[patch.id] = fit
            patch.kind = fit.kind
    return fits
