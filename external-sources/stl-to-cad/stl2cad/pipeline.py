"""End-to-end: STL path -> reconstructed solid + metrics + exported files."""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import trimesh

_VERBOSE = bool(os.environ.get("STL2CAD_VERBOSE"))


def _log(msg: str):
    if _VERBOSE:
        print(f"  [{time.strftime('%H:%M:%S')}] {msg}", flush=True)

from .config import PipelineConfig, DEFAULT
from .io_mesh import load_mesh, mesh_stats, MeshStats
from .heal import heal_mesh
from .segment import segment, Segmentation
from .fit import assign_fits
from .topology import build, BuildResult
from .validate import validate, ValidationResult
from .export import export_all


@dataclass
class PipelineResult:
    src: str
    stats: MeshStats
    healed_faces: int
    n_patches: int
    patch_kinds: dict
    build: BuildResult
    validation: ValidationResult
    outputs: dict = field(default_factory=dict)
    timings: dict = field(default_factory=dict)
    shape: object = None
    healed_mesh: object = None
    preview_mesh: object = None      # tessellated + type-coloured result (trimesh)

    def summary(self) -> str:
        k = ", ".join(f"{v}x{n}" for n, v in sorted(self.patch_kinds.items()))
        return (
            f"{Path(self.src).name}\n"
            f"  mesh    : {self.stats.n_faces:,} tris -> healed {self.healed_faces:,}\n"
            f"  patches : {self.n_patches}  ({k})\n"
            f"  build   : {self.build.method}  {self.build.face_hist}  "
            f"solids={self.build.n_solids} closed={self.build.closed}\n"
            f"  check   : {self.validation.summary()}\n"
            f"  time    : {self.timings.get('total', 0):.1f}s"
        )


def run(path: str | Path, cfg: PipelineConfig | None = None,
        out_dir: str | Path | None = None, do_export: bool = True,
        progress=None) -> PipelineResult:
    cfg = cfg or DEFAULT
    path = Path(path)
    t = {}
    t0 = time.time()

    def _step(stage: str, msg: str = ""):
        _log(f"{stage} {msg}")
        if progress is not None:
            try:
                progress(stage, msg)
            except Exception:
                pass

    _step("load", "reading STL")
    mesh = load_mesh(path)
    stats = mesh_stats(mesh, path)
    ref_mesh = mesh.copy()
    t["load"] = time.time() - t0
    _log(f"loaded {stats.n_faces:,} tris")

    # analytic reconstruction recovers exact surfaces, so it does NOT want an
    # aggressively decimated mesh -- that crushes small holes into polygons.
    heal_cfg = cfg.heal
    if (cfg.build.method != "faceted" and stats.n_faces <= 250_000
            and cfg.heal.target_faces and cfg.heal.target_faces < 150_000):
        import dataclasses
        heal_cfg = dataclasses.replace(cfg.heal, target_faces=None)

    ts = time.time()
    _step("heal", f"cleaning {stats.n_faces:,} triangles")
    healed = heal_mesh(mesh, heal_cfg)
    t["heal"] = time.time() - ts
    _log(f"healed -> {len(healed.faces):,} tris watertight={healed.is_watertight} ({t['heal']:.1f}s)")

    face_ceiling = cfg.build.max_build_faces
    if cfg.build.method != "faceted":
        face_ceiling = max(face_ceiling, 300_000)   # analytic path scales better
    if len(healed.faces) > face_ceiling:
        raise RuntimeError(
            f"mesh still has {len(healed.faces):,} triangles after healing "
            f"(limit {face_ceiling:,}). This mesh resists decimation "
            f"(dense/thin features). Simplify the STL in your mesh tool first, "
            f"then retry.")

    # the faceted builder ignores segmentation/fitting entirely
    faceted_only = cfg.build.method == "faceted"

    ts = time.time()
    _step("segment", "finding surface patches")
    seg = segment(healed, cfg.segment)
    _log(f"segment -> {seg.n_patches} patches ({time.time()-ts:.1f}s)")
    if cfg.segment.refine and not faceted_only:
        from .refine import refine
        seg = refine(seg, cfg.segment, cfg.fit)
        _log(f"refine -> {seg.n_patches} patches ({time.time()-ts:.1f}s)")
    t["segment"] = time.time() - ts

    ts = time.time()
    if not faceted_only:
        _step("fit", f"fitting surfaces to {seg.n_patches} patches")
    fits = {} if faceted_only else assign_fits(seg, cfg.fit)
    t["fit"] = time.time() - ts
    kinds: dict[str, int] = {}
    for f in fits.values():
        kinds[f.kind] = kinds.get(f.kind, 0) + 1
    _log(f"fit -> {kinds} ({t['fit']:.1f}s)")

    ts = time.time()
    _step("build", f"building B-rep ({cfg.build.method})")
    br = build(seg, fits, cfg.build, cfg.fit)
    t["build"] = time.time() - ts
    _log(f"build[{br.method}] -> solids={br.n_solids} closed={br.closed} "
         f"hist={br.face_hist} ({t['build']:.1f}s) {br.notes}")

    # tessellate the result once (used for both the deviation check and the
    # 3-D preview) -- meshing trimmed B-splines is the expensive bit
    preview_mesh = None
    if br.shape is not None:
        ts = time.time()
        _step("tessellate", "meshing the result for preview")
        try:
            from .preview import shape_to_trimesh
            preview_mesh = shape_to_trimesh(br.shape)
        except Exception as exc:  # pragma: no cover
            _log(f"tessellate failed: {exc!r}")
        t["tessellate"] = time.time() - ts
        _log(f"tessellate -> {0 if preview_mesh is None else len(preview_mesh.faces)} tris "
             f"({t['tessellate']:.1f}s)")

    ts = time.time()
    _step("validate", "checking solid & measuring deviation")
    val = validate(br.shape, ref_mesh if ref_mesh.is_watertight else healed,
                   cfg.validate, result_mesh=preview_mesh)
    t["validate"] = time.time() - ts
    _log(f"validate -> {val.summary()} ({t['validate']:.1f}s)")

    outputs = {}
    if do_export and br.shape is not None:
        od = Path(out_dir) if out_dir else path.parent / "out"
        od.mkdir(parents=True, exist_ok=True)
        ts = time.time()
        try:
            outputs = {k: str(v) for k, v in
                       export_all(br.shape, od / path.stem, cfg.export).items()}
        except Exception as exc:  # pragma: no cover
            outputs = {"error": repr(exc)}
        t["export"] = time.time() - ts

    t["total"] = time.time() - t0
    return PipelineResult(
        src=str(path), stats=stats, healed_faces=len(healed.faces),
        n_patches=seg.n_patches, patch_kinds=kinds, build=br, validation=val,
        outputs=outputs, timings=t, shape=br.shape, healed_mesh=healed,
        preview_mesh=preview_mesh,
    )
