"""Segment a triangle mesh into surface patches by region growing.

Output is a :class:`Segmentation` holding a per-triangle patch label plus helper
structures (patch adjacency, ordered boundary loops) used by :mod:`stl2cad.topology`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import trimesh

from .config import SegmentConfig


@dataclass
class Patch:
    id: int
    faces: np.ndarray
    loops: list[list[int]] = field(default_factory=list)
    kind: str = "unknown"


@dataclass
class Segmentation:
    mesh: trimesh.Trimesh
    labels: np.ndarray
    patches: list[Patch]
    adjacency: dict[int, set[int]]

    @property
    def n_patches(self) -> int:
        return len(self.patches)


# --------------------------------------------------------------------------- #
def _union_find_labels(n: int, pairs: np.ndarray) -> np.ndarray:
    parent = np.arange(n)

    def find(x):
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    for a, b in pairs:
        ra, rb = find(int(a)), find(int(b))
        if ra != rb:
            parent[ra] = rb
    roots = np.fromiter((find(i) for i in range(n)), dtype=np.int64, count=n)
    _, inv = np.unique(roots, return_inverse=True)
    return inv


def _absorb_small(labels: np.ndarray, adj_pairs: np.ndarray, min_faces: int,
                  face_counts_of: np.ndarray | None = None) -> np.ndarray:
    """Iteratively merge undersized patches into their majority neighbour."""
    labels = labels.copy()
    for _ in range(8):
        counts = np.bincount(labels)
        small = np.where(counts < min_faces)[0]
        if small.size == 0:
            break
        la = labels[adj_pairs[:, 0]]
        lb = labels[adj_pairs[:, 1]]
        cross = la != lb
        la, lb = la[cross], lb[cross]

        # for each small label, tally neighbour labels
        remap = {}
        small_set = set(small.tolist())
        # build neighbour votes vectorised-ish
        src = np.concatenate([la, lb])
        dst = np.concatenate([lb, la])
        order = np.argsort(src, kind="stable")
        src, dst = src[order], dst[order]
        bounds = np.searchsorted(src, np.arange(src.max() + 2)) if src.size else np.array([0])
        for lbl in small:
            if lbl + 1 >= len(bounds):
                continue
            seg = dst[bounds[lbl]:bounds[lbl + 1]]
            seg = seg[seg != lbl]
            if seg.size:
                remap[int(lbl)] = int(np.bincount(seg).argmax())
        if not remap:
            break
        # resolve chains
        for k in list(remap):
            v = remap[k]
            seen = {k}
            while v in remap and v not in seen:
                seen.add(v)
                v = remap[v]
            remap[k] = v
        vec = np.arange(labels.max() + 1)
        for k, v in remap.items():
            vec[k] = v
        labels = vec[labels]
        _, labels = np.unique(labels, return_inverse=True)
    return labels


def region_grow(mesh: trimesh.Trimesh, cfg: SegmentConfig) -> np.ndarray:
    n = len(mesh.faces)
    fa = mesh.face_adjacency
    ang = np.degrees(mesh.face_adjacency_angles)
    smooth = fa[ang <= cfg.dihedral_deg]

    labels = _union_find_labels(n, smooth)
    labels = _absorb_small(labels, fa, cfg.min_patch_faces)
    return labels


# --------------------------------------------------------------------------- #
def _patch_boundary_loops(mesh: trimesh.Trimesh, face_ids: np.ndarray) -> list[list[int]]:
    faces = mesh.faces[face_ids]
    edge_count: dict[tuple[int, int], int] = {}
    edge_dir: dict[tuple[int, int], tuple[int, int]] = {}
    for tri in faces:
        for i in range(3):
            a, b = int(tri[i]), int(tri[(i + 1) % 3])
            key = (a, b) if a < b else (b, a)
            edge_count[key] = edge_count.get(key, 0) + 1
            if key not in edge_dir:
                edge_dir[key] = (a, b)

    nxt: dict[int, list[int]] = {}
    for key, cnt in edge_count.items():
        if cnt == 1:
            a, b = edge_dir[key]
            nxt.setdefault(a, []).append(b)

    loops: list[list[int]] = []
    visited: set[tuple[int, int]] = set()
    for start in list(nxt):
        for first in nxt.get(start, []):
            if (start, first) in visited:
                continue
            loop = [start]
            cur, prev = first, start
            visited.add((prev, cur))
            guard = 0
            while cur != start and guard < 200000:
                guard += 1
                loop.append(cur)
                nc = None
                for c in nxt.get(cur, []):
                    if (cur, c) not in visited:
                        nc = c
                        break
                if nc is None:
                    break
                visited.add((cur, nc))
                cur = nc
            if cur == start and len(loop) >= 3:
                loops.append(loop)
    loops.sort(key=len, reverse=True)
    return loops


def _adjacency(mesh: trimesh.Trimesh, labels: np.ndarray) -> dict[int, set[int]]:
    adj: dict[int, set[int]] = {int(l): set() for l in np.unique(labels)}
    fa = mesh.face_adjacency
    la, lb = labels[fa[:, 0]], labels[fa[:, 1]]
    for a, b in zip(la[la != lb], lb[la != lb]):
        adj[int(a)].add(int(b))
        adj[int(b)].add(int(a))
    return adj


def segment(mesh: trimesh.Trimesh, cfg: SegmentConfig) -> Segmentation:
    labels = region_grow(mesh, cfg)
    patches = []
    for lbl in np.unique(labels):
        face_ids = np.where(labels == lbl)[0]
        loops = _patch_boundary_loops(mesh, face_ids)
        patches.append(Patch(id=int(lbl), faces=face_ids, loops=loops))
    return Segmentation(mesh=mesh, labels=labels, patches=patches,
                        adjacency=_adjacency(mesh, labels))
