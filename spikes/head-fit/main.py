# /// script
# requires-python = ">=3.10,<3.13"
# dependencies = [
#   "mediapipe>=0.10.14",
#   "numpy>=1.26",
#   "pillow>=10",
# ]
# ///
"""Spike #586: does MediaPipe's head pose place a Loomis head well enough to be a starting point?

Throwaway. Runs outside the workspace (its own interpreter and dependencies via the PEP 723 header),
so nothing lands in a package's ``pyproject.toml``::

    uv run spikes/head-fit/main.py OUT_DIR SOURCE [SOURCE ...] [--max N] [--every K]

A ``SOURCE`` is an image file, a folder of images, or a ``.zip``/``.cbz`` whose image members are read
in place. Each image with a detected face gets ``<name>.loomis.png`` in ``OUT_DIR`` with the sphere, the
side-plane cuts, the centre line, the brow line and the nose and chin lines drawn over it, plus the
yaw / pitch / roll it measured; ``summary.csv`` lists every input with its pose or the reason it was
skipped. Look at the pictures, write the verdict into reference-images.md §18.15, delete this folder.
"""

from __future__ import annotations

import argparse
import csv
import io
import math
import sys
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/"
    "face_landmarker.task"
)
POSE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/"
    "pose_landmarker_lite.task"
)
# Pose landmark indices (33-point layout) that bound the head.
POSE_HEAD_POINTS = range(0, 11)  # nose, eyes, ears, mouth corners
HEAD_CROP_MARGIN = 1.6  # half-size of the crop, in multiples of the head points' spread
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

# Landmark indices of the 468-point mesh used for the fit.
GLABELLA = 9  # between the brows — the Loomis brow line runs through the sphere's centre here
CHIN = 152
FOREHEAD = 10
SUBNASALE = 2

# Proportions, in sphere radii, from adult averages (skull top→chin ≈ 23 cm, brow→chin ≈ 12.5 cm, a
# cranium sphere of r ≈ 9 cm): the brow line sits 0.2 r below the sphere's centre, the nose base a face
# third (0.7 r) below the brow, the chin another third; the sides are cut 0.6 r in from the centre.
# First run used the textbook "brow on the centre, nose base on the bottom" (brow→chin = 1.5 r) and drew
# the sphere visibly too small and too low on every face — see the README.
BROW_Y = -0.2
FACE_THIRD = 0.7
BROW_TO_CHIN_IN_RADII = 2 * FACE_THIRD
NOSE_Y = BROW_Y - FACE_THIRD
CHIN_Y = BROW_Y - 2 * FACE_THIRD
SIDE_CUT_X = 0.6
SIDE_CUT_RADIUS = math.sqrt(1 - SIDE_CUT_X**2)
FACE_FRONT_DEPTH = 0.9  # the brow point sits this far in front of the sphere's centre


@dataclass
class Pose:
    yaw: float
    pitch: float
    roll: float
    rotation: np.ndarray  # 3x3, head-local → camera, y up, z toward the camera


def model_path(url: str = MODEL_URL) -> Path:
    cache = Path(__file__).with_name(".cache")
    cache.mkdir(exist_ok=True)
    path = cache / url.rsplit("/", 1)[1]
    if not path.exists():
        print(f"downloading {url}", file=sys.stderr)
        urllib.request.urlretrieve(url, path)  # noqa: S310 — fixed https URL
    return path


def make_pose_landmarker() -> mp_vision.PoseLandmarker:
    options = mp_vision.PoseLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=str(model_path(POSE_MODEL_URL))),
        running_mode=mp_vision.RunningMode.IMAGE,
        num_poses=1,
    )
    return mp_vision.PoseLandmarker.create_from_options(options)


def head_crop(pose_landmarker: mp_vision.PoseLandmarker, image: Image.Image) -> tuple[int, int, int, int] | None:
    """The head box the whole-body pose gives — what #336 would hand the face stage — as a crop of the original.

    The face detector downsizes the whole frame to a tiny input, so a face that is a few percent of a
    full-figure photo is invisible to it however many pixels it has; the crop is the remedy.
    """
    w, h = image.size
    small = image.copy()
    small.thumbnail((1024, 1024))
    result = pose_landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.asarray(small)))
    if not result.pose_landmarks:
        return None
    pts = np.array([[lm.x * w, lm.y * h] for i, lm in enumerate(result.pose_landmarks[0]) if i in POSE_HEAD_POINTS])
    centre = pts.mean(axis=0)
    spread = max(np.ptp(pts[:, 0]), np.ptp(pts[:, 1]), 0.02 * max(w, h))
    half = HEAD_CROP_MARGIN * spread
    x0, y0 = max(0, int(centre[0] - half)), max(0, int(centre[1] - half))
    x1, y1 = min(w, int(centre[0] + half)), min(h, int(centre[1] + half))
    return x0, y0, x1, y1


