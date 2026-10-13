"""Tunable parameters for the reconstruction pipeline.

All lengths are in millimetres (STL input is assumed to be mm).
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict


@dataclass
class HealConfig:
    # Vertices closer than this are welded together.
    merge_distance: float = 1.0e-3
    # Fill holes whose boundary loop has at most this many edges.
    max_hole_edges: int = 60
    # Target triangle count after quadric decimation. None = keep as-is.
    # Meshes below `decimate_skip_below` triangles are never decimated.
    target_faces: int | None = 60_000
    decimate_skip_below: int = 20_000
    # Preserve boundaries / topology during decimation.
    preserve_boundary: bool = True


@dataclass
class SegmentConfig:
    # Region growing stops at edges whose dihedral angle exceeds this (degrees).
    dihedral_deg: float = 18.0
    # Secondary guard: stop where estimated curvature changes sharply.
    curvature_ratio: float = 3.0
    # Patches with fewer triangles than this are merged into a neighbour.
    min_patch_faces: int = 12
    # Normal-clustering pre-pass bucket size (degrees) to seed regions.
    normal_bucket_deg: float = 10.0
    # Run the split/merge refinement pass after region growing.
    refine: bool = True


@dataclass
class FitConfig:
    # A primitive fit is accepted when the max point deviation is <= this.
    analytic_tol: float = 0.5
    # Preferred target; fits under this are considered "clean".
    target_tol: float = 0.2
    # RANSAC iterations for cylinder/cone/sphere axis seeding.
    ransac_iters: int = 200
    # Two adjacent analytic patches are merged when a joint refit stays under this.
    merge_tol: float = 0.5
    # Order in which primitive types are tried; first acceptable & simplest wins,
    # ties broken by lower DOF (plane < cylinder < cone < sphere < torus).
    try_types: tuple[str, ...] = ("plane", "cylinder", "cone", "sphere", "torus")


@dataclass
class BuildConfig:
    # Sewing tolerance for stitching faces into a shell.
    sew_tol: float = 0.50
    # Fixed tolerance applied to fitted geometry before sewing.
    shape_tol: float = 1.0e-2
    # Try to unify coplanar / cocylindrical faces after sewing.
    unify: bool = True
    # Angular tolerance (radians) for merging near-coplanar faceted triangles
    # into a single planar face. ~2 deg copes with print/scan wobble.
    unify_angular_tol: float = 0.035
    unify_linear_tol: float = 1.0e-3
    # Fit one plate/B-spline face to freeform patches instead of keeping their
    # triangles (smaller output but BRepOffsetAPI_MakeFilling is slow; off by
    # default). Only attempted for patches with <= this many boundary vertices.
    freeform_filling: bool = False
    freeform_filling_max_boundary: int = 80
    # Above this many faces the (slow) sewing pass is skipped.
    sew_face_limit: int = 9000
    # Above this many faceted faces, skip the (slow) coplanar-face merge.
    faceted_polish_limit: int = 14000
    # Above this many faceted faces, skip ShapeFix too (and warn). Kept equal to
    # max_build_faces so every accepted mesh is orientation-fixed.
    faceted_shapefix_limit: int = 95000
    # Hard ceiling: if the healed mesh still exceeds this, the pipeline refuses
    # (rather than hanging OCC). Decimate the STL externally first.
    max_build_faces: int = 90000
    # If sewing fails to close, fall back to a faceted solid from the mesh.
    faceted_fallback: bool = True
    # Build method:
    #   "faceted" - every triangle as a face (reliable, closes, heavy output)
    #   "arcwise" - one simplified shared edge per patch-boundary arc, one face
    #               per patch (compact analytic output; EXPERIMENTAL - may leave
    #               gaps or run slowly on some meshes)
    #   "hybrid"  - analytic faces + raw triangles for the rest
    method: str = "faceted"
    # Wall-clock budget (s) for the arcwise builder before it bails out.
    arcwise_budget_s: float = 90.0
    # Douglas-Peucker tolerance (mm) for simplifying boundary arcs.
    arc_simplify: float = 0.15


@dataclass
class ValidateConfig:
    # Number of sample points per face used for deviation measurement.
    samples_per_face: int = 400
    # Overall pass threshold for max deviation.
    pass_max_dev: float = 0.5
    # Acceptable relative volume error (fraction).
    pass_volume_rel: float = 0.02


@dataclass
class ExportConfig:
    # "AP242DIS" (AP242) or "AP214IF" or "AP203".
    step_schema: str = "AP242DIS"
    unit: str = "MM"
    write_brep: bool = True
    write_iges: bool = False


@dataclass
class PipelineConfig:
    heal: HealConfig = field(default_factory=HealConfig)
    segment: SegmentConfig = field(default_factory=SegmentConfig)
    fit: FitConfig = field(default_factory=FitConfig)
    build: BuildConfig = field(default_factory=BuildConfig)
    validate: ValidateConfig = field(default_factory=ValidateConfig)
    export: ExportConfig = field(default_factory=ExportConfig)

    def to_dict(self) -> dict:
        return asdict(self)


DEFAULT = PipelineConfig()
