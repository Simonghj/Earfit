import argparse
from pathlib import Path

import trimesh

from earfit.geometry import clean_scan, make_mold, sample_plug


def main() -> None:
    parser = argparse.ArgumentParser(description="Turn an ear-impression scan into a printable two-part earplug mold.")
    parser.add_argument("scan", nargs="?", help="STL/OBJ/PLY scan of the impression; omit to use the built-in sample")
    parser.add_argument("--longest-mm", type=float, help="real length of the impression's longest side, for rescaling")
    parser.add_argument("--out", default="out", help="output directory")
    args = parser.parse_args()

    plug = clean_scan(trimesh.load(args.scan), args.longest_mm) if args.scan else sample_plug()
    half_a, half_b = make_mold(plug)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, mesh in (("plug", plug), ("mold_a", half_a), ("mold_b", half_b)):
        path = out / f"{name}.stl"
        mesh.export(path)
        print(f"{path}: watertight={mesh.is_watertight} volume={mesh.volume:.0f} mm^3 size={mesh.extents.round(1)} mm")
