import numpy as np
import pytest

from stl2cad.primitives import (
    fit_plane,
    fit_sphere,
    fit_cylinder,
    fit_cone,
    fit_torus,
    best_fit,
)

RNG = np.random.default_rng(42)


def _noise(pts, sigma=0.01):
    return pts + RNG.normal(0, sigma, pts.shape)


def test_plane():
    xy = RNG.uniform(-10, 10, (500, 2))
    pts = _noise(np.c_[xy, np.full(len(xy), 3.0)])
    f = fit_plane(pts)
    assert f.max_dev < 0.05
    assert abs(abs(f.params["normal"][2]) - 1) < 1e-3


def test_sphere():
    v = _unit = RNG.normal(size=(600, 3))
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    pts = _noise(np.array([5.0, -2.0, 1.0]) + 7.5 * v)
    f = fit_sphere(pts)
    assert abs(f.params["radius"] - 7.5) < 0.05
    assert f.max_dev < 0.06


def test_cylinder():
    theta = RNG.uniform(0, 2 * np.pi, 800)
    z = RNG.uniform(0, 30, 800)
    r = 4.0
    local = np.c_[r * np.cos(theta), r * np.sin(theta), z]
    normals = np.c_[np.cos(theta), np.sin(theta), np.zeros_like(theta)]
    f = fit_cylinder(_noise(local), normals)
    assert abs(f.params["radius"] - r) < 0.05
    assert f.max_dev < 0.08


def test_cone():
    z = RNG.uniform(1, 20, 900)
    theta = RNG.uniform(0, 2 * np.pi, 900)
    ha = np.radians(20)
    rad = z * np.tan(ha)
    pts = np.c_[rad * np.cos(theta), rad * np.sin(theta), z]
    f = fit_cone(_noise(pts))
    assert f is not None
    assert abs(np.degrees(f.params["half_angle"]) - 20) < 1.5


def test_torus():
    u = RNG.uniform(0, 2 * np.pi, 1500)
    v = RNG.uniform(0, 2 * np.pi, 1500)
    R, r = 12.0, 3.0
    pts = np.c_[
        (R + r * np.cos(v)) * np.cos(u),
        (R + r * np.cos(v)) * np.sin(u),
        r * np.sin(v),
    ]
    f = fit_torus(_noise(pts))
    assert f is not None
    assert abs(f.params["major_radius"] - R) < 0.2
    assert abs(f.params["minor_radius"] - r) < 0.2


def test_best_fit_prefers_plane():
    xy = RNG.uniform(-5, 5, (400, 2))
    pts = _noise(np.c_[xy, np.zeros(len(xy))], 0.005)
    f = best_fit(pts, None, tol=0.5, try_types=("plane", "cylinder", "cone", "sphere", "torus"))
    assert f.kind == "plane"
