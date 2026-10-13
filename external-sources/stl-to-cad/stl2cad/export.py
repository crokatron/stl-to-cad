"""Write reconstructed solids to STEP / BREP / IGES."""

from __future__ import annotations

from pathlib import Path

from OCC.Core.STEPControl import STEPControl_Writer, STEPControl_Reader, STEPControl_AsIs
from OCC.Core.IGESControl import IGESControl_Writer
from OCC.Core.Interface import Interface_Static
from OCC.Core.IFSelect import IFSelect_RetDone
from OCC.Core.BRepTools import breptools

from .config import ExportConfig

_SCHEMA_MAP = {
    "AP242DIS": "AP242DIS",
    "AP242": "AP242DIS",
    "AP214IF": "AP214IF",
    "AP214": "AP214IF",
    "AP203": "AP203",
}


def write_step(shape, path: str | Path, cfg: ExportConfig) -> Path:
    path = Path(path)
    Interface_Static.SetCVal("write.step.schema", _SCHEMA_MAP.get(cfg.step_schema, "AP242DIS"))
    Interface_Static.SetCVal("write.step.unit", cfg.unit)
    Interface_Static.SetIVal("write.step.nonmanifold", 0)
    w = STEPControl_Writer()
    w.Transfer(shape, STEPControl_AsIs)
    if w.Write(str(path)) != IFSelect_RetDone:
        raise RuntimeError(f"STEP write failed: {path}")
    return path


def write_brep(shape, path: str | Path) -> Path:
    path = Path(path)
    breptools.Write(shape, str(path))
    return path


def write_iges(shape, path: str | Path, unit: str = "MM") -> Path:
    path = Path(path)
    Interface_Static.SetCVal("write.iges.unit", unit)
    w = IGESControl_Writer(unit, 0)
    w.AddShape(shape)
    w.ComputeModel()
    if not w.Write(str(path)):
        raise RuntimeError(f"IGES write failed: {path}")
    return path


def read_step(path: str | Path):
    r = STEPControl_Reader()
    if r.ReadFile(str(path)) != IFSelect_RetDone:
        raise RuntimeError(f"cannot read {path}")
    r.TransferRoots()
    return r.OneShape()


def export_all(shape, out_stem: str | Path, cfg: ExportConfig) -> dict[str, Path]:
    out_stem = Path(out_stem)
    written = {"step": write_step(shape, out_stem.with_suffix(".stp"), cfg)}
    if cfg.write_brep:
        written["brep"] = write_brep(shape, out_stem.with_suffix(".brep"))
    if cfg.write_iges:
        written["iges"] = write_iges(shape, out_stem.with_suffix(".igs"), cfg.unit)
    return written
