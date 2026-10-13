"""Command-line entry point:  python -m stl2cad file1.stl [file2.stl ...]"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import DEFAULT
from .pipeline import run


def main(argv=None):
    ap = argparse.ArgumentParser(prog="stl2cad", description=__doc__)
    ap.add_argument("inputs", nargs="+", help="STL file(s) or a directory")
    ap.add_argument("-o", "--out", default=None, help="output directory")
    ap.add_argument("--tol", type=float, default=DEFAULT.fit.analytic_tol,
                    help="analytic acceptance tolerance, mm (default 0.5)")
    ap.add_argument("--faces", type=int, default=DEFAULT.heal.target_faces,
                    help="decimation target triangle count")
    ap.add_argument("--dihedral", type=float, default=DEFAULT.segment.dihedral_deg,
                    help="region-grow dihedral limit, degrees")
    ap.add_argument("--method", default=DEFAULT.build.method,
                    choices=["arcwise", "hybrid", "faceted"])
    ap.add_argument("--arc-simplify", type=float, default=DEFAULT.build.arc_simplify,
                    help="boundary-arc simplification tolerance, mm")
    ap.add_argument("--no-export", action="store_true")
    args = ap.parse_args(argv)

    cfg = DEFAULT
    cfg.fit.analytic_tol = args.tol
    cfg.heal.target_faces = args.faces
    cfg.segment.dihedral_deg = args.dihedral
    cfg.build.method = args.method
    cfg.build.arc_simplify = args.arc_simplify

    files: list[Path] = []
    for item in args.inputs:
        p = Path(item)
        if p.is_dir():
            files.extend(sorted(p.glob("*.stl")))
        else:
            files.append(p)

    rc = 0
    for f in files:
        if not f.exists():
            print(f"!! missing: {f}", file=sys.stderr)
            rc = 1
            continue
        print(f"\n=== {f.name} ===")
        try:
            res = run(f, cfg, out_dir=args.out, do_export=not args.no_export)
            print(res.summary())
            if res.outputs:
                print("  output  :", ", ".join(f"{k}={v}" for k, v in res.outputs.items()))
            if not res.validation.passed:
                rc = 2
        except Exception as exc:
            import traceback
            traceback.print_exc()
            print(f"!! failed: {f.name}: {exc}", file=sys.stderr)
            rc = 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
