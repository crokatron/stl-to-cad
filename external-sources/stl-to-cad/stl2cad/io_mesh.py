"""STL loading and basic mesh statistics."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import trimesh


@dataclass
class MeshStats:
    path: str
    n_vertices: int
    n_faces: int
    is_watertight: bool
    is_winding_consistent: bool
    euler_number: int
    bbox_min: tuple[float, float, float]
    bbox_max: tuple[float, float, float]
    area: float
    volume: float | None
    n_bodies: int

    def summary(self) -> str:
        dx, dy, dz = (np.array(self.bbox_max) - np.array(self.bbox_min))
        vol = f"{self.volume:.1f}" if self.volume is not None else "n/a"
        return (
            f"{Path(self.path).name}: {self.n_faces:,} tris, {self.n_bodies} body(ies), "
            f"bbox {dx:.1f}x{dy:.1f}x{dz:.1f} mm, area {self.area:.1f}, vol {vol}, "
            f"watertight={self.is_watertight}"
        )


def load_mesh(path: str | Path) -> trimesh.Trimesh:
    """Load an STL and merge coincident vertices (STL stores every triangle loose)."""
    obj = trimesh.load(str(path), force="mesh", process=False)
    if isinstance(obj, trimesh.Scene):
        obj = trimesh.util.concatenate(tuple(obj.geometry.values()))
    if not isinstance(obj, trimesh.Trimesh):
        raise ValueError(f"{path}: not a triangle mesh")
    obj.merge_vertices()
    obj.remove_unreferenced_vertices()
    return obj


def mesh_stats(mesh: trimesh.Trimesh, path: str | Path = "") -> MeshStats:
    try:
        n_bodies = int(mesh.body_count)
    except Exception:
        n_bodies = 1
    try:
        vol = float(mesh.volume) if mesh.is_watertight else None
    except Exception:
        vol = None
    return MeshStats(
        path=str(path),
        n_vertices=int(len(mesh.vertices)),
        n_faces=int(len(mesh.faces)),
        is_watertight=bool(mesh.is_watertight),
        is_winding_consistent=bool(mesh.is_winding_consistent),
        euler_number=int(mesh.euler_number),
        bbox_min=tuple(float(v) for v in mesh.bounds[0]),
        bbox_max=tuple(float(v) for v in mesh.bounds[1]),
        area=float(mesh.area),
        volume=vol,
        n_bodies=n_bodies,
    )
