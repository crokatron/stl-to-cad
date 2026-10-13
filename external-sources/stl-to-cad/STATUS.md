# Project status — v0.1  (2026-09-01)

## What you can rely on today

`python -m stl2cad part.stl` (method **`faceted`**, the default) turns an STL
into a **closed solid whose volume matches the mesh exactly (0 mm deviation)**
and writes it as STEP + BREP. NX imports the STEP and converts it to a native
Parasolid body. The output is heavy (one face per mesh triangle, tens of MB for
large parts) but it is geometrically correct and watertight.

| sample | result | notes |
|---|---|---|
| BED BLOCK | ✅ closed solid, vol err 0 % vs its own mesh | its reference `.stp` is a much finer model, so hist/volume differ from it |
| 3090_1 | ✅ closed solid, vol err 0 % vs mesh | ~30 k faces, ~40 MB STEP |
| VICE STOAGE_3 | ✅ (expected) | large, heavy STEP |
| fdm drying rack | ✅ 2 closed solids, vol err 0 % | matches reference volume to 0.07 % |
| TOWER FAN FILTER_1 | ⛔ **refused with a clear message** | 1.5 M-triangle grille; heals watertight but won't decimate below ~147 k (irreducible thin-slat edges), which is over the `max_build_faces` ceiling. Pre-decimate the STL in a mesh tool and retry. |

`pytest` (8/8): primitive fits + box & cylinder STL→STEP→re-read round-trips pass.

## The `arcwise` method (`--method arcwise`) — experimental

Segments the mesh, fits real plane/cylinder/cone/sphere/torus surfaces (plus a
plate surface for freeform patches), and rebuilds a **compact** B-rep. Decimation
is auto-relaxed for this method so small holes aren't crushed. Runs in ~10–25 s.

* **Round holes work.** On `Lego+Car+Mount+v3` it recognises all **221 array
  holes + 3 counterbores as true Ø5 mm cylinders** (P95 deviation ~1.5 mm),
  visible as blue in the **"By type"** view.
* **It usually doesn't fully seal.** Parametric (cylinder/cone/…) faces can't
  share the boundary edges of their planar neighbours, so the result imports as a
  **sheet body** — one "Sew/Heal" in NX closes it. The result panel says so.
* **Faces it can't fit** (a hole-lined fillet strip, a face pierced by 100+
  holes) are kept as small faceted islands and show up plainly in the type view.
* Runaway surface fits are bbox-checked and discarded rather than exported.

Next: give parametric faces proper seam edges so they share topology and the
shell closes without sewing; recognise constant-radius fillets as cylinders/tori.

## Front ends

* **Web UI** (recommended) — `python -m webapp` / `STL2CAD Web.bat` → browser at
  `localhost:8765`. FastAPI + three.js, runs entirely local. Drag-drop or pick a
  sample, live progress, interactive 3-D (solid / input-mesh / deviation
  heat-map), STEP/BREP/ZIP download. Conversions run in a child process with a
  wall-clock watchdog so a wedged mesh fails cleanly. Verified end-to-end on
  BED BLOCK, drying rack, and 3090_1.
* **Desktop GUI** — `python -m app.main` / `STL2CAD GUI.bat`. PySide6 + OCC
  viewer, same pipeline. Needs a real desktop GPU.

## Next session — priority order

1. **`arcwise` edge sharing** — build each face with a low-level
   `BRep_Builder.MakeFace` + explicit pcurve so the arc edges stay shared and the
   shell closes with no sew. (Earlier attempt segfaulted in
   `breplib.BuildCurves3d`; needs care.)
2. **TOWER FAN-class meshes** — a decimation path that actually reduces dense
   grilles (pymeshlab's quadric filter is a no-op in this build; try
   `pyvista`/VTK `decimate_pro`, or voxel-remesh).
3. **Curvature-aware segmentation** so fillets become tori/cylinders instead of
   being swallowed into freeform patches.
4. **AP242 schema** — `write.step.schema` isn't taking (writes AP214).
5. Build & smoke-test the PyInstaller `.exe`.

## Feedback loop

Drop STL + reference STP pairs in the project folder, run `python -m tests.bench`,
send `bench_report.html`.
