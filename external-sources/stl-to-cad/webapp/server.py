"""FastAPI backend for the STL -> CAD Converter web UI.

Start with:  python -m webapp    (opens a browser at http://127.0.0.1:8765)

Conversions run in a single child process because OpenCASCADE is not
thread-safe; the parent only serves files and status.
"""

from __future__ import annotations

import io
import json
import tempfile
import threading
import time
import traceback
import uuid
import zipfile
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, UploadFile, Form, HTTPException
from fastapi.responses import (
    FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse,
)
from fastapi.staticfiles import StaticFiles

from stl2cad.config import DEFAULT
from webapp.worker import convert

HERE = Path(__file__).parent
STATIC = HERE / "static"

app = FastAPI(title="STL to CAD Converter")


def _worker_init():
    import os
    os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
    os.environ.setdefault("OMP_NUM_THREADS", "4")


_POOL = ProcessPoolExecutor(max_workers=1, initializer=_worker_init)
_POOL_LOCK = threading.Lock()


def _reset_pool():
    global _POOL
    with _POOL_LOCK:
        try:
            _POOL.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        _POOL = ProcessPoolExecutor(max_workers=1, initializer=_worker_init)


@dataclass
class Job:
    id: str
    workdir: Path
    status: str = "running"          # running | done | error
    error: str = ""
    started: float = field(default_factory=time.time)
    future: object = None
    result: dict | None = None

    def progress(self) -> dict:
        try:
            return json.loads((self.workdir / "progress.json").read_text())
        except Exception:
            return {"stage": "queued", "message": "", "elapsed": round(time.time() - self.started, 1)}

    def public(self) -> dict:
        self._poll()
        p = self.progress()
        d = {"id": self.id, "status": self.status, "error": self.error,
             "stage": p.get("stage", ""), "message": p.get("message", ""),
             "elapsed": p.get("elapsed", round(time.time() - self.started, 1))}
        if self.status == "done":
            d["result"] = self.result
        return d

    def _poll(self):
        if self.status != "running" or self.future is None or not self.future.done():
            return
        try:
            self.result = self.future.result()
            self.status = "done"
        except BrokenProcessPool:
            self.status = "error"
            p = self.progress()
            self.error = ("conversion timed out" if p.get("message") == "timed out"
                          else "the converter process crashed on this mesh")
            _reset_pool()
        except Exception as exc:
            self.status = "error"
            self.error = f"{type(exc).__name__}: {exc}"
            traceback.print_exception(exc)


JOBS: dict[str, Job] = {}


_SAMPLE_DIR = Path.cwd()


@app.get("/", response_class=HTMLResponse)
def index():
    return (STATIC / "index.html").read_text(encoding="utf8")


@app.get("/api/samples")
def api_samples():
    return sorted(p.name for p in _SAMPLE_DIR.glob("*.stl"))


@app.get("/api/samples/{name}")
def api_sample(name: str):
    p = (_SAMPLE_DIR / name).resolve()
    if p.parent != _SAMPLE_DIR.resolve() or p.suffix.lower() != ".stl" or not p.exists():
        raise HTTPException(404)
    return FileResponse(p, filename=p.name, media_type="application/octet-stream")


@app.post("/api/convert")
async def api_convert(
    file: UploadFile,
    method: str = Form("faceted"),
    tol: float = Form(0.5),
    faces: int = Form(25000),
    dihedral: float = Form(18.0),
    arc_simplify: float = Form(0.15),
    refine: bool = Form(True),
):
    if not (file.filename or "").lower().endswith(".stl"):
        raise HTTPException(400, "please upload a .stl file")
    data = await file.read()
    if len(data) > 400 * 1024 * 1024:
        raise HTTPException(413, "file too large (400 MB max)")

    jid = uuid.uuid4().hex[:12]
    wd = Path(tempfile.mkdtemp(prefix="stl2cad_"))
    stem = Path(file.filename).stem or "model"
    stl_path = wd / f"{stem}.stl"
    stl_path.write_bytes(data)

    cfg = {
        "heal": {**{k: getattr(DEFAULT.heal, k) for k in ("merge_distance", "max_hole_edges", "decimate_skip_below", "preserve_boundary")}, "target_faces": int(faces)},
        "segment": {**{k: getattr(DEFAULT.segment, k) for k in ("curvature_ratio", "min_patch_faces", "normal_bucket_deg")}, "dihedral_deg": float(dihedral), "refine": bool(refine)},
        "fit": {**{k: getattr(DEFAULT.fit, k) for k in ("target_tol", "ransac_iters", "merge_tol", "try_types")}, "analytic_tol": float(tol)},
        "build": {**{k: getattr(DEFAULT.build, k) for k in ("sew_tol", "shape_tol", "unify", "unify_angular_tol", "unify_linear_tol", "freeform_filling", "freeform_filling_max_boundary", "sew_face_limit", "faceted_polish_limit", "faceted_shapefix_limit", "max_build_faces", "faceted_fallback", "arcwise_budget_s")}, "method": method, "arc_simplify": float(arc_simplify)},
        "validate": {},
        "export": {},
    }

    job = Job(id=jid, workdir=wd)
    with _POOL_LOCK:
        job.future = _POOL.submit(convert, str(stl_path), cfg, str(wd))
    JOBS[jid] = job
    return {"id": jid}


@app.get("/api/jobs/{jid}")
def api_status(jid: str):
    job = JOBS.get(jid)
    if job is None:
        raise HTTPException(404, "unknown job")
    return JSONResponse(job.public())


def _glb(jid: str, which: str):
    job = JOBS.get(jid)
    if job is None:
        raise HTTPException(404)
    job._poll()
    path = (job.result or {}).get(f"{which}_glb") if job.result else None
    if not path or not Path(path).exists():
        raise HTTPException(404)
    return Response(Path(path).read_bytes(), media_type="model/gltf-binary")


@app.get("/api/jobs/{jid}/solid.glb")
def api_solid(jid: str):
    return _glb(jid, "solid")


@app.get("/api/jobs/{jid}/mesh.glb")
def api_mesh(jid: str):
    return _glb(jid, "mesh")


@app.get("/api/jobs/{jid}/download/{kind}")
def api_download(jid: str, kind: str):
    job = JOBS.get(jid)
    if job is None:
        raise HTTPException(404)
    job._poll()
    path = (job.result or {}).get("outputs", {}).get(kind)
    if not path or not Path(path).exists():
        raise HTTPException(404, f"no {kind} output")
    return FileResponse(path, filename=Path(path).name,
                        media_type="application/octet-stream")


@app.get("/api/jobs/{jid}/download-all")
def api_download_all(jid: str):
    job = JOBS.get(jid)
    if job is None or not job.result:
        raise HTTPException(404)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path in job.result.get("outputs", {}).values():
            p = Path(path)
            if p.exists():
                z.write(p, p.name)
    buf.seek(0)
    stem = Path(job.result["source"]).stem
    return StreamingResponse(buf, media_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="{stem}_cad.zip"'})


app.mount("/static", StaticFiles(directory=STATIC), name="static")
