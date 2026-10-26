"""Earplug geometry: scan cleanup and a two-part pour mold. All units are millimetres."""

from __future__ import annotations

import numpy as np
import trimesh
import pymeshfix
from trimesh.creation import box, cylinder, icosphere


def _union(meshes: list[trimesh.Trimesh]) -> trimesh.Trimesh:
    return trimesh.boolean.union(meshes, engine="manifold")


def _difference(a: trimesh.Trimesh, b: trimesh.Trimesh) -> trimesh.Trimesh:
    return trimesh.boolean.difference([a, b], engine="manifold")


def _intersection(a: trimesh.Trimesh, b: trimesh.Trimesh) -> trimesh.Trimesh:
    return trimesh.boolean.intersection([a, b], engine="manifold")


def _sphere(radius: float, center) -> trimesh.Trimesh:
    s = icosphere(subdivisions=3, radius=radius)
    s.apply_translation(center)
    return s


def sample_plug() -> trimesh.Trimesh:
    """Synthetic earplug shape (concha bowl + bent canal stem along +Z) for testing without a real scan."""
    bowl = icosphere(subdivisions=4, radius=1.0)
    bowl.apply_scale([11.0, 8.0, 6.0])
    centers = np.array([(0, 0, 3), (2, 0, 9), (3, 1, 14), (2.5, 2, 18)], dtype=float)
    radii = [4.5, 4.0, 3.6, 3.2]
    segments = [
        trimesh.convex.convex_hull(
            np.vstack([_sphere(r0, c0).vertices, _sphere(r1, c1).vertices])
        )
        for c0, c1, r0, r1 in zip(centers, centers[1:], radii, radii[1:])
    ]
    return _union([bowl, *segments])


def clean_scan(mesh: trimesh.Trimesh | trimesh.Scene, longest_mm: float | None = None) -> trimesh.Trimesh:
    """Keep the largest piece of a phone scan, close its holes, optionally rescale, and centre it at the origin."""
    if isinstance(mesh, trimesh.Scene):
        mesh = mesh.to_geometry()
    vertices, faces = pymeshfix.clean_from_arrays(
        np.ascontiguousarray(mesh.vertices, dtype=np.float64),
        np.ascontiguousarray(mesh.faces, dtype=np.int32),
    )
    mesh = trimesh.Trimesh(vertices, faces)
    if not mesh.is_watertight:
        raise ValueError("scan still has holes after repair; rescan with more overlap")
    if longest_mm is not None:
        mesh.apply_scale(longest_mm / mesh.extents.max())
    mesh.apply_translation(-mesh.bounds.mean(axis=0))
    return mesh


def make_mold(
    plug: trimesh.Trimesh,
    wall: float = 6.0,
    sprue_d: float = 4.0,
    air_d: float = 1.5,
    key_r: float = 2.0,
    key_clearance: float = 0.2,
) -> tuple[trimesh.Trimesh, trimesh.Trimesh]:
    """Two mold halves split on the XZ plane through the plug centre.

    Silicone is poured through a sprue on the -X face (bowl rim) and air escapes through a vent
    on the +Z face (canal tip). Half A carries registration bumps; half B the matching sockets.
    """
    if key_r * 2 >= wall:
        raise ValueError("key_r must leave material in the wall: need 2*key_r < wall")
    lo = plug.bounds[0] - wall
    hi = plug.bounds[1] + wall
    block = box(extents=hi - lo)
    block.apply_translation((hi + lo) / 2)

    v = plug.vertices
    rim = v[np.argmin(v[:, 0])]
    tip = v[np.argmax(v[:, 2])]
    sprue = cylinder(radius=sprue_d / 2, segment=[(lo[0] - 1, rim[1], rim[2]), (rim[0] + 2, rim[1], rim[2])])
    air = cylinder(radius=air_d / 2, segment=[(tip[0], tip[1], tip[2] - 2), (tip[0], tip[1], hi[2] + 1)])
    cavity = _difference(block, _union([plug, sprue, air]))

    split_y = (lo[1] + hi[1]) / 2
    size = hi - lo + 2
    side_a = box(extents=size)
    side_a.apply_translation(((hi[0] + lo[0]) / 2, split_y - size[1] / 2, (hi[2] + lo[2]) / 2))
    side_b = side_a.copy()
    side_b.apply_translation((0, size[1], 0))
    half_a = _intersection(cavity, side_a)
    half_b = _intersection(cavity, side_b)

    inset = wall / 2
    corners = [(x, split_y, z) for x in (lo[0] + inset, hi[0] - inset) for z in (lo[2] + inset, hi[2] - inset)]
    half_a = _union([half_a, *[_sphere(key_r, c) for c in corners]])
    half_b = _difference(half_b, _union([_sphere(key_r + key_clearance, c) for c in corners]))
    return half_a, half_b
