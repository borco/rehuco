# Spike: automatic head fit (#586)

Throwaway code for one question ([[reference-images#construction-overlays]], "The spike first"):

> On this collection's photos — hair, three-quarter views, studio lighting, the odd profile — does the
> automatic head fit land close enough that handles are a *correction* rather than the whole job?

Keep the lesson, delete the code: the verdict goes into `docs/specs/reference-images.md` §18.15, then this
folder is removed (the convention `spikes/pyqtads-qml/` followed).

## Run

```bash
uv run spikes/head-fit/main.py OUT_DIR SOURCE [SOURCE ...] [--max N]
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
- **Small faces.** A family group whose faces were under about 60 px yielded no detection. The stage cannot
  run on a 512 px working image of a full figure; it needs the face region from the original — an exception
  to tier 2's no-crop rule, recorded in §18.15 for #587.
- **Still to do.** Run it over a few of the collection's own packs (`uv run spikes/head-fit/main.py out
  path/to/pack.zip --max 40`), look, adjust the verdict in §18.15 if they disagree, then delete this folder.