class _Shifted:
    """A landmark re-expressed in full-image normalized coordinates after detection on a crop."""

    def __init__(self, lm, box: tuple[int, int, int, int], size: tuple[int, int]) -> None:
        x0, y0, x1, y1 = box
        w, h = size
        self.x = (x0 + lm.x * (x1 - x0)) / w
        self.y = (y0 + lm.y * (y1 - y0)) / h
        self.z = lm.z


def make_landmarker() -> mp_vision.FaceLandmarker:
    options = mp_vision.FaceLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=str(model_path())),
        running_mode=mp_vision.RunningMode.IMAGE,
        num_faces=4,
        output_facial_transformation_matrixes=True,
        output_face_blendshapes=False,
    )
    return mp_vision.FaceLandmarker.create_from_options(options)


def pose_from_matrix(matrix: np.ndarray) -> Pose:
    """Decompose MediaPipe's 4x4 facial transformation matrix into yaw, pitch, roll (degrees)."""
    rot = np.asarray(matrix, dtype=float)[:3, :3]
    # MediaPipe: x right, y up, z toward the camera. Yaw about y, pitch about x, roll about z.
    yaw = math.degrees(math.atan2(rot[0, 2], rot[2, 2]))
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, -rot[1, 2]))))
    roll = math.degrees(math.atan2(rot[1, 0], rot[1, 1]))
    return Pose(yaw=yaw, pitch=pitch, roll=roll, rotation=rot)


def iter_sources(sources: list[Path]):
    """Yield ``(display name, PIL image)`` for every image in the given files, folders and archives."""
    for source in sources:
        if source.is_dir():
            for path in sorted(source.rglob("*")):
                if path.suffix.lower() in IMAGE_SUFFIXES:
                    yield f"{source.name}/{path.relative_to(source)}", Image.open(path)
        elif source.suffix.lower() in {".zip", ".cbz"}:
            with zipfile.ZipFile(source) as archive:
                for info in sorted(archive.infolist(), key=lambda i: i.filename):
                    if Path(info.filename).suffix.lower() in IMAGE_SUFFIXES and not info.is_dir():
                        data = archive.read(info)
                        yield f"{source.name}/{info.filename}", Image.open(io.BytesIO(data))
        elif source.suffix.lower() in IMAGE_SUFFIXES:
            yield source.name, Image.open(source)
        else:
            print(f"skipping {source}: not an image, folder or zip", file=sys.stderr)


def project(points: np.ndarray, pose: Pose, scale: float, centre_px: np.ndarray) -> np.ndarray:
    """Weak-perspective projection of head-local points (in radii) to pixels; returns (N, 3) with depth."""
    cam = points @ pose.rotation.T  # rotate into camera space
    xy = np.column_stack([cam[:, 0], -cam[:, 1]]) * scale + centre_px  # image y runs down
    return np.column_stack([xy, cam[:, 2]])


def polyline(draw: ImageDraw.ImageDraw, pts: np.ndarray, colour: str, width: int, *, front_only: bool) -> None:
    """Draw consecutive segments; with ``front_only`` only the half facing the camera (z > 0)."""
    for a, b in zip(pts[:-1], pts[1:]):
        if front_only and (a[2] < 0 or b[2] < 0):
            continue
        draw.line([(a[0], a[1]), (b[0], b[1])], fill=colour, width=width)


def great_circle(axis: str, radius: float = 1.0, offset: float = 0.0, n: int = 96) -> np.ndarray:
    t = np.linspace(0, 2 * math.pi, n)
    if axis == "x":  # circle in the yz plane at x = offset: the centre line
        return np.column_stack([np.full(n, offset), radius * np.cos(t), radius * np.sin(t)])
    if axis == "y":  # circle in the xz plane at y = offset: the brow line and its parallels
        return np.column_stack([radius * np.cos(t), np.full(n, offset), radius * np.sin(t)])
    raise ValueError(axis)


def level_arc(y: float, half_width: float, n: int = 32) -> np.ndarray:
    """A horizontal arc on the front of the head at height ``y`` (nose base, chin)."""
    xs = np.linspace(-half_width, half_width, n)
    zs = np.sqrt(np.clip(1.0 - xs**2 - min(1.0, y**2), 0.05, None))
    return np.column_stack([xs, np.full(n, y), zs])


