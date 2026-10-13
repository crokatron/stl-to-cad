"""Extract the arc network that separates mesh patches.

An *arc* is a maximal polyline of boundary edges shared by the same pair of
patches, running between two *nodes* (vertices where >2 boundary edges meet or
the patch-pair changes). Arcs are the atoms of the reconstructed B-rep: one
shared edge per arc guarantees neighbouring faces stitch with no sewing.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np


@dataclass
class Arc:
    id: int
    verts: list[int]                 # ordered mesh-vertex indices
    pair: tuple[int, int]            # the two patch ids it separates (-1 = open)
    n0: int = -1                     # node id at start
    n1: int = -1                     # node id at end
    kept: np.ndarray = field(default=None)   # simplified polyline (set later)


@dataclass
class ArcNetwork:
    arcs: list[Arc]
    nodes: dict[int, int]            # mesh-vertex index -> node id
    arcs_of_patch: dict[int, list[int]]
    open_boundary: bool


def _boundary_pairs(mesh, labels) -> dict[tuple[int, int], tuple[int, int]]:
    out: dict[tuple[int, int], tuple[int, int]] = {}
    fae = mesh.face_adjacency_edges
    for (fa, fb), (v0, v1) in zip(mesh.face_adjacency, fae):
        la, lb = int(labels[fa]), int(labels[fb])
        if la == lb:
            continue
        k = (int(v0), int(v1)) if v0 < v1 else (int(v1), int(v0))
        out[k] = (min(la, lb), max(la, lb))
    # open boundary edges (used by a single triangle)
    try:
        from trimesh.grouping import group_rows
        es = mesh.edges_sorted
        single = group_rows(es, require_count=1)
        for r in single:
            a, b = int(es[r][0]), int(es[r][1])
            k = (a, b) if a < b else (b, a)
            fid = r // 3
            out.setdefault(k, (int(labels[fid]), -1))
    except Exception:
        pass
    return out


def build_arc_network(mesh, labels) -> ArcNetwork:
    bp = _boundary_pairs(mesh, labels)
    vadj: dict[int, list[tuple[int, tuple[int, int]]]] = defaultdict(list)
    for (a, b), pair in bp.items():
        vadj[a].append((b, pair))
        vadj[b].append((a, pair))

    def is_node(v: int) -> bool:
        nb = vadj[v]
        if len(nb) != 2:
            return True
        return nb[0][1] != nb[1][1]

    node_ids: dict[int, int] = {}
    for v in vadj:
        if is_node(v):
            node_ids[v] = len(node_ids)

    used: set[frozenset] = set()
    arcs: list[Arc] = []

    def walk(start: int, nxt: int, pair):
        seq = [start, nxt]
        used.add(frozenset((start, nxt)))
        prev, cur = start, nxt
        while cur not in node_ids:
            cand = [o for (o, p) in vadj[cur]
                    if o != prev and p == pair and frozenset((cur, o)) not in used]
            if not cand:
                break
            nn = cand[0]
            used.add(frozenset((cur, nn)))
            seq.append(nn)
            prev, cur = cur, nn
        return seq

    for v in list(node_ids):
        for (o, pair) in vadj[v]:
            if frozenset((v, o)) in used:
                continue
            seq = walk(v, o, pair)
            arc = Arc(id=len(arcs), verts=seq, pair=pair)
            arc.n0 = node_ids.get(seq[0], -1)
            arc.n1 = node_ids.get(seq[-1], -1)
            arcs.append(arc)

    # closed loops with no node: synthesise a node at the first vertex
    for (a, b), pair in bp.items():
        if frozenset((a, b)) in used:
            continue
        node_ids.setdefault(a, len(node_ids))
        seq = walk(a, b, pair)
        if seq[-1] != a:
            seq.append(a)
        arc = Arc(id=len(arcs), verts=seq, pair=pair)
        arc.n0 = arc.n1 = node_ids[a]
        arcs.append(arc)

    arcs_of_patch: dict[int, list[int]] = defaultdict(list)
    for arc in arcs:
        for lbl in arc.pair:
            if lbl >= 0:
                arcs_of_patch[lbl].append(arc.id)

    return ArcNetwork(arcs=arcs, nodes=node_ids, arcs_of_patch=arcs_of_patch,
                      open_boundary=any(-1 in a.pair for a in arcs))


def order_loops(net: ArcNetwork, patch_id: int) -> list[list[int]]:
    """Return list of loops; each loop is an ordered list of arc ids."""
    ids = list(net.arcs_of_patch.get(patch_id, []))
    if not ids:
        return []
    by_node: dict[int, list[int]] = defaultdict(list)
    for aid in ids:
        arc = net.arcs[aid]
        by_node[arc.n0].append(aid)
        by_node[arc.n1].append(aid)

    remaining = set(ids)
    loops: list[list[int]] = []
    while remaining:
        aid = next(iter(remaining))
        arc = net.arcs[aid]
        loop = [aid]
        remaining.discard(aid)
        start, cur = arc.n0, arc.n1
        guard = 0
        while cur != start and guard < 100000:
            guard += 1
            nxt = None
            for cand in by_node.get(cur, []):
                if cand in remaining:
                    nxt = cand
                    break
            if nxt is None:
                break
            na = net.arcs[nxt]
            loop.append(nxt)
            remaining.discard(nxt)
            cur = na.n1 if na.n0 == cur else na.n0
        loops.append(loop)

    # outer boundary first (proxy: more distinct vertices than a hole rim)
    loops.sort(key=lambda lp: len({v for aid in lp for v in net.arcs[aid].verts}),
               reverse=True)
    return loops
