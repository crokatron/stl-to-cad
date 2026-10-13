"""Compare a reconstructed solid against a reference STEP file."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .export import read_step
from .occ_util import volume, count_solids, face_kind_histogram


@dataclass
class RefComparison:
    ref_path: str
    ref_solids: int
    ref_volume: float
    ref_hist: dict
    our_solids: int
    our_volume: float
    our_hist: dict
    volume_rel_err: float

    def table(self) -> str:
        keys = sorted(set(self.ref_hist) | set(self.our_hist))
        rows = [f"  {'type':10s} {'ours':>6s} {'ref':>6s}"]
        for k in keys:
            rows.append(f"  {k:10s} {self.our_hist.get(k, 0):6d} {self.ref_hist.get(k, 0):6d}")
        rows.append(f"  {'FACES':10s} {sum(self.our_hist.values()):6d} "
                    f"{sum(self.ref_hist.values()):6d}")
        rows.append(f"  volume err vs ref: {self.volume_rel_err*100:.2f}%")
        return "\n".join(rows)


def compare_to_reference(our_shape, ref_step: str | Path) -> RefComparison | None:
    ref_step = Path(ref_step)
    if not ref_step.exists():
        return None
    try:
        ref = read_step(ref_step)
    except Exception:
        return None
    rv = abs(volume(ref))
    ov = abs(volume(our_shape)) if our_shape is not None else 0.0
    return RefComparison(
        ref_path=str(ref_step),
        ref_solids=count_solids(ref),
        ref_volume=rv,
        ref_hist=face_kind_histogram(ref),
        our_solids=count_solids(our_shape) if our_shape is not None else 0,
        our_volume=ov,
        our_hist=face_kind_histogram(our_shape) if our_shape is not None else {},
        volume_rel_err=abs(ov - rv) / rv if rv > 0 else 1.0,
    )
