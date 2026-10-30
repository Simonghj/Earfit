# EarFit pipeline on real ear impressions (Denk 2021, CC BY 4.0)

Harness: `uv run --with matplotlib python data/public_ears/run_pipeline.py`. The `--with` flag gives an ephemeral overlay, so no project deps change. Raw numbers are in `results.json` and the previews are in `previews/<scan>_{native,28}.png`. Each preview has five panels: raw XZ, clean XZ, clean YZ, plug XZ, and mold half A XZ.
Calls per scan: `clean_scan(trimesh.load(p), longest_mm)` → `customize_plug(m, 13, 2, 0)` → `make_mold(plug)`. Two variants were run: `longest_mm=None`, where the scans are already true-size mm, and `longest_mm=28`, the app's "typical impression" heuristic.
Code tested: HEAD 2cb1b59 plus the working tree at about 22:46. After that run, someone changed `customize_plug` to raise when `length_mm > max_length`. I re-ran the one affected case against the new code; see bug 4.

## Results

On every run, the raw scan is not watertight (97–292 boundary edges, one hole). After `clean_scan` it is watertight. Both mold halves are watertight and each is a single body. No exceptions were raised, except the post-change case in bug 4. "Canal at max Z?" comes from looking at the clean XZ/YZ previews.

| scan | variant | clean extents (mm) | canal at max Z? | plug size (mm) / vol (mm³) | max_length_mm | clean / plug / mold s | total s |
|---|---|---|---|---|---|---|---|
| 100_L | native | 38.9 × 33.4 × 24.7 | **no**, canal points +X | 38.9 × 31.8 × 13.0 / 6024 | 22.7 | 0.51 / 0.03 / 0.12 | 1.9 |
| 100_L | 28 | 32.7 × 28.0 × 20.7 | **no** | 32.7 × 28.0 × 13.0 / 4091 | 18.7 | 1.83 / 0.10 / 0.48 | 4.7 |
| 101_L | native | 42.0 × 33.5 × 22.6 | **no**, canal points +X | 42.0 × 33.1 × 13.0 / 6389 | 20.6 | 1.83 / 0.10 / 0.48 | 4.8 |
| 101_L | 28 | 27.0 × 21.5 × 14.5 | **no** | 27.0 × 21.5 × 12.5 / 1964 (silently clamped); **now raises**, see bug 4 | 12.5 | 1.94 / 0.10 / 0.50 | 5.2 |
| 130_R | native | 17.2 × 27.4 × 35.5 | yes | 17.2 × 27.4 × 13.0 / 2310 (concha only, canal cut off) | 33.5 | 1.21 / 0.05 / 0.37 | 3.6 |
| 130_R | 28 | 13.6 × 21.6 × 28.0 | yes | 13.6 × 21.6 × 13.0 / 1446 | 26.0 | 1.42 / 0.06 / 0.36 | 3.9 |
| 150_L | native | 33.2 × 35.7 × 32.4 | **no**, canal near min Z at −X | 33.2 × 35.2 × 13.0 / 3799 | 30.4 | 2.20 / 0.09 / 0.43 | 5.4 |
| 150_L | 28 | 28.2 × 30.4 × 27.6 | **no** | 28.2 × 30.3 × 13.0 / 2984 | 25.6 | 2.42 / 0.12 / 0.44 | 5.7 |
| 161_R | native | 25.6 × 35.4 × 49.3 | yes | 16.3 × 35.3 × 13.0 / 2400 (concha only, canal cut off) | 47.3 | 2.18 / 0.07 / 0.32 | 5.1 |
| 161_R | 28 | 14.8 × 20.5 × 28.6 | yes | 13.7 × 20.5 × 13.0 / 1412 | 26.6 | 2.48 / 0.08 / 0.45 | 5.8 |
| 190_R | native | 42.7 × 33.9 × 29.2 | **no**, canal points −X/down | 42.7 × 33.9 × 13.0 / 6428 | 27.2 | 2.17 / 0.10 / 0.48 | 5.7 |
| 190_R | 28 | 34.9 × 27.7 × 23.8 | **no** | 34.9 × 27.7 × 13.0 / 4419 | 21.8 | 2.51 / 0.11 / 0.52 | 6.1 |

