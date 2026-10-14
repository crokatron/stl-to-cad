# STL to CAD Converter: maintainer handover

[One-screen summary](START-HERE.md) · [User manual](USER-MANUAL.md) · [Feature overview](../README.md) · [Recorded validation](../VALIDATION.md)

## Purpose and behaviour to preserve

Convert a triangle mesh into CAD boundary geometry and inspect the result before downloading STEP or BREP. The reliable faceted method follows triangles and may produce a heavy model; experimental analytic methods try to make a more compact representation. Conversion does not recreate the original designer’s feature tree.

- **Mesh input:** Upload an STL; the hosted route enforces a 32 MB limit. (Conversion workflow.)
- **Method selection:** Faceted, arcwise and hybrid strategies with different fidelity, size and robustness tradeoffs. (Conversion workflow.)
- **Controls:** Analytic tolerance, decimation target, dihedral threshold, arc simplification and refinement. (Conversion workflow.)
- **Inspection:** Solid, Input mesh, Deviation, By type and Wireframe views. (Conversion workflow.)
- **Validation:** Review closure, solid count, volume/deviation information and timings when available. (Conversion workflow.)
- **Downloads:** Export STEP, BREP and result archives for downstream CAD work. (Conversion workflow.)

The [demo](../demo.html) is a smaller, labelled simulation with fictional data. It explains cause and effect without the real service; it is not evidence of a working production installation. Numbered screenshots in the user manual distinguish actual-app captures from demo captures.

## Files and sources of truth

| Actual package path | Maintainer role |
| --- | --- |
| [external-sources/stl-to-cad/README.md](../external-sources/stl-to-cad/README.md) | Methods, limits and setup |
| [external-sources/stl-to-cad/environment.yml](../external-sources/stl-to-cad/environment.yml) | Conda environment |
| [external-sources/stl-to-cad/webapp](../external-sources/stl-to-cad/webapp) | Web front end/service |
| [external-sources/stl-to-cad/tests](../external-sources/stl-to-cad/tests) | Primitive and round-trip checks |
| [demo-source](../demo-source) | Editable demo HTML/CSS/runtime and embedded screenshot tour |
| [SOURCE-MANIFEST.json](../SOURCE-MANIFEST.json) | Original copied-source paths and SHA-256 checkpoint values |

The original working source is under C:/Users/lamon/Desktop/AI TOOLS/NAS for NAS modules; adjacent CAD/watch source locations are recorded by the full backup’s reviewed source manifest. This package contains only the explicitly copied source, not an automatic mirror. The main private nas-projects backup retains the broader shared host context.

## Setup, run and tests

Run commands from this repository root unless a `cd` is shown. Use a disposable checkout and fictional data for first setup. Dependencies, SDKs, signing material and personal data are not bundled. The following are continuation instructions grounded in the retained source, **not commands executed or newly certified by this handover**.

```powershell
cd external-sources/stl-to-cad
conda env create -f environment.yml
conda activate stl2cad
python -m webapp
```

Use the address printed by the configured local web app.

Selected project check:

```powershell
cd external-sources/stl-to-cad
conda activate stl2cad
python -m pytest tests/test_primitives.py
```

For the documentation demo alone, serve this repository on loopback with `python -m http.server 8765 --bind 127.0.0.1` and open `/demo.html`. Choose a free port if another preview is running. JavaScript syntax can be checked with `node --check demo-source/runtime.js`. `python demo-source/rebuild.py` rewrites demo.html, so run it only in a disposable checkout or an authorised demo-editing session. A local server cannot provide missing HA/CAD/NAS functions. Inspect browser tests for installed dependencies, fixture requirements and network targets before running them with the approved browser tooling.

## Data, configuration and backup boundaries

Original meshes and reference STEP files are user assets and excluded. Downloads and temporary jobs are not durable source backup. The OpenCascade/pythonocc environment is required; a static HTTP server cannot convert a model.

Treat conversion jobs as temporary working results and download the outputs you need. The source repository does not contain uploaded meshes or the NAS job store. Back up original meshes independently.

Git preserves reviewed source and documentation. It does not copy browser storage, application databases, uploaded models/photos, accepted device settings, SDKs or credentials. Maintain independent recovery copies of the data identified above, including matching configuration and asset versions. Never add real secrets to examples, issues or logs. Private source copies on GitHub are not proof of a complete NAS/offsite data backup.

## Current verification and Git state

Before these documentation edits on 14 October 2026, this package was clean on branch `main` at `482647c088449af14b92fe181d2825d9db0197a3` and its private upload was verified. All 46 manifest-listed source entries matched their stored checksums before editing. The upload follow-up has completed all 17 repositories and is paused; it does not run this tool or back up its live data.

These handover pages and README links accompany the private source package. Preserve them when continuing; stage only reviewed changes. Recheck current `git status --short --branch` and `git diff` before starting. No project-specific background schedule was inspected or changed in this documentation pass. Any service schedules in older notes are historical claims to verify in the actual deployment.

Earlier package checks and limits are recorded in [VALIDATION.md](../VALIDATION.md). This handover adds documentation/link/whitespace/secret and source-preservation checks only. No current NAS release, real hardware state, fresh installation, complete data restoration or offsite-backup freshness was verified here.

## Recovery approach

1. Preserve the current installation/data before changing it. Identify the exact code commit and data snapshot required; do not assume this package matches the running service.
2. Recover source into a new folder. Verify the source manifest and restore the project-specific configuration/assets described above separately. Recreate dependencies from the retained project files and guides.
3. Restore user data into an isolated instance or clean test browser. Check a representative editable record, associated files and save/reload behaviour, then compare to the original. Do not test recovery by overwriting production.
4. Record what actually restored and what remains missing. A demo opening or a passing syntax check is not a production recovery drill. Real deployment/device actions need the existing authorised workflow.

## Known limits and next work

A local static server cannot perform CAD conversion. The package needs the configured OpenCascade/Python environment or the NAS conversion service. No new full CAD integration test was performed for this documentation update.

**Priority:** Run primitive/round-trip fixtures in the actual CAD environment and inspect topology/deviation for representative meshes. Preserve source meshes before decimation; do not promise the original CAD feature tree or analytic success for every mesh.

Common symptoms to check for this tool:

- Dense mesh stalls or fails: reduce triangle count intentionally and try a smaller representative section.
- Open edges: repair the input or inspect the experimental method’s output as a sheet.
- Unexpected size: verify source units and CAD import units.
- Heavy STEP: normal for triangle-per-face conversion; compact fitting is a separate tradeoff.

Keep [the release checklist](../RELEASE-CHECKLIST.md) and [third-party notes](../THIRD-PARTY.md) with the package. Original contributions use MIT; bundled/upstream code and assets keep their own licences. Public publication is a separate decision; preparing documentation is not permission to publish.
