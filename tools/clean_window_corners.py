"""Crop a Windows window screenshot to the window itself, and restore its rounded corners.

Windows 11's DWM compositor rounds window corners and draws a 1px border, so
a rectangular capture of a single window (e.g. Snipping Tool) carries that
border along the straight edges plus whatever was behind the window showing
through the four corner gaps.

The capture's rectangle is not the window's: it sits one pixel out on the
left, top and bottom, and flush on the right. That is the capture pipeline's
own geometry, identical from one grab to the next, so BORDER_CROP below is a
constant rather than something measured per image. Trimming a fixed 1px off
all four sides instead -- the obvious thing -- eats a real column of window on
the right and leaves that corner starting a pixel inside the others, which is
what makes one corner come out visibly squarer than the rest.

The corners are then rebuilt geometrically, as an anti-aliased quarter-disc of
--radius. The radius is a property of the compositor and the display scaling
(8 physical pixels at 100%), not of the window's dimensions, so it does not
scale with the image. Only pixels the arc leaves partly uncovered are touched:
each takes the window's own colour beside that corner at an alpha equal to its
coverage, and everything the arc covers fully is left exactly as captured --
so a scrollbar or an icon sitting close to a corner survives.

Deriving the corner alpha from pixel brightness instead -- the desktop behind
a corner contributing ~0 to the blend, so brightness *is* the window's opacity
there -- holds only while the desktop behind the window is black. Against a
light backdrop the same arithmetic returns ~255 everywhere and the corner comes
out square, with nothing in the output to say the assumption was violated.

Usage:
    uv run python tools/clean_window_corners.py <image.png> [image2.png ...]
    uv run python tools/clean_window_corners.py --radius 12 <image.png>

By default, each original is preserved as "<name>.orig<suffix>" next to it
before the image is cleaned in place. Pass --overwrite to skip the backup
and overwrite the image directly.
"""

import argparse
import shutil
from pathlib import Path
from typing import Final

from PySide6.QtGui import QImage

CORNER_RADIUS: Final = 8
"""Windows 11's corner radius in physical pixels, at 100% display scaling."""

BORDER_CROP: Final = [1, 1, 0, 1]
"""Left, top, right, bottom: what a capture carries beyond the window, measured off real grabs.

Right is 0 because the capture's right edge already falls on the window's own last column -- the
border pixel that the other three sides carry is not there to crop.
"""

SUBSAMPLES: Final = 8
"""Per axis, so 64 samples decide how much of a pixel the corner arc covers."""


def coverage(dx: int, dy: int, radius: int) -> float:
    """Return how much of the pixel at ``(dx, dy)`` from a corner falls inside that corner's arc.

    :param dx: distance in pixels from the corner, along the image's width.
    :param dy: distance in pixels from the corner, along the image's height.
    :param radius: the corner radius, and so the arc's centre at ``(radius, radius)``.
    :returns: covered fraction, 0.0 (outside the window) to 1.0 (wholly inside it).
    """
    inside = 0
    for step_x in range(SUBSAMPLES):
        offset_x = dx + (step_x + 0.5) / SUBSAMPLES - radius
        for step_y in range(SUBSAMPLES):
            offset_y = dy + (step_y + 0.5) / SUBSAMPLES - radius
            if offset_x * offset_x + offset_y * offset_y <= radius * radius:
                inside += 1
    return inside / (SUBSAMPLES * SUBSAMPLES)


def round_corners(image: QImage, radius: int) -> None:
    """Replace ``image``'s four square corners with anti-aliased arcs of ``radius``, in place.

    :param image: the cropped window, in an alpha-carrying format.
    :param radius: the corner radius in pixels.
    """
    width, height = image.width(), image.height()
    for corner_x, corner_y in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)):
        x_step = 1 if corner_x == 0 else -1
        y_step = 1 if corner_y == 0 else -1
        # Sampled per corner rather than once for the whole window: the colour a fringe pixel
        # should fade out of is the window's own colour right there, and the four corners of a
        # window are rarely the same colour.
        colour = image.pixelColor(corner_x + radius * x_step, corner_y + radius * y_step)
        for dx in range(radius):
            for dy in range(radius):
                covered = coverage(dx, dy, radius)
                if covered == 1.0:
                    continue
                colour.setAlpha(round(255 * covered))
                image.setPixelColor(corner_x + dx * x_step, corner_y + dy * y_step, colour)


def clean(path: Path, radius: int, overwrite: bool) -> None:
    """Crop ``path``'s capture down to the window and round its corners, in place.

    :param path: the screenshot to clean.
    :param radius: the corner radius in pixels.
    :param overwrite: skip the ``<name>.orig<suffix>`` backup and overwrite the original.
    :raises ValueError: when the file is not an image Qt can read.
    """
    image = QImage(str(path))
    if image.isNull():
        raise ValueError(f"{path}: not an image Qt can read")

    if not overwrite:
        backup_path = path.with_suffix(f".orig{path.suffix}")
        shutil.copyfile(path, backup_path)

    left, top, right, bottom = BORDER_CROP
    window = image.convertToFormat(QImage.Format.Format_ARGB32).copy(
        left, top, image.width() - left - right, image.height() - top - bottom
    )
    round_corners(window, radius)
    window.save(str(path))


def main() -> None:
    """Clean every image named on the command line, in place."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", nargs="+", type=Path, help="screenshot(s) to clean")
    parser.add_argument(
        "-r",
        "--radius",
        type=int,
        default=CORNER_RADIUS,
        help="corner radius in pixels, as the compositor drew it (default: %(default)s)",
    )
    parser.add_argument(
        "-o",
        "--overwrite",
        action="store_true",
        help="overwrite each image in place without keeping a '<name>.orig<suffix>' backup",
    )
    args = parser.parse_args()

    for image in args.images:
        clean(image, args.radius, args.overwrite)


if __name__ == "__main__":
    main()
