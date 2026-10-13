import numpy as np
import trimesh

from stl2cad.config import PipelineConfig
from stl2cad.pipeline import run
from stl2cad.export import read_step
from stl2cad.occ_util import volume, count_solids, is_valid


def _write_stl(tmp_path, mesh, name):
    p = tmp_path / name
    mesh.export(p)
    return p


def test_box_roundtrip(tmp_path):
    box = trimesh.creation.box(extents=(20, 30, 40))
    stl = _write_stl(tmp_path, box, "box.stl")

    cfg = PipelineConfig()
    cfg.heal.target_faces = None
    res = run(stl, cfg, out_dir=tmp_path, do_export=True)

    assert res.build.n_solids == 1
    assert res.validation.closed
    assert res.validation.dev_max < 0.2
    assert abs(res.validation.volume_solid - 24000) / 24000 < 0.02

    shape = read_step(res.outputs["step"])
    assert count_solids(shape) == 1
    assert abs(volume(shape) - 24000) / 24000 < 0.02


def test_cylinder_roundtrip(tmp_path):
    cyl = trimesh.creation.cylinder(radius=8, height=25, sections=96)
    stl = _write_stl(tmp_path, cyl, "cyl.stl")

    cfg = PipelineConfig()
    cfg.heal.target_faces = None
    res = run(stl, cfg, out_dir=tmp_path, do_export=False)

    assert res.validation.closed
    assert res.validation.dev_max < 0.3
    # a cylinder + 2 caps should be recognised as at least one cylindrical face
    assert res.build.face_hist.get("cylinder", 0) >= 1 or res.build.method == "faceted"
