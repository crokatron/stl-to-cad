"""Runs one conversion in a child process (OpenCASCADE is not thread-safe).

Everything returned is plain-old-data so it can be pickled back to the server.
Progress is written to ``<workdir>/progress.json`` for the server to poll.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

HARD_TIMEOUT_S = float(os.environ.get("STL2CAD_TIMEOUT", "240"))


def _write_progress(workdir: Path, stage: str, message: str, t0: float):
    try:
        (workdir / "progress.json").write_text(json.dumps({
            "stage": stage, "message": message,
            "elapsed": round(time.time() - t0, 1),
        }))
    except Exception:
        pass


def convert(stl_path: str, cfg_dict: dict, workdir: str) -> dict:
    from stl2cad.config import (
        PipelineConfig, HealConfig, SegmentConfig, FitConfig, BuildConfig,
        ValidateConfig, ExportConfig,
    )
    from stl2cad import pipeline as pl
    from stl2cad import preview as pv

    wd = Path(workdir)
    t0 = time.time()

    # OpenCASCADE calls cannot be interrupted from Python; if a conversion wedges,
    # kill the whole worker so the server can recover.
    def _kill():
        _write_progress(wd, "error", "timed out", t0)
        os._exit(70)

    watchdog = threading.Timer(HARD_TIMEOUT_S, _kill)
    watchdog.daemon = True
    watchdog.start()

    cfg = PipelineConfig(
        heal=HealConfig(**cfg_dict.get("heal", {})),
        segment=SegmentConfig(**cfg_dict.get("segment", {})),
        fit=FitConfig(**cfg_dict.get("fit", {})),
        build=BuildConfig(**cfg_dict.get("build", {})),
        validate=ValidateConfig(**cfg_dict.get("validate", {})),
        export=ExportConfig(**cfg_dict.get("export", {})),
    )

    _write_progress(wd, "load", "reading STL", t0)
    res = pl.run(stl_path, cfg, out_dir=wd, do_export=True,
                 progress=lambda s, m: _write_progress(wd, s, m, t0))

    _write_progress(wd, "preview", "building 3-D preview", t0)
    solid_glb = mesh_glb = None
    kinds = []
    if res.shape is not None:
        solid_tm = res.preview_mesh
        try:
            if solid_tm is None:
                solid_tm = pv.shape_to_trimesh(res.shape)
            kinds = list(solid_tm.metadata.get("kinds", []))
            (wd / "solid.glb").write_bytes(pv.to_glb(solid_tm))
            solid_glb = str(wd / "solid.glb")
        except Exception:
            pass
        try:
            dm = pv.mesh_with_deviation(res.healed_mesh, res.shape,
                                        cfg.validate.pass_max_dev,
                                        result_mesh=solid_tm)
            (wd / "mesh.glb").write_bytes(pv.to_glb(dm))
            mesh_glb = str(wd / "mesh.glb")
        except Exception:
            pass

    watchdog.cancel()
    _write_progress(wd, "done", "", t0)
    v = res.validation
    return {
        "ok": True,
        "source": Path(res.src).name,
        "mesh_tris": res.stats.n_faces,
        "healed_tris": res.healed_faces,
        "n_patches": res.n_patches,
        "method": res.build.method,
        "face_hist": res.build.face_hist,
        "n_solids": v.n_solids,
        "closed": v.closed,
        "valid": v.valid,
        "free_edges": res.build.free_edges,
        "volume_solid": round(v.volume_solid, 2),
        "volume_mesh": round(v.volume_mesh, 2),
        "volume_rel_err": round(v.volume_rel_err * 100, 2),
        "dev_max": round(v.dev_max, 4),
        "dev_rms": round(v.dev_rms, 4),
        "dev_p95": round(v.dev_p95, 4),
        "passed": v.passed,
        "notes": [str(n) for n in (res.build.notes + v.notes)],
        "timings": {k: round(val, 1) for k, val in res.timings.items()},
        "outputs": {k: str(p) for k, p in res.outputs.items()},
        "solid_glb": solid_glb,
        "mesh_glb": mesh_glb,
        "kinds": kinds,
        "bbox": {"min": list(res.stats.bbox_min), "max": list(res.stats.bbox_max)},
    }
