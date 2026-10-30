# Spike: automatic head fit (#586)

Throwaway code for one question ([[reference-images#construction-overlays]], "The spike first"):

> On this collection's photos — hair, three-quarter views, studio lighting, the odd profile — does the
> automatic head fit land close enough that handles are a *correction* rather than the whole job?

Keep the lesson, delete the code: the verdict goes into `docs/specs/reference-images.md` §18.15, then this
folder is removed (the convention `spikes/pyqtads-qml/` followed).

## Run

```bash
uv run spikes/head-fit/main.py OUT_DIR SOURCE [SOURCE ...] [--max N] [--every K]
```

`SOURCE` is an image, a folder of images, or a reference pack's `.zip`/`.cbz` read in place. The script
carries its own dependencies in a PEP 723 header, so nothing is added to any package's `pyproject.toml`;
on first run it downloads MediaPipe's `face_landmarker.task` (about 4 MB) into `spikes/head-fit/.cache/`.

Each image with a face gets `<name>.loomis.png` in `OUT_DIR`: the Loomis sphere (cyan), the side-plane cuts
and jaw (orange), the centre line (red), the brow line (green), the nose and chin arcs (white), the four
landmarks the fit uses (magenta) and the measured yaw / pitch / roll. `summary.csv` lists every input.

## What it does

1. MediaPipe Face Landmarker: 468 landmarks and the facial transformation matrix.
2. Yaw, pitch and roll from the matrix's rotation; scale from the brow→chin distance in pixels, corrected
   for pitch; the Loomis proportions are constants at the top of `main.py` (brow line on the sphere's
   centre, nose base on its bottom, chin half a radius lower, sides cut 0.6 r in).
3. The construction as 3D points in head space, rotated by the pose and projected weak-perspective onto
   the photo — the same shape #588's pure geometry module would take.

## Findings so far

- **Runtime.** MediaPipe's wheels stop at Python 3.12 while the workspace is on 3.14, so the header pins
  `<3.13` and `uv` fetches an interpreter. For a stage inside `rehuco-vision` this argues for an ONNX
  landmarker on `onnxruntime` (§18.7's default) over a second runtime — #587's decision.
- **Fit quality (four public-domain portraits: frontal, two three-quarter views including a painting, one
  near-frontal under a beret).** Yaw, pitch and roll read right by eye; the centre and brow lines follow the
  face every time. The textbook proportion (brow on the sphere's centre, nose base on its bottom) drew the
  sphere too small and too low on every skull; adult averages (brow 0.2 r below the centre, face thirds of
  0.7 r — the constants at the top of `main.py`) fixed it in one pass. What remains is handle-sized.
- **The collection's packs** (one archive each, every 7th–11th image, 33–40 per pack):

  | Pack | Faces found | Notes |
  | --- | --- | --- |
  | Expressions (head close-ups, 4000×6000) | 24 / 33 at full frame | yaw to 43°, pitch to 38°, all fitted well |
  | Female poses, top angle (5760²) | 6 / 40 | heads small and often turned away |
  | Male turnaround (3840×5760) | 0 / 40 full frame → 14 / 40 with the head crop | misses are profiles and backs |
  | Warrior, sword (5600×8400) | 0 / 39 full frame → 14 / 39 with the head crop | misses are profiles and backs |

- **Small faces, however many pixels.** The face detector downsizes the whole frame to a tiny input, so a
  face that is a few percent of a full-figure photo is invisible to it at any resolution. The fallback here
  runs MediaPipe Pose on a 1024 px copy, crops the head box from the original, detects on the crop and maps
  the landmarks back — which is what #336's head box would hand #587's stage. Recorded in §18.15 as an
  exception to tier 2's no-crop rule.
- **Beyond ~60° of yaw and from behind** the landmarker gives nothing; the overlay must start from the pose
  stage's coarse head angle (ears and nose) or by hand — the handles' job.
- **Done.** Verdict is in §18.15; this folder goes when #586 is closed.
