# Public ear meshes: sources and licenses

## Used in the pipeline test

### Denk et al. (2021): ear impression scans (`denk2021/`)
- Record: https://doi.org/10.5281/zenodo.5569300 ("Ear impressions and Earmold design files")
- File downloaded: `Ear Scans.zip` (21.4 MB), https://zenodo.org/api/records/5569300/files/Ear%20Scans.zip/content, plus `readme.txt`. Both are kept in `_downloads/`.
- License: **CC BY 4.0**, https://creativecommons.org/licenses/by/4.0/. Redistribution and derivatives are allowed with attribution.
- Attribution: F. Denk, T. Hieke, M. Roberz, H. Husstedt, "Occlusion and coupling effects with different earmold designs – all a matter of opening the ear canal?", International Journal of Audiology, 2022, DOI 10.1080/14992027.2022.2039966.
- Content: 3D scans of real silicone ear impressions (concha bowl, canal and helix lock) from 10 subjects (IDs 10–19). The filename pattern is `<subject><mode>_<side>`, where mode 0 is mouth closed and mode 1 is mouth open. The STL header says `smart optics duo`, which is an ear-impression scanner. Units are mm. Each scan is an open single surface: one boundary loop where the impression sat on the scanner mount, so none of them is watertight. Subject 11 mode 0 is only provided as `.asc` point clouds, with no faces.
- Files copied unmodified from the zip (only the extension was lowercased):

| file | subject / mode / side | raw OBB (mm) | faces |
|---|---|---|---|
| `denk2021/100_L.stl` | 10 / closed / L | 33.3 × 31.0 × 26.1 | 20 725 |
| `denk2021/101_L.stl` | 10 / open mouth / L | 43.5 × 30.7 × 22.0 | 21 383 |
| `denk2021/130_R.stl` | 13 / closed / R (smallest) | 35.5 × 24.9 × 17.0 | 14 619 |
| `denk2021/150_L.stl` | 15 / closed / L (most boundary edges) | 32.9 × 31.5 × 30.7 | 21 514 |
| `denk2021/161_R.stl` | 16 / open mouth / R (largest) | 48.3 × 35.5 × 25.0 | 25 931 |
| `denk2021/190_R.stl` | 19 / closed / R (near-cubic OBB) | 34.3 × 33.3 × 32.4 | 27 434 |

- Not downloaded from the same record: `Earmolds.zip` (230.8 MB). It holds 240 finished earmold STLs: 10 subjects × 12 designs × L/R, about 2 MB each. Single members can be pulled with HTTP range requests; Zenodo supports them.

## Downloaded but not run

### Viking HRTF dataset v2: pinna replica scans (`_downloads/viking_v2_3D_scans.zip`)
- Record: https://doi.org/10.5281/zenodo.4160400. The file is at https://zenodo.org/api/records/4160401/files/3D_scans.zip/content (9.6 MB).
- License: **CC BY 4.0**. Attribution: S. Spagnol, R. Miccini, R. Unnthórsson, "The Viking HRTF dataset v2", Zenodo 2020.
- Content: `subj_A.stl` … `subj_T.stl`, scans of 20 left artificial pinnae that were molded from lifelike human heads (Creaform Go!SCAN 20, 1 mm). These are pinna meshes, not impressions. I left them out of the pipeline run because of time.

## Rejected or skipped
- **IHA database** of 58 torso, head and complete outer-ear meshes including ear canals (https://doi.org/10.5281/zenodo.16949997). The Zenodo metadata says CC BY 4.0, but the license file inside the record (`_downloads/IHA_database_License_Info_v2.pdf`) says **CC BY-NC-SA 4.0**. I treated it as non-commercial and deleted the downloaded `IHA_database_01.stl`. The PDF is kept as evidence.
- **PIRATE earplugs**, CC BY-SA 4.0 (https://doi.org/10.5281/zenodo.2574395): skipped on Main's instruction because the download was too slow. The file is deleted.
- **Aachen ITA** ear models (MRI): CC BY-NC-SA 4.0, so skipped.
- **HUTUBS** 3D head meshes, CC BY 4.0, 142 MB zip (https://doi.org/10.14279/depositonce-8487): permissive and a possible next source, but not downloaded.
- **OpenEar** temporal bone library, CC BY 4.0: multi-GB per specimen and mostly inner ear, so not relevant.
- Thingiverse and Printables return HTTP 403 to scripted downloads. Sketchfab and embodi3D need a login.