def draw_loomis(image: Image.Image, landmarks, pose: Pose) -> tuple[Image.Image, float]:
    """Overlay the Loomis head on ``image``; returns the annotated image and the sphere radius in px."""
    w, h = image.size
    px = np.array([[lm.x * w, lm.y * h] for lm in landmarks])
    brow = px[GLABELLA]
    chin = px[CHIN]
    # The brow→chin distance is vertical in the head frame, so yaw barely shortens it; pitch does.
    brow_to_chin = np.linalg.norm(chin - brow) / max(0.35, abs(math.cos(math.radians(pose.pitch))))
    radius = brow_to_chin / BROW_TO_CHIN_IN_RADII
    # The brow point is on the face front, FACE_FRONT_DEPTH radii in front of the sphere's centre.
    centre_offset = project(np.array([[0.0, BROW_Y, FACE_FRONT_DEPTH]]), pose, radius, np.zeros(2))[0, :2]
    centre_px = brow - centre_offset

    out = image.convert("RGB")
    draw = ImageDraw.Draw(out)
    lw = max(2, int(radius / 40))

    # Sphere outline — a sphere projects to a circle under weak perspective.
    draw.ellipse(
        [centre_px[0] - radius, centre_px[1] - radius, centre_px[0] + radius, centre_px[1] + radius],
        outline="#00c8ff",
        width=lw,
    )
    # Side-plane cuts, centre line, brow line.
    for sign in (-1, 1):
        pts = project(great_circle("x", SIDE_CUT_RADIUS, sign * SIDE_CUT_X), pose, radius, centre_px)
        polyline(draw, pts, "#ffb000", lw, front_only=True)
    polyline(draw, project(great_circle("x"), pose, radius, centre_px), "#ff4040", lw, front_only=True)
    brow_circle = great_circle("y", math.sqrt(1 - BROW_Y**2), BROW_Y)
    polyline(draw, project(brow_circle, pose, radius, centre_px), "#40ff40", lw, front_only=True)
    # Nose base and chin as arcs on the face front, a face third apart.
    for level, half_width in ((NOSE_Y, 0.45), (CHIN_Y, 0.35)):
        arc = level_arc(min(level, -0.05), half_width)
        arc[:, 1] = level
        polyline(draw, project(arc, pose, radius, centre_px), "#ffffff", lw, front_only=False)
    # Jaw: from the bottom of each side cut down to the chin.
    for sign in (-1, 1):
        jaw = np.array([[sign * SIDE_CUT_X, -SIDE_CUT_RADIUS, 0.3], [sign * 0.35, CHIN_Y, 0.75]])
        polyline(draw, project(jaw, pose, radius, centre_px), "#ffb000", lw, front_only=False)

    # Landmarks used for the fit, and the measured pose.
    for name, idx in (("brow", GLABELLA), ("chin", CHIN), ("nose", SUBNASALE), ("top", FOREHEAD)):
        x, y = px[idx]
        draw.ellipse([x - lw, y - lw, x + lw, y + lw], fill="#ff00ff")
    font = ImageFont.load_default(size=max(14, int(h / 50)))
    text = f"yaw {pose.yaw:+.0f}°  pitch {pose.pitch:+.0f}°  roll {pose.roll:+.0f}°  r {radius:.0f}px"
    draw.rectangle([8, 8, 16 + font.getlength(text), 16 + font.size], fill="#000000c0")
    draw.text((12, 10), text, fill="#ffffff", font=font)
    return out, radius


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("sources", type=Path, nargs="+")
    parser.add_argument("--max", type=int, default=60, help="stop after this many images (default 60)")
    parser.add_argument("--every", type=int, default=1, help="take every K-th image, to span a whole pack (default 1)")
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    landmarker = make_landmarker()
    pose_landmarker = make_pose_landmarker()
    rows: list[dict[str, str]] = []
    seen = 0
    for index, (name, image) in enumerate(iter_sources(args.sources)):
        if index % args.every:
            continue
        if seen >= args.max:
            break
        seen += 1
        image = image.convert("RGB")
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.asarray(image))
        result = landmarker.detect(mp_image)
        via = "full"
        faces = list(zip(result.face_landmarks, result.facial_transformation_matrixes))
        if not faces:
            box = head_crop(pose_landmarker, image)
            if box is not None:
                crop = image.crop(box)
                cropped = landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.asarray(crop)))
                faces = [
                    ([_Shifted(lm, box, image.size) for lm in lms], matrix)
                    for lms, matrix in zip(cropped.face_landmarks, cropped.facial_transformation_matrixes)
                ]
                via = f"head crop {box[2] - box[0]}px" if faces else "head crop, no face"
            else:
                via = "no pose"
        if not faces:
            rows.append({"image": name, "faces": "0", "yaw": "", "pitch": "", "roll": "", "radius_px": "", "via": via})
            print(f"{name}: no face ({via})", file=sys.stderr)
            continue
        out = image
        for i, (landmarks, matrix) in enumerate(faces):
            pose = pose_from_matrix(matrix)
            out, radius = draw_loomis(out, landmarks, pose)
            rows.append(
                {
                    "image": name,
                    "faces": str(len(result.face_landmarks)),
                    "yaw": f"{pose.yaw:.1f}",
                    "pitch": f"{pose.pitch:.1f}",
                    "roll": f"{pose.roll:.1f}",
                    "radius_px": f"{radius:.0f}",
                    "via": via,
                }
            )
            print(f"{name} [{i}]: yaw {pose.yaw:+.0f} pitch {pose.pitch:+.0f} roll {pose.roll:+.0f} ({via})", file=sys.stderr)
        safe = name.replace("/", "__").replace("\\", "__")
        out.save(args.out_dir / f"{safe}.loomis.png")

    with (args.out_dir / "summary.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["image", "faces", "yaw", "pitch", "roll", "radius_px", "via"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"{len(rows)} rows → {args.out_dir / 'summary.csv'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
