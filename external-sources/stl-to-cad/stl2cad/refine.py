"""Split/merge refinement so every patch is either a clean primitive or small.

Kept deliberately cheap: the SPLIT test uses fast PCA planarity / normal-spread
heuristics (no least-squares), and MERGE only runs a real fit on the handful of
same-type neighbour pairs.
"""

from __future__ import annotations

import os

os.environ.setdefault("OMP_NUM_THREADS", "4")

import numpy as np
from sklearn.cluster import KMeans

from .config import FitConfig, SegmentConfig
from .segment import Segmentation, Patch, _patch_boundary_loops, _adjacency, _absorb_small
from .primitives import best_fit


def _needs_split(mesh, face_ids, tol: float) -> bool:
    """Fast test: is this patch clearly not a single simple primitive?"""
    faces = mesh.faces[face_ids]
    verts = np.unique(faces.ravel())
    P = mesh.vertices[verts]
    c = P.mean(0)
    # plane residual
    _, s, vt = np.linalg.svd(P - c, full_matrices=False)
    plane_dev = np.abs((P - c) @ vt[2]).max()
    if plane_dev <= tol:
        return False
    # normal spread — a single cylinder/cone has normals spanning ~a great circle;
    # a blend of surfaces has a scattered normal cloud in >1 principal plane
    n = mesh.face_normals[face_ids]
    n = n - n.mean(0)
    ns = np.linalg.svd(n, compute_uv=False)
    # if the 3rd normal-singular value is large, normals fill 3D -> not one quadric
    spread3 = ns[2] / (ns[0] + 1e-9)
    return spread3 > 0.35


def refine(seg: Segmentation, seg_cfg: SegmentConfig, fit_cfg: FitConfig,
           max_depth: int = 3, max_faces: int = 90_000) -> Segmentation:
    mesh = seg.mesh
    if len(mesh.faces) > max_faces:
        return seg
    labels = seg.labels.copy()
    n_faces = len(mesh.faces)
    big = max(seg_cfg.min_patch_faces * 6, int(n_faces * 0.015))
    scale = float(np.linalg.norm(mesh.bounds[1] - mesh.bounds[0])) or 1.0
    cent_all = mesh.vertices[mesh.faces].mean(axis=1)
    nrm_all = mesh.face_normals

    for _ in range(max_depth):
        nxt = labels.max() + 1
        changed = False
        for lbl in np.unique(labels):
            fid = np.where(labels == lbl)[0]
            if len(fid) < big:
                continue
            if not _needs_split(mesh, fid, fit_cfg.analytic_tol):
                continue
            k = int(np.clip(len(fid) // big + 1, 2, 6))
            feats = np.c_[cent_all[fid] / scale, nrm_all[fid] * 0.6]
            try:
                km = KMeans(n_clusters=k, n_init=1, random_state=0).fit(feats).labels_
            except Exception:
                continue
            for ci in range(1, k):
                labels[fid[km == ci]] = nxt
                nxt += 1
            changed = True
        _, labels = np.unique(labels, return_inverse=True)
        if not changed:
            break

    labels = _absorb_small(labels, mesh.face_adjacency, seg_cfg.min_patch_faces)

    # -------- MERGE over-split coplanar / coaxial patches (cheap descriptors) --
    tol = fit_cfg.merge_tol
    for _ in range(2):
        uniq = np.unique(labels)
        desc = {int(l): _fast_descriptor(mesh, np.where(labels == l)[0]) for l in uniq}
        adj = _adjacency_from_labels(mesh, labels)
        parent = {int(l): int(l) for l in uniq}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        merged = False
        for a in uniq:
            a = int(a)
            for b in adj[a]:
                if b <= a:
                    continue
                if _descriptors_match(desc[a], desc[int(b)], tol):
                    ra, rb = find(a), find(int(b))
                    if ra != rb:
                        parent[max(ra, rb)] = min(ra, rb)
                        merged = True
        if not merged:
            break
        vec = np.arange(labels.max() + 1)
        for l in uniq:
            vec[int(l)] = find(int(l))
        labels = vec[labels]
        _, labels = np.unique(labels, return_inverse=True)

    patches = []
    for lbl in np.unique(labels):
        fid = np.where(labels == lbl)[0]
        patches.append(Patch(id=int(lbl), faces=fid,
                             loops=_patch_boundary_loops(mesh, fid)))
    return Segmentation(mesh=mesh, labels=labels, patches=patches,
                        adjacency=_adjacency(mesh, labels))


def _fast_descriptor(mesh, fid):
    """Cheap plane/cylinder descriptor for a patch (no least-squares)."""
    faces = mesh.faces[fid]
    verts = np.unique(faces.ravel())
    P = mesh.vertices[verts]
    c = P.mean(0)
    _, s, vt = np.linalg.svd(P - c, full_matrices=False)
    n = vt[2]
    plane_dev = np.abs((P - c) @ n).max()
    diag = np.linalg.norm(P.max(0) - P.min(0)) + 1e-9
    if plane_dev < 0.15 or plane_dev / diag < 5e-3:
        return ("plane", n / (np.linalg.norm(n) or 1), float(c @ n))
    # cylinder: axis = direction least represented in face normals
    fn = mesh.face_normals[fid]
    fn = fn - fn.mean(0)
    _, sc, vc = np.linalg.svd(fn, full_matrices=False)
    axis = vc[2] / (np.linalg.norm(vc[2]) or 1)
    d = P - c
    w = d @ axis
    rho = np.linalg.norm(d - np.outer(w, axis), axis=1)
    R = float(rho.mean())
    if R > 1e-6 and rho.std() / R < 0.08:
        # point on axis closest to origin-ish (centroid projected off axis)
        return ("cyl", axis, R, c - (c @ axis) * axis)
    return ("other",)


def _descriptors_match(a, b, tol):
    if a[0] != b[0]:
        return False
    if a[0] == "plane":
        if abs(np.dot(a[1], b[1])) < np.cos(np.radians(3)):
            return False
        return abs(a[2] - abs(np.dot(a[1], b[1])) * b[2]) < tol or abs(a[2] - b[2]) < tol
    if a[0] == "cyl":
        if abs(np.dot(a[1], b[1])) < np.cos(np.radians(4)):
            return False
        if abs(a[2] - b[2]) / max(a[2], b[2]) > 0.06:
            return False
        # distance between the two axis lines (approx: perp offset of points)
        off = np.linalg.norm((a[3] - b[3]) - np.dot(a[3] - b[3], a[1]) * a[1])
        return off < max(tol, 0.1 * a[2])
    return False


def _adjacency_from_labels(mesh, labels):
    adj: dict[int, set[int]] = {int(l): set() for l in np.unique(labels)}
    fa = mesh.face_adjacency
    la, lb = labels[fa[:, 0]], labels[fa[:, 1]]
    m = la != lb
    for a, b in zip(la[m], lb[m]):
        adj[int(a)].add(int(b))
        adj[int(b)].add(int(a))
    return adj
