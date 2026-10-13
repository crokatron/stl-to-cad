"""Benchmark the pipeline over every STL that has a sibling reference .stp.

    python -m tests.bench [--dir .] [--faces 60000] [--tol 0.5]

Writes bench_report.html and prints a summary table.
"""

from __future__ import annotations

import argparse
import html
import time
from pathlib import Path

from stl2cad.config import PipelineConfig
from stl2cad.pipeline import run
from stl2cad.report import compare_to_reference


def _ref_for(stl: Path) -> Path | None:
    for cand in (stl.with_suffix(".stp"), stl.with_suffix(".step"),
                 stl.parent / (stl.stem.split("_")[0] + ".stp")):
        if cand.exists():
            return cand
    hits = list(stl.parent.glob(stl.stem.rsplit("_", 1)[0] + "*.stp"))
    return hits[0] if hits else None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=".")
    ap.add_argument("--faces", type=int, default=60_000)
    ap.add_argument("--tol", type=float, default=0.5)
    ap.add_argument("--method", default="hybrid")
    args = ap.parse_args(argv)

    cfg = PipelineConfig()
    cfg.heal.target_faces = args.faces
    cfg.fit.analytic_tol = args.tol
    cfg.build.method = args.method

    root = Path(args.dir)
    stls = sorted(root.glob("*.stl"))
    rows = []
    for stl in stls:
        ref = _ref_for(stl)
        print(f"\n### {stl.name}   (ref: {ref.name if ref else '—'})")
        t0 = time.time()
        try:
            res = run(stl, cfg, out_dir=root / "out")
        except Exception as exc:
            import traceback
            traceback.print_exc()
            rows.append((stl.name, None, None, str(exc), time.time() - t0))
            continue
        cmp = compare_to_reference(res.shape, ref) if ref else None
        print(res.summary())
        if cmp:
            print(cmp.table())
        rows.append((stl.name, res, cmp, None, time.time() - t0))

    _write_html(root / "bench_report.html", rows)
    print(f"\nwrote {root / 'bench_report.html'}")

    print(f"\n{'file':32s} {'closed':7s} {'devmax':>7s} {'vol%':>7s} {'ourF':>6s} {'refF':>6s} {'t(s)':>6s}")
    for name, res, cmp, err, dt in rows:
        if res is None:
            print(f"{name:32s} ERROR {err}")
            continue
        v = res.validation
        ourf = sum(res.build.face_hist.values())
        reff = sum(cmp.ref_hist.values()) if cmp else 0
        print(f"{name:32s} {str(v.closed):7s} {v.dev_max:7.3f} "
              f"{v.volume_rel_err*100:7.2f} {ourf:6d} {reff:6d} {dt:6.1f}")


def _write_html(path: Path, rows):
    cells = []
    for name, res, cmp, err, dt in rows:
        if res is None:
            cells.append(f"<tr><td>{html.escape(name)}</td><td colspan=8>ERROR: {html.escape(str(err))}</td></tr>")
            continue
        v = res.validation
        b = res.build
        ok = "#1b5e20" if v.passed else "#b71c1c"
        refhist = cmp.ref_hist if cmp else {}
        cells.append(
            f"<tr><td>{html.escape(name)}</td>"
            f"<td>{res.stats.n_faces:,}→{res.healed_faces:,}</td>"
            f"<td>{b.method}</td>"
            f"<td>{res.n_patches}</td>"
            f"<td>{b.n_solids}</td>"
            f"<td style='color:{ok}'>{'PASS' if v.passed else 'FAIL'}</td>"
            f"<td>{v.dev_max:.3f}/{v.dev_rms:.3f}</td>"
            f"<td>{v.volume_rel_err*100:.2f}%</td>"
            f"<td>{b.face_hist}</td>"
            f"<td>{refhist}</td>"
            f"<td>{dt:.1f}</td></tr>"
        )
    doc = f"""<!doctype html><meta charset=utf8>
<title>stl2cad bench</title>
<style>body{{font:13px system-ui;margin:24px}}table{{border-collapse:collapse}}
td,th{{border:1px solid #ccc;padding:4px 8px}}th{{background:#eee}}</style>
<h2>stl2cad benchmark</h2>
<table><tr><th>file</th><th>tris</th><th>method</th><th>patches</th><th>solids</th>
<th>result</th><th>dev max/rms mm</th><th>vol err</th><th>our faces</th>
<th>ref faces</th><th>t (s)</th></tr>
{''.join(cells)}
</table>"""
    path.write_text(doc, encoding="utf8")


if __name__ == "__main__":
    main()