Stage pass rates, counted on the 12 runs:
- Repair (`clean_scan` watertight): 12/12.
- Orientation correct: 4/12. By scan that is 2/6 (130_R, 161_R).
- Plug anatomically usable: 0/12. Each plug is watertight, but it is a horizontal slab of the impression and contains no canal.
- Mold booleans watertight: 12/12.

## Pipeline failure modes found

1. **`orient_impression` points the canal sideways or down in 4 of 6 real impressions** (100_L, 101_L, 150_L, 190_R).
   - Every raw scan already arrives in the right pose from the impression scanner: open/flat base at −Z, canal pointing +Z (see the raw panels). Orientation makes it worse.
   - Cause: the method only tries the ± principal inertia axes. On a full-concha impression the canal axis is not a principal axis. The best bottom/top slab ratio (1.7–2.8) usually lands on the thinnest axis, so the plug's Z becomes the impression's thickness.
   - The ratio does not change with scale, so `longest_mm` does not affect which pose is chosen.
   - Fix ideas:
     - Score by the cross-section area at the top (the canal tip must be narrow) instead of the slab-volume ratio.
     - Try more directions, e.g. a Fibonacci sphere, not just 3 axes.
     - Find the canal as the farthest narrow protrusion from the planar repair patch.
     - Or keep the input pose when it already scores well, and let the user flip it.
2. **`customize_plug(length_mm=13)` produces no earplug from a full impression, even when the orientation is correct** (130_R, 161_R).
   - It keeps the bottom 13 mm across the full XY extent. That slice is concha, cymba and helix lock; the canal sits 20–47 mm away (`max_length_mm` 33.5 / 47.3) and is cut off entirely.
   - Real impressions are 29–48 mm long (OBB), so a fixed slab measured from the outer face only works on short, already-trimmed plug shapes like `sample_plug()`.
   - Needs canal-aware trimming: keep the canal plus the concha bowl, cut perpendicular to the canal axis, and trim the helix/cymba.
3. **Scale heuristic is wrong for real impressions.**
   - `longest_mm=28` shrinks these true-mm scans by 16–42%: 161_R goes from 48.3 to 28 mm and its volume drops 10458 → 2031 mm³. The OBB longest side of real full-concha impressions ranged 29–48 mm here.
   - Recommendation: for mm scans, default to `None`. Infer units from size instead: an OBB longest side of about 15–80 means mm; about 0.015–0.08 means m, so ×1000.
4. **Exception after the new length check.** `101_L` with `longest_mm=28`: the wrong orientation leaves only 12.5 mm along Z, so the new check rejects the default 13 mm:
   ```
   File "src\earfit\geometry.py", line 110, in customize_plug
     raise ValueError(
   ValueError: length_mm 13 exceeds this impression's max_length_mm 12.5; choose a shorter length (the default for the use case)
   ```
   Before the change, the same call silently returned a 12.5 mm plug.
5. **Repair noise and hole patch.**
   - pymeshfix prints `MeshFix could not fix everything` on all 6 scans, yet the result is watertight. That is misleading in server logs.
   - The closed scanner hole becomes a large flat cap; it is the flat diagonal face in the clean previews. After the bad rotation it is no longer at min Z, so the plug's "outer face" is not the impression's real outer face.
6. **Mold placement depends on orientation.** `make_mold` puts the air vent at the max-Z vertex ("canal tip") and the sprue at the min-X vertex. With the canal sideways, the vent lands on an arbitrary high point of the concha. The booleans themselves were robust: 0.1–0.5 s, watertight, one body per half. The mold previews show only the outside of the block; I did not visually check the cavity.
7. **Other observations, not exercised in this run:**
   - The dataset includes `.asc` point clouds (subject 11), which upload cannot handle as meshes.
   - In this venv, `trimesh.Trimesh.split()` / `fill_holes()` raise `ModuleNotFoundError: networkx` (seen while probing). The pipeline does not call them today.
