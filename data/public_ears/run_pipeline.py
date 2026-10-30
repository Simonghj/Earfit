"""Run the EarFit geometry pipeline on the public ear meshes in this folder and render side-view previews.

uv run --with matplotlib python data/public_ears/run_pipeline.py
Writes previews/<name>_<variant>.png and results.json next to this file.
"""

import json
import time
import traceback
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import trimesh
from matplotlib.collections import PolyCollection

from earfit.geometry import _slab_volume, clean_scan, customize_plug, make_mold

HERE = Path(__file__).resolve().parent
MESHES = sorted((HERE / "denk2021").glob("*.stl"))
VARIANTS = {"native_mm": None, "longest28": 28.0}  # longest_mm passed to clean_scan


def boundary_edges(m: trimesh.Trimesh) -> int:
    _, counts = np.unique(m.edges_sorted, axis=0, return_counts=True)
    return int((counts == 1).sum())


def draw(ax, mesh: trimesh.Trimesh | None, axes: tuple[int, int], title: str) -> None:
    ax.set_title(title, fontsize=8)
    ax.set_aspect("equal")
    ax.tick_params(labelsize=6)
    if mesh is None:
        ax.text(0.5, 0.5, "n/a", ha="center", transform=ax.transAxes)
        return
    h, v = axes
    depth_axis = 3 - h - v
    tri = mesh.triangles
    order = np.argsort(-tri[:, :, depth_axis].mean(axis=1))  # far faces first (camera looks along +depth)
    shade = np.abs(mesh.face_normals[order, depth_axis])
    colors = plt.cm.Greys_r(0.25 + 0.6 * shade)
    ax.add_collection(PolyCollection(tri[order][:, :, [h, v]], facecolors=colors, edgecolors="none"))
    lo, hi = mesh.bounds[:, [h, v]]
    pad = 0.05 * (hi - lo).max()
    ax.set_xlim(lo[0] - pad, hi[0] + pad)
    ax.set_ylim(lo[1] - pad, hi[1] + pad)
    ax.set_xlabel("XYZ"[h], fontsize=7)
    ax.set_ylabel("XYZ"[v], fontsize=7)


def run(path: Path, longest_mm: float | None) -> dict:
    rec: dict = {"file": path.name, "longest_mm": longest_mm}
    raw = trimesh.load(path, force="mesh")
    rec["raw"] = {
        "faces": len(raw.faces),
        "aabb_mm": [round(float(x), 1) for x in raw.extents],
        "obb_mm": [round(float(x), 1) for x in sorted(raw.bounding_box_oriented.primitive.extents, reverse=True)],
        "watertight": bool(raw.is_watertight),
        "boundary_edges": boundary_edges(raw),
    }
    clean = plug = mold_a = mold_b = None
    t = time.perf_counter()
    try:
        clean = clean_scan(raw.copy(), longest_mm)
        z0, z1 = clean.bounds[:, 2]
        cut = 0.3 * (z1 - z0)
        bottom, top = _slab_volume(clean, z0, z0 + cut), _slab_volume(clean, z1 - cut, z1)
        rec["clean"] = {
            "ok": True,
            "seconds": round(time.perf_counter() - t, 2),
            "watertight": bool(clean.is_watertight),
            "faces": len(clean.faces),
            "extents_mm": [round(float(x), 1) for x in clean.extents],
            "volume_mm3": round(float(clean.volume)),
            "bottom30_vol": round(bottom),
            "top30_vol": round(top),
        }
    except Exception:
        rec["clean"] = {"ok": False, "seconds": round(time.perf_counter() - t, 2), "error": traceback.format_exc()}
    if clean is not None:
        t = time.perf_counter()
        try:
            plug, report = customize_plug(clean, 13, 2, 0)
            rec["plug"] = {"ok": True, "seconds": round(time.perf_counter() - t, 2), "report": report}
        except Exception:
            rec["plug"] = {"ok": False, "seconds": round(time.perf_counter() - t, 2), "error": traceback.format_exc()}
    if plug is not None:
        t = time.perf_counter()
        try:
            mold_a, mold_b = make_mold(plug)
            rec["mold"] = {
                "ok": True,
                "seconds": round(time.perf_counter() - t, 2),
                "a_watertight": bool(mold_a.is_watertight),
                "b_watertight": bool(mold_b.is_watertight),
                "a_volume_mm3": round(float(mold_a.volume)),
                "b_volume_mm3": round(float(mold_b.volume)),
                "a_bodies": int(mold_a.body_count),
                "b_bodies": int(mold_b.body_count),
            }
        except Exception:
            rec["mold"] = {"ok": False, "seconds": round(time.perf_counter() - t, 2), "error": traceback.format_exc()}

    fig, axs = plt.subplots(1, 5, figsize=(17, 3.8))
    draw(axs[0], raw, (0, 2), f"raw {path.name} (XZ)")
    draw(axs[1], clean, (0, 2), "clean_scan (XZ, +Z up)")
    draw(axs[2], clean, (1, 2), "clean_scan (YZ, +Z up)")
    draw(axs[3], plug, (0, 2), "customize_plug(13,2,0) (XZ)")
    draw(axs[4], mold_a, (0, 2), "make_mold half A (XZ)")
    fig.suptitle(f"{path.stem}  longest_mm={longest_mm}", fontsize=9)
    fig.tight_layout()
    out = HERE / "previews" / f"{path.stem}_{'native' if longest_mm is None else int(longest_mm)}.png"
    out.parent.mkdir(exist_ok=True)
    fig.savefig(out, dpi=110)
    plt.close(fig)
    rec["preview"] = str(out.relative_to(HERE)).replace("\\", "/")
    return rec


def main() -> None:
    results = []
    for path in MESHES:
        for variant, longest_mm in VARIANTS.items():
            t = time.perf_counter()
            rec = run(path, longest_mm)
            rec["variant"] = variant
            rec["total_seconds"] = round(time.perf_counter() - t, 2)
            results.append(rec)
            stages = {k: rec.get(k, {}).get("ok") for k in ("clean", "plug", "mold")}
            print(path.name, variant, stages, rec["total_seconds"], "s", flush=True)
    (HERE / "results.json").write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
