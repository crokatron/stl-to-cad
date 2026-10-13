"""Build a watertight solid B-rep from a segmented, primitive-fitted mesh.

Approach
--------
* One **shared** ``TopoDS_Edge`` per inter-patch mesh edge (keyed by its vertex
  pair) so neighbouring patch faces are guaranteed to stitch.
* Per patch: assemble the ordered boundary loops (from segmentation) into wires
  and build a single face -- on the fitted analytic surface where available,
  otherwise a filled/plate face that follows the mesh.
* Sew -> shell -> solid -> ShapeFix -> (optional) UnifySameDomain.
* Fallback: if no closed solid results, build a faceted solid from the mesh.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from OCC.Core.BRep import BRep_Builder
from OCC.Core.BRepBuilderAPI import (
    BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire, BRepBuilderAPI_MakeFace,
    BRepBuilderAPI_MakePolygon, BRepBuilderAPI_Sewing, BRepBuilderAPI_MakeSolid,
)
from OCC.Core.BRepOffsetAPI import BRepOffsetAPI_MakeFilling
from OCC.Core.GeomAbs import GeomAbs_C0
from OCC.Core.ShapeFix import (
    ShapeFix_Shape, ShapeFix_Face, ShapeFix_Shell, ShapeFix_Solid,
)
from OCC.Core.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
from OCC.Core.TopoDS import TopoDS_Shell, TopoDS_Compound, topods
from OCC.Core.TopExp import TopExp_Explorer, topexp
from OCC.Core.TopAbs import TopAbs_SHELL, TopAbs_EDGE, TopAbs_FACE
from OCC.Core.TopTools import TopTools_IndexedDataMapOfShapeListOfShape

from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
from OCC.Core.gp import gp_Circ, gp_Ax2
from OCC.Core.GC import GC_MakeArcOfCircle

from .config import BuildConfig, FitConfig
from .curves import rdp, fit_arc
from .arcs import build_arc_network, order_loops
from .occ_util import (
    pnt, surface_from_fit, bspline_from_points, count_solids, is_valid,
    face_kind_histogram,
)


@dataclass
class BuildResult:
    shape: object
    method: str
    n_solids: int
    closed: bool
    face_hist: dict = field(default_factory=dict)
    free_edges: int = -1
    n_analytic: int = 0
    notes: list = field(default_factory=list)


# --------------------------------------------------------------------------- #
class _EdgePool:
    """Cache of one shared TopoDS_Edge per mesh-vertex pair."""

    def __init__(self, vertices):
        self.V = vertices
        self._cache: dict[tuple[int, int], object] = {}

    def segment(self, a: int, b: int):
        key = (a, b) if a < b else (b, a)
        e = self._cache.get(key)
        if e is None:
            mk = BRepBuilderAPI_MakeEdge(pnt(self.V[a]), pnt(self.V[b]))
            e = mk.Edge() if mk.IsDone() else None
            self._cache[key] = e
        return e

    def polyline_wire(self, loop: list[int]):
        mw = BRepBuilderAPI_MakeWire()
        n = 0
        for i in range(len(loop)):
            a, b = loop[i], loop[(i + 1) % len(loop)]
            if a == b:
                continue
            e = self.segment(a, b)
            if e is not None:
                mw.Add(e)
                n += 1
        if n >= 3 and mw.IsDone():
            return mw.Wire()
        return None


# --------------------------------------------------------------------------- #
def _periodic_face(fit, patch_pts):
    """Face on a periodic surface (cyl/cone/sphere/torus) trimmed by the u,v
    range of the patch points -- handles the seam automatically."""
    from OCC.Core.GeomAPI import GeomAPI_ProjectPointOnSurf
    import math
    surf = surface_from_fit(fit)
    if surf is None or len(patch_pts) < 5:
        return None

    us, vs = [], []
    step = max(1, len(patch_pts) // 120)
    for p in patch_pts[::step]:
        proj = GeomAPI_ProjectPointOnSurf(pnt(p), surf)
        if proj.NbPoints() >= 1:
            u, v = proj.LowerDistanceParameters()
            us.append(u); vs.append(v)
    if len(us) < 5:
        return None
    us = np.array(us); vs = np.array(vs)

    # v-range: use the fitted geometry directly (projection can produce outliers)
    if fit.kind == "cylinder":
        axis = fit.params["axis"] / (np.linalg.norm(fit.params["axis"]) or 1)
        w = (patch_pts - fit.params["point"]) @ axis
        vmin, vmax = float(w.min()), float(w.max())
    elif fit.kind == "cone":
        axis = fit.params["axis"] / (np.linalg.norm(fit.params["axis"]) or 1)
        w = (patch_pts - fit.params["apex"]) @ axis
        vmin, vmax = float(w.min()), float(w.max())
    else:
        lo, hi = np.percentile(vs, [2, 98])
        vmin, vmax = float(lo), float(hi)
    span = np.linalg.norm(patch_pts.max(0) - patch_pts.min(0))
    if vmax - vmin < 1e-6 or (vmax - vmin) > 1.8 * span + 1e-6:
        return None

    umin, umax = float(np.percentile(us, 2)), float(np.percentile(us, 98))
    if fit.kind in ("cylinder", "cone", "sphere", "torus"):
        hist, _ = np.histogram(us % (2 * math.pi), bins=24, range=(0, 2 * math.pi))
        if np.all(hist > 0):
            umin, umax = 0.0, 2 * math.pi
    if umax - umin < 1e-6:
        return None
    try:
        mf = BRepBuilderAPI_MakeFace(surf, umin, umax, vmin, vmax, 1e-6)
        if mf.IsDone():
            return mf.Face()
    except Exception:
        pass
    return None


def _bspline_face(patch_pts, wires, grid=10):
    """Fit a low-order B-spline surface to scattered patch points, trim by wire.

    Kept low-degree (<=3) and modest-grid so OCC can mesh the trimmed face fast.
    """
    from OCC.Core.TColgp import TColgp_Array2OfPnt
    from OCC.Core.GeomAPI import GeomAPI_PointsToBSplineSurface
    from OCC.Core.GeomAbs import GeomAbs_C1
    from scipy.interpolate import griddata

    if len(patch_pts) < 12 or not wires:
        return None
    c = patch_pts.mean(axis=0)
    _, sv, vt = np.linalg.svd(patch_pts - c, full_matrices=False)
    if sv[2] / (sv[0] + 1e-9) > 0.55:      # not a height-field -> not safe
        return None
    e1, e2, e3 = vt[0], vt[1], vt[2]
    uv = np.c_[(patch_pts - c) @ e1, (patch_pts - c) @ e2]
    w = (patch_pts - c) @ e3
    wlo, whi = float(w.min()), float(w.max())
    umin, vmin = uv.min(axis=0)
    umax, vmax = uv.max(axis=0)
    GU, GV = np.meshgrid(np.linspace(umin, umax, grid),
                         np.linspace(vmin, vmax, grid), indexing="ij")
    GW = griddata(uv, w, (GU, GV), method="linear", fill_value=float(np.mean(w)))
    # never let the fitted surface fly outside the patch's own height range
    margin = 0.15 * (whi - wlo) + 1e-6
    GW = np.clip(GW, wlo - margin, whi + margin)
    try:
        arr = TColgp_Array2OfPnt(1, grid, 1, grid)
        for i in range(grid):
            for j in range(grid):
                arr.SetValue(i + 1, j + 1, pnt(
                    c + GU[i, j] * e1 + GV[i, j] * e2 + GW[i, j] * e3))
        # interpolation (not approximation) -> stays within the data envelope
        surf = GeomAPI_PointsToBSplineSurface(arr).Surface()
        return _face_on_surface(surf, wires)
    except Exception:
        return None


def _face_on_surface(surf, wires):
    """High-level trimmed-face build (edges are copied; a later tolerance sew
    stitches neighbouring faces)."""
    try:
        mf = BRepBuilderAPI_MakeFace(surf, wires[0], True)
        if not mf.IsDone():
            return None
        face = mf.Face()
        for w in wires[1:]:
            mf2 = BRepBuilderAPI_MakeFace(face)
            mf2.Add(w)
            if mf2.IsDone():
                face = mf2.Face()
        return face
    except Exception:
        return None


def _analytic_face(fit, wires):
    surf = surface_from_fit(fit)
    if surf is None or not wires:
        return None
    try:
        if fit.kind == "plane":
            mf = BRepBuilderAPI_MakeFace(wires[0], True)
            if not mf.IsDone():
                return None
            face = mf.Face()
            for w in wires[1:]:
                mf2 = BRepBuilderAPI_MakeFace(face)
                mf2.Add(w)
                if mf2.IsDone():
                    face = mf2.Face()
            return face
    except Exception:
        return None
    return _face_on_surface(surf, wires)


def _filled_face(edges, interior_pts):
    f = BRepOffsetAPI_MakeFilling()
    added = 0
    for e in edges:
        if e is None:
            continue
        try:
            f.Add(e, GeomAbs_C0)
            added += 1
        except Exception:
            pass
    if added < 3:
        return None
    for p in interior_pts:
        try:
            f.Add(pnt(p))
        except Exception:
            pass
    try:
        f.Build()
        if f.IsDone():
            return topods.Face(f.Shape())
    except Exception:
        pass
    return None


def _loop_edges(pool: _EdgePool, loop: list[int]):
    out = []
    for i in range(len(loop)):
        a, b = loop[i], loop[(i + 1) % len(loop)]
        if a != b:
            out.append(pool.segment(a, b))
    return out


# --------------------------------------------------------------------------- #
def _tri_face(pool: _EdgePool, tri) -> object | None:
    a, b, c = int(tri[0]), int(tri[1]), int(tri[2])
    if a == b or b == c or a == c:
        return None
    mw = BRepBuilderAPI_MakeWire()
    for u, v in ((a, b), (b, c), (c, a)):
        e = pool.segment(u, v)
        if e is None:
            return None
        mw.Add(e)
    if not mw.IsDone():
        return None
    mf = BRepBuilderAPI_MakeFace(mw.Wire(), True)
    return mf.Face() if mf.IsDone() else None


def build_arcwise(seg, fits, cfg: BuildConfig, fit_cfg: FitConfig,
                  simplify_eps: float | None = None) -> BuildResult:
    """Reconstruct from the arc network: one shared edge per arc, one face per
    patch. Closed by construction -- no sewing, small output."""
    import os, time as _t
    _dbg = bool(os.environ.get("STL2CAD_VERBOSE"))
    def _p(m):
        if _dbg:
            print(f"    [arcwise {_t.strftime('%H:%M:%S')}] {m}", flush=True)

    simplify_eps = cfg.arc_simplify if simplify_eps is None else simplify_eps
    mesh = seg.mesh
    V = mesh.vertices
    net = build_arc_network(mesh, seg.labels)
    _p(f"network {len(net.arcs)} arcs {len(net.nodes)} nodes")
    if not net.arcs:
        return BuildResult(None, "arcwise", 0, False, notes=["no arcs"])

    # shared node vertices
    node_vertex = {nid: BRepBuilderAPI_MakeVertex(pnt(V[v])).Vertex()
                   for v, nid in net.nodes.items()}
    nid_to_v = {nid: v for v, nid in net.nodes.items()}

    freeform = {pid for pid, f in fits.items() if f is not None and f.kind == "freeform"}

    # one shared edge per arc (simplify harder along freeform patch borders so
    # their plate faces don't drown in constraints)
    arc_edge: dict[int, object] = {}
    for arc in net.arcs:
        eps = simplify_eps * (6.0 if (arc.pair[0] in freeform or arc.pair[1] in freeform)
                              else 1.0)
        P = V[np.asarray(arc.verts, int)]
        keep = rdp(P, eps) if len(P) >= 3 else P
        arc.kept = keep
        v0 = node_vertex.get(arc.n0)
        v1 = node_vertex.get(arc.n1)
        e = _make_arc_edge(keep, v0, v1, eps)
        arc_edge[arc.id] = e
    _p(f"arc edges built ({sum(e is not None for e in arc_edge.values())}/{len(net.arcs)})")

    builder = BRep_Builder()
    shell = TopoDS_Shell()
    builder.MakeShell(shell)
    n_analytic = n_filled = n_tri = n_fail = 0

    mesh_diag = float(np.linalg.norm(mesh.bounds[1] - mesh.bounds[0]))

    def _sane(f):
        """Reject a face whose surface fit ran away (bbox >> the part)."""
        try:
            from OCC.Core.Bnd import Bnd_Box
            from OCC.Core.BRepBndLib import brepbndlib
            bb = Bnd_Box(); brepbndlib.Add(f, bb)
            return bb.CornerMin().Distance(bb.CornerMax()) < 0.85 * mesh_diag
        except Exception:
            return True

    _t0 = _t.time()
    _bailed = False
    for patch in seg.patches:
        if _t.time() - _t0 > cfg.arcwise_budget_s:
            _bailed = True
            _p(f"time budget exceeded at patch {patch.id}")
            for tri in mesh.faces[patch.faces]:
                tf = _tri_face_v(mesh.vertices, tri)
                if tf is not None:
                    builder.Add(shell, tf)
                    n_tri += 1
            n_fail += 1
            continue
        _p(f"patch {patch.id} ({len(patch.faces)} tris, fit={fits.get(patch.id).kind if fits.get(patch.id) else '?'})")
        loops = order_loops(net, patch.id)
        wires = []
        loop_edges = []
        ok = True
        for loop in loops:
            edges = [arc_edge[a] for a in loop if arc_edge.get(a) is not None]
            if len(edges) < 1:
                continue
            loop_edges.append(edges)
            mw = BRepBuilderAPI_MakeWire()
            for e in edges:
                mw.Add(e)
            if mw.IsDone():
                wires.append(mw.Wire())
            else:
                ok = False
        fit = fits.get(patch.id)
        vs = np.unique(mesh.faces[patch.faces].ravel())
        patch_pts = mesh.vertices[vs]
        face = None
        try:
            if fit is not None and fit.kind == "plane" and wires and ok:
                # a planar wire bounds a real region -> shared-edge face, no sew
                face = _analytic_face(fit, wires)
            elif fit is not None and fit.kind in ("cylinder", "cone", "sphere", "torus"):
                # a curved surface needs the parametric seam -> build on the
                # natural (u,v) range, then a tight sew stitches it to neighbours
                face = _periodic_face(fit, patch_pts)
                if face is None and wires and ok:
                    face = _analytic_face(fit, wires)
        except Exception:
            face = None
        if face is not None and not _sane(face):
            _p(f"patch {patch.id}: {fit.kind} face bbox blew up -> discard")
            face = None
        if face is not None:
            n_analytic += 1

        # freeform: a plate surface through the (shared) boundary + interior pts.
        # MakeFilling interpolates -> stays bounded, unlike a B-spline approx.
        flat_edges = [e for grp in loop_edges for e in grp]
        if face is None and wires and 3 <= len(flat_edges) <= 130:
            step = max(1, len(patch_pts) // 25)
            try:
                face = _filled_face(flat_edges, patch_pts[::step])
            except Exception:
                face = None
            if face is not None and not _sane(face):
                face = None
            if face is not None:
                n_filled += 1

        if face is None:
            n_fail += 1
            # keep the patch as a (decimated) faceted island; the tolerance sew
            # bridges its border to the analytic neighbours
            tris = _decimate_patch(mesh, patch.faces, target=500)
            for a, b, c in tris:
                tf = _tri_face_v(mesh.vertices, (a, b, c))
                if tf is not None:
                    builder.Add(shell, tf)
                    n_tri += 1
            if n_tri > cfg.sew_face_limit:
                _p(f"patch {patch.id}: faceted islands exceed budget -> abandon arcwise")
                return BuildResult(None, "arcwise", 0, False, notes=[
                    f"{n_fail} freeform patch(es) too large to plate-fill "
                    f"(e.g. a hole-lined fillet strip). Falling back to faceted."])
            continue
        builder.Add(shell, face)

    _p(f"faces done: analytic={n_analytic} filled={n_filled} tri={n_tri} fail={n_fail}")
    if n_fail > 0.45 * max(1, seg.n_patches):
        return BuildResult(None, "arcwise", 0, False,
                           notes=[f"too many patches unreconstructed "
                                  f"(fail={n_fail}/{seg.n_patches})"])
    shell.Closed(True)
    try:
        ms = BRepBuilderAPI_MakeSolid(shell)
        shape = ms.Solid() if ms.IsDone() else shell
    except Exception:
        shape = shell
    fe0 = _free_edge_count(shape)
    _p(f"pre-sew free_edges={fe0}")
    if fe0 == 0:
        shape = _fix_and_unify(shape, cfg)
    else:
        # Parametric (cylinder/cone/...) faces don't share the boundary edges.
        # Sewing periodic faces is fragile and eats them, so only sew the small
        # cases; otherwise keep the shell as a sheet body (NX seals it in one
        # click) -- far more useful than dropping to faceted.
        import dataclasses
        total = n_analytic + n_filled + n_tri
        if total <= 900:
            shape = _sew_and_solidify(shell, dataclasses.replace(
                cfg, sew_tol=min(cfg.sew_tol, 0.4)))
        else:
            shape = _fix_and_unify(shape, cfg)
    fe = _free_edge_count(shape)
    nfaces = n_analytic + n_filled + n_tri
    _p(f"post free_edges={fe} solids={count_solids(shape)} faces~{nfaces}")

    note = (f"arcs={len(net.arcs)} nodes={len(net.nodes)} analytic={n_analytic} "
            f"bspline={n_filled} faceted_patches={n_fail} tri={n_tri} free_edges0={fe0}")
    if fe and fe > 0:
        note += (f"  |  {fe} unclosed edges remain -- import as a sheet body and "
                 f"run Sew/Heal in NX, or retry with a smaller --arc-simplify / "
                 f"larger --tol")
    return BuildResult(
        shape=shape, method="arcwise", n_solids=count_solids(shape),
        closed=(count_solids(shape) >= 1 and fe == 0),
        face_hist=face_kind_histogram(shape), free_edges=fe,
        notes=[note], n_analytic=n_analytic,
    )


def _decimate_patch(mesh, face_ids, target=500):
    """Return a decimated triangle list (into mesh.vertices indices) for a patch."""
    faces = mesh.faces[face_ids]
    if len(faces) <= target:
        return faces
    try:
        import fast_simplification as fs
        verts, inv = np.unique(faces.ravel(), return_inverse=True)
        local = inv.reshape(-1, 3)
        v2, f2 = fs.simplify(mesh.vertices[verts].astype(np.float64),
                             local.astype(np.int64), target_count=target, agg=6)
        # snap decimated verts back to nearest original patch vertices
        from scipy.spatial import cKDTree
        idx = cKDTree(mesh.vertices[verts]).query(v2)[1]
        out = verts[idx][f2]
        out = out[(out[:, 0] != out[:, 1]) & (out[:, 1] != out[:, 2]) & (out[:, 0] != out[:, 2])]
        return out if len(out) else faces
    except Exception:
        return faces


def _tri_face_v(V, tri):
    a, b, c = int(tri[0]), int(tri[1]), int(tri[2])
    if len({a, b, c}) < 3:
        return None
    try:
        poly = BRepBuilderAPI_MakePolygon(pnt(V[a]), pnt(V[b]), pnt(V[c]), True)
        mf = BRepBuilderAPI_MakeFace(poly.Wire(), True)
        return mf.Face() if mf.IsDone() else None
    except Exception:
        return None


def _make_arc_edge(keep, v0, v1, tol):
    keep = np.asarray(keep, float)
    if len(keep) < 2:
        return None
    closed = (len(keep) >= 4 and np.linalg.norm(keep[0] - keep[-1]) < max(tol, 1e-4)) \
        or (v0 is not None and v1 is not None and v0.IsSame(v1))
    try:
        if closed:
            circ = _fit_circle_full(keep, tol)
            if circ is not None:
                mk = BRepBuilderAPI_MakeEdge(circ)
                if mk.IsDone():
                    return mk.Edge()
            pts = keep if np.linalg.norm(keep[0] - keep[-1]) < 1e-6 else np.vstack([keep, keep[0]])
            crv = bspline_from_points(pts)
            mk = BRepBuilderAPI_MakeEdge(crv)
            return mk.Edge() if mk.IsDone() else None

        cf = fit_arc(keep, max(tol, 0.05))
        if cf.kind == "line":
            mk = (BRepBuilderAPI_MakeEdge(v0, v1) if v0 is not None and v1 is not None
                  else BRepBuilderAPI_MakeEdge(pnt(keep[0]), pnt(keep[-1])))
            return mk.Edge() if mk.IsDone() else None
        if cf.kind == "circle":
            p = cf.params
            circ = gp_Circ(gp_Ax2(pnt(p["center"]), _dir(p["normal"])), float(p["radius"]))
            arc = GC_MakeArcOfCircle(circ, pnt(p["p_start"]), pnt(p["p_end"]), True)
            if arc.IsDone():
                mk = (BRepBuilderAPI_MakeEdge(arc.Value(), v0, v1)
                      if v0 is not None and v1 is not None
                      else BRepBuilderAPI_MakeEdge(arc.Value()))
                if mk.IsDone():
                    return mk.Edge()
        crv = bspline_from_points(keep)
        mk = (BRepBuilderAPI_MakeEdge(crv, v0, v1)
              if v0 is not None and v1 is not None else BRepBuilderAPI_MakeEdge(crv))
        return mk.Edge() if mk.IsDone() else None
    except Exception:
        try:
            mk = BRepBuilderAPI_MakeEdge(pnt(keep[0]), pnt(keep[-1]))
            return mk.Edge() if mk.IsDone() else None
        except Exception:
            return None


def _fit_circle_full(pts, tol):
    c = pts.mean(axis=0)
    u, s, vt = np.linalg.svd(pts - c, full_matrices=False)
    normal = vt[2]
    e1, e2 = vt[0], vt[1]
    p2 = np.c_[(pts - c) @ e1, (pts - c) @ e2]
    A = np.c_[2 * p2, np.ones(len(p2))]
    b = np.sum(p2 ** 2, axis=1)
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    cen2 = sol[:2]
    r = float(np.sqrt(max(sol[2] + cen2 @ cen2, 1e-12)))
    center = c + cen2[0] * e1 + cen2[1] * e2
    dev = np.abs(np.linalg.norm(pts - center, axis=1) - r).max()
    if dev > max(3 * tol, 0.5):
        return None
    return gp_Circ(gp_Ax2(pnt(center), _dir(normal)), r)


def _dir(v):
    from OCC.Core.gp import gp_Dir
    v = np.asarray(v, float)
    v = v / (np.linalg.norm(v) or 1.0)
    return gp_Dir(float(v[0]), float(v[1]), float(v[2]))


def build_hybrid(seg, fits, cfg: BuildConfig, fit_cfg: FitConfig) -> BuildResult:
    """Analytic face per well-fitted patch; shared triangles everywhere else.

    Every face references shared edge objects and the patches tile the whole
    watertight mesh, so the shell is closed by construction -- no sewing needed.
    """
    mesh = seg.mesh
    pool = _EdgePool(mesh.vertices)
    builder = BRep_Builder()
    shell = TopoDS_Shell()
    builder.MakeShell(shell)

    n_analytic = n_tri = n_patch_faceted = n_filled = 0
    for patch in seg.patches:
        fit = fits.get(patch.id)
        loops = [lp for lp in patch.loops if len(lp) >= 3]
        face = None
        if fit is not None and fit.kind != "freeform" and 1 <= len(loops) <= 4:
            wires = [w for w in (pool.polyline_wire(lp) for lp in loops) if w is not None]
            if wires and len(wires) == len(loops):
                face = _analytic_face(fit, wires)
                if face is not None:
                    n_analytic += 1

        if face is None and 1 <= len(loops) <= 6 and cfg.freeform_filling:
            edges = []
            for lp in loops:
                edges += _loop_edges(pool, lp)
            verts = np.unique(mesh.faces[patch.faces].ravel())
            pts = mesh.vertices[verts]
            step = max(1, len(pts) // 30)
            face = _filled_face(edges, pts[::step])
            if face is not None:
                n_filled += 1

        if face is not None:
            builder.Add(shell, face)
        else:
            for tri in mesh.faces[patch.faces]:
                tf = _tri_face(pool, tri)
                if tf is not None:
                    builder.Add(shell, tf)
                    n_tri += 1
            n_patch_faceted += 1

    shell.Closed(True)
    try:
        ms = BRepBuilderAPI_MakeSolid(shell)
        shape = ms.Solid() if ms.IsDone() else shell
    except Exception:
        shape = shell

    fe0 = _free_edge_count(shape)
    total_faces = n_analytic + n_filled + n_tri
    if fe0 != 0 and total_faces <= cfg.sew_face_limit:
        # analytic/filled faces broke edge sharing -> stitch with tolerance
        shape = _sew_and_solidify(shell, cfg)
    elif fe0 != 0:
        # too big to sew quickly: keep the solid but note the gaps
        shape = _fix_and_unify(shape, cfg)
    else:
        shape = _fix_and_unify(shape, cfg)

    fe = _free_edge_count(shape)
    notes = [f"patches={seg.n_patches} analytic={n_analytic} filled={n_filled} "
             f"faceted_patches={n_patch_faceted} tri_faces={n_tri} free_edges0={fe0}"]
    return BuildResult(
        shape=shape, method="hybrid", n_solids=count_solids(shape),
        closed=(count_solids(shape) >= 1 and fe == 0),
        face_hist=face_kind_histogram(shape), free_edges=fe, notes=notes,
    )


def _fix_and_unify(shape, cfg: BuildConfig):
    try:
        sfs = ShapeFix_Shape(shape)
        sfs.SetPrecision(1e-5)
        sfs.SetMaxTolerance(1e-2)
        sfs.Perform()
        shape = sfs.Shape()
    except Exception:
        pass
    if cfg.unify:
        try:
            u = ShapeUpgrade_UnifySameDomain(shape, True, True, True)
            u.SetLinearTolerance(cfg.unify_linear_tol)
            u.SetAngularTolerance(cfg.unify_angular_tol)
            u.Build()
            shape = u.Shape()
        except Exception:
            pass
    return shape


# --------------------------------------------------------------------------- #
def build_faceted(mesh, cfg: BuildConfig) -> BuildResult:
    """Fast faceted solid: shared vertices/edges, no sewing, then planar merge."""
    from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_MakeVertex

    V = mesh.vertices
    F = mesh.faces
    builder = BRep_Builder()

    verts = [BRepBuilderAPI_MakeVertex(pnt(p)).Vertex() for p in V]
    edge_cache: dict[tuple[int, int], object] = {}

    def edge(a, b):
        key = (a, b) if a < b else (b, a)
        e = edge_cache.get(key)
        if e is None:
            mk = BRepBuilderAPI_MakeEdge(verts[a], verts[b])
            e = mk.Edge() if mk.IsDone() else None
            edge_cache[key] = e
        return e

    shell = TopoDS_Shell()
    builder.MakeShell(shell)
    made = 0
    for a, b, c in F:
        a, b, c = int(a), int(b), int(c)
        try:
            mw = BRepBuilderAPI_MakeWire()
            ok = True
            for u, v in ((a, b), (b, c), (c, a)):
                e = edge(u, v)
                if e is None:
                    ok = False
                    break
                mw.Add(e)
            if not ok or not mw.IsDone():
                continue
            mf = BRepBuilderAPI_MakeFace(mw.Wire(), True)
            if mf.IsDone():
                builder.Add(shell, mf.Face())
                made += 1
        except Exception:
            continue

    shell.Closed(True)
    try:
        ms = BRepBuilderAPI_MakeSolid(shell)
        shape = ms.Solid() if ms.IsDone() else shell
    except Exception:
        shape = shell
    try:
        from OCC.Core.BRepLib import breplib
        breplib.OrientClosedSolid(shape)
    except Exception:
        pass

    note = f"{len(F)} triangles, {made} faces built"
    # ShapeFix fixes face orientation (needed for a valid solid / correct
    # volume). It is ~O(faces) and gets impractical past ~50k, so above that we
    # skip it and warn -- the STL should be decimated further first.
    if made <= cfg.faceted_shapefix_limit:
        try:
            sfs = ShapeFix_Shape(shape)
            sfs.SetPrecision(1e-5)
            sfs.SetMaxTolerance(1e-2)
            sfs.Perform()
            shape = sfs.Shape()
        except Exception:
            pass
    else:
        note += (f" -- WARNING: {made} faces exceeds the fixable limit; the solid "
                 f"may have inconsistent orientation. Decimate the STL and retry "
                 f"(--faces), or pre-simplify in your mesh tool.")
    if cfg.unify and made <= cfg.faceted_polish_limit:
        try:
            u = ShapeUpgrade_UnifySameDomain(shape, True, True, True)
            u.SetLinearTolerance(cfg.unify_linear_tol)
            u.SetAngularTolerance(cfg.unify_angular_tol)
            u.Build()
            shape = u.Shape()
        except Exception:
            pass
    elif made > cfg.faceted_polish_limit:
        note += " (coplanar-merge skipped: large mesh)"

    fe = _free_edge_count(shape)
    return BuildResult(
        shape=shape, method="faceted", n_solids=count_solids(shape),
        closed=(count_solids(shape) >= 1),
        face_hist=face_kind_histogram(shape), free_edges=fe,
        notes=[note],
    )


# --------------------------------------------------------------------------- #
def _sew_and_solidify(shell, cfg: BuildConfig):
    sew = BRepBuilderAPI_Sewing(cfg.sew_tol, True, True, True, False)
    sew.SetNonManifoldMode(False)
    sew.Load(shell)
    sew.Perform()
    sewed = sew.SewedShape()

    solids = []
    ex = TopExp_Explorer(sewed, TopAbs_SHELL)
    while ex.More():
        sh = topods.Shell(ex.Current())
        try:
            ms = BRepBuilderAPI_MakeSolid(sh)
            if ms.IsDone():
                solids.append(ms.Solid())
        except Exception:
            pass
        ex.Next()

    if not solids:
        shape = sewed
    elif len(solids) == 1:
        shape = solids[0]
    else:
        b = BRep_Builder()
        comp = TopoDS_Compound()
        b.MakeCompound(comp)
        for s in solids:
            b.Add(comp, s)
        shape = comp

    try:
        sfs = ShapeFix_Shape(shape)
        sfs.SetPrecision(cfg.shape_tol)
        sfs.SetMaxTolerance(max(1.0, cfg.sew_tol * 3))
        sfs.Perform()
        shape = sfs.Shape()
    except Exception:
        pass

    if cfg.unify:
        try:
            u = ShapeUpgrade_UnifySameDomain(shape, True, True, True)
            u.Build()
            shape = u.Shape()
        except Exception:
            pass
    return shape


def _free_edge_count(shape, verbose: bool = False) -> int:
    if shape is None:
        return -1
    try:
        from OCC.Core.BRep import BRep_Tool
        m = TopTools_IndexedDataMapOfShapeListOfShape()
        topexp.MapShapesAndAncestors(shape, TopAbs_EDGE, TopAbs_FACE, m)
        size = m.Size() if hasattr(m, "Size") else m.Extent()
        n = 0
        for i in range(1, size + 1):
            edge = m.FindKey(i)
            try:
                if BRep_Tool.Degenerated(topods.Edge(edge)):
                    continue
            except Exception:
                pass
            if m.FindFromIndex(i).Size() < 2:
                n += 1
        return n
    except Exception as exc:  # pragma: no cover
        if verbose:
            import traceback
            traceback.print_exc()
        return -1


# --------------------------------------------------------------------------- #
def build(seg, fits, cfg: BuildConfig, fit_cfg: FitConfig) -> BuildResult:
    if cfg.method == "faceted":
        return build_faceted(seg.mesh, cfg)

    builders = {"arcwise": build_arcwise, "hybrid": build_hybrid}
    fn = builders.get(cfg.method, build_arcwise)
    try:
        res = fn(seg, fits, cfg, fit_cfg)
    except Exception as exc:  # pragma: no cover
        import traceback; traceback.print_exc()
        res = BuildResult(None, cfg.method, 0, False, notes=[f"error: {exc!r}"])

    if res.shape is not None and res.n_solids >= 1:
        return res

    # arcwise recovered plenty of real analytic faces but couldn't fully seal:
    # keep it as a sheet body (round holes intact) rather than dropping to the
    # heavy faceted output. The user sews it in one click in NX.
    if (res.shape is not None and res.method == "arcwise"
            and res.n_analytic >= 20
            and sum(res.face_hist.values()) < 4000):
        res.notes.append(
            f"sheet body: {res.n_analytic} analytic faces recovered, "
            f"{res.free_edges} open edges -- run Sew/Heal in NX to close it")
        return res

    if cfg.faceted_fallback:
        fb = build_faceted(seg.mesh, cfg)
        fb.notes.append(f"{cfg.method} not usable ({res.notes})")
        return fb
    return res
