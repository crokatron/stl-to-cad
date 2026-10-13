# STL → CAD Converter

Turn triangle meshes (STL) into **watertight solid B-reps** and export them as
**STEP AP242** (or AP214 / IGES / BREP). Siemens NX converts the STEP solid to a
native Parasolid body on import, so no Parasolid SDK is required.

The pipeline recognises analytic faces (plane / cylinder / cone / sphere / torus)
where the geometry genuinely is analytic and keeps everything else as a
mesh-following surface, then stitches the result into a closed solid.

> **Status (v0.1 — see `STATUS.md`):** the **`faceted`** method (default)
> reliably produces a closed solid with 0 mm deviation from the mesh — heavy
> STEP files but valid and NX-importable — for normal parts (fails on very dense
> meshes like a 1.5 M-triangle grille; decimate those first). The **`arcwise`**
> method rebuilds a *compact* analytic B-rep (≈1 face per feature) but is
> **experimental**: it currently leaves a few open edges, so the result may
> import as a sheet body needing one "Sew" in NX. Matching a hand-built NX model
> face-for-face is out of scope.

---

## Install

```bash
# 1. Miniforge (once) — https://github.com/conda-forge/miniforge
winget install CondaForge.Miniforge3

# 2. environment
conda env create -f environment.yml
conda activate stl2cad
```

Key packages: `pythonocc-core` (OpenCASCADE 7.9), `trimesh`, `pymeshlab`,
`fast-simplification`, `numpy/scipy/scikit-learn`, `PySide6`.

## Web UI (recommended)

```bash
conda activate stl2cad
python -m webapp                  # or double-click "STL2CAD Web.bat"
```

Opens `http://127.0.0.1:8765` in your browser. Everything runs on this machine —
nothing is uploaded anywhere.

* Drag in an STL (or click a **sample**), pick parameters, **Convert**.
* Interactive 3-D view: **Solid** / **Input mesh** / **Deviation** heat-map /
  **By type** (colour each face by its fitted surface — plane/cylinder/cone/…),
  wireframe, orbit/zoom.
* Result panel: closed? · #solids · volume vs mesh · max/RMS/P95 deviation · timings.
* Download **STEP** / **BREP** / **ZIP**.

Conversions run in a child process with a wall-clock watchdog, so a mesh that
wedges OpenCASCADE fails cleanly instead of hanging the server.

## Desktop GUI (offline fallback)

```bash
conda activate stl2cad
python -m app.main               # or "STL2CAD GUI.bat"
```

PySide6 window with the same pipeline, an OCC 3-D view, and **Export STEP…**.

## Command line

```bash
python -m stl2cad part.stl                      # -> ./out/part.stp
python -m stl2cad *.stl -o converted --tol 0.3  # batch, tighter analytic tol
python -m stl2cad part.stl --faces 80000 --dihedral 15 --method faceted
```

| flag | meaning | default |
|---|---|---|
| `--tol` | max deviation to accept an analytic face (mm) | 0.5 |
| `--faces` | decimation target triangle count | 60000 |
| `--dihedral` | region-growing angle limit (deg) | 18 |
| `--method` | `faceted`, `arcwise`, `hybrid` | faceted |
| `--arc-simplify` | boundary-arc simplification (mm, `arcwise`) | 0.15 |
| `--no-export` | analyse only | – |

## Benchmark

```bash
python -m tests.bench --faces 50000
```

Runs every `*.stl` that has a sibling reference `*.stp`, compares face-type
histogram / volume / deviation, and writes `bench_report.html`.

## How it works

| stage | module | what it does |
|---|---|---|
| web UI | `webapp/` | FastAPI server + three.js front end (`python -m webapp`) |
| load | `io_mesh` | read STL, weld vertices |
| heal | `heal` | repair non-manifold, close holes, quadric-decimate |
| segment | `segment` + `refine` | region-grow by dihedral angle, then split blended patches / merge co-primitive patches |
| fit | `primitives` + `fit` | least-squares plane/cylinder/cone/sphere/torus per patch |
| build | `topology` | analytic face per good patch, shared triangles elsewhere → sew → solid → `UnifySameDomain` |
| validate | `validate` | closed check, volume vs mesh, sampled surface deviation |
| export | `export` | STEP AP242 (unit = mm), BREP, IGES |

## Known limitations

* Output for organic / high-detail regions stays faceted (many small planar
  faces). B-spline surface fitting for those regions is the next step.
* Very large STLs are decimated hard; sub-0.5 mm on fine detail is not guaranteed
  — the bench report shows per-part deviation.
* Direct Parasolid (`.x_t`) output needs a licensed Siemens SDK and is not
  included; use the STEP → NX route.
