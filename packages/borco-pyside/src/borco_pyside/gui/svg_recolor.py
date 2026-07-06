"""Recolor a monochrome SVG icon, rendering fresh at whatever exact size Qt requests.

Unlike rasterizing once and recoloring pixels (see :mod:`~borco_pyside.gui.icon_recolor`), this
rewrites the SVG's own fill color and keeps it as a real, infinitely-scalable icon -- exactly as
crisp at any requested size as an untouched SVG-backed ``QIcon``, since nothing is ever cached at
a fixed resolution. Only works correctly for a genuinely monochrome source (see
:func:`recolor_svg` for the exact, narrower rule it actually applies) -- feeding it a multi-color
icon collapses every recognized shape to one flat color rather than preserving their distinctions.
"""

import re
from typing import Final, override

from PySide6.QtCore import QByteArray, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QIconEngine, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer


def recolor_svg(svg: bytes, color: QColor) -> bytes:
    """Rewrite every fill in ``svg`` to ``color``, leaving ``fill:none`` (e.g. background rects).

    Handles both a shape with an explicit ``style="fill:rgb(...)"`` (replaced) and one with no
    ``fill`` at all in its ``style`` (SVG's own implicit default is black; ``fill:{color}`` is
    added). Only ``style="fill:rgb(...)"`` is recognized -- **not** a bare ``fill="..."`` XML
    attribute, nor a non-``rgb()`` ``style`` fill like a hex literal (``style="fill:#112233"``);
    either of those is left completely untouched, permanently, regardless of ``color``. This makes
    the function correct only for a genuinely monochrome icon (every shape either unfilled,
    ``fill:none``, or a single shared color) whose source uses the ``fill:rgb(...)`` form -- e.g.
    an Inkscape export, which is what this app's own icon assets are. Given a multi-color icon
    (several shapes with *different* colors), every ``fill:rgb(...)`` shape collapses to the same
    single ``color`` -- the original color distinctions between shapes are lost, not preserved.

    :param svg: the source SVG document, as raw bytes.
    :param color: the color to recolor every filled shape to.
    :returns: the recolored SVG document, as raw bytes.
    """
    hex_color = color.name()
    text = svg.decode("utf-8")

    def replace_style(match: re.Match[str]) -> str:
        style = match.group(1)
        if "fill:none" in style:
            return match.group(0)
        if re.search(r"fill:\s*rgb\([^)]*\)", style):
            style = re.sub(r"fill:\s*rgb\([^)]*\)", f"fill:{hex_color}", style)
        elif "fill:" not in style:
            style = f"fill:{hex_color};{style}"
        return f'style="{style}"'

    return re.sub(r'style="([^"]*)"', replace_style, text).encode("utf-8")


def recolored_svg_icon(svg: bytes, color: QColor) -> QIcon:
    """Build a ``QIcon`` that renders ``svg`` recolored to ``color``, at any size, on demand.

    :param svg: the source SVG document, as raw bytes.
    :param color: the color to recolor every filled shape to.
    :returns: a scalable ``QIcon`` backed by a :class:`RecoloredSvgIconEngine`.
    """
    return QIcon(RecoloredSvgIconEngine(recolor_svg(svg, color)))


class RecoloredSvgIconEngine(QIconEngine):
    """Renders an already-recolored SVG fresh at whatever exact size/mode/state Qt requests.

    :param svg: the (already recolored) SVG document to render, as raw bytes.
    """

    def __init__(self, svg: bytes) -> None:
        super().__init__()
        self.__svg: Final = svg
        self.__renderer: Final = QSvgRenderer(QByteArray(svg))

    @override
    def paint(  # pylint: disable=unused-argument
        self,
        painter: QPainter,
        rect: QRect,
        mode: QIcon.Mode,
        state: QIcon.State,
    ) -> None:
        self.__renderer.render(painter, QRectF(rect))

    @override
    def pixmap(self, size: QSize, mode: QIcon.Mode, state: QIcon.State) -> QPixmap:
        # overridden rather than relying on QIconEngine's inherited default: that default does not
        # clear the pixmap to transparent first, so paint()'s anti-aliased edges blend against
        # whatever garbage was already in the newly-allocated pixmap (confirmed empirically: wrong,
        # seemingly-random colors came back until this was filled transparent explicitly).
        pixmap = QPixmap(size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        self.paint(painter, QRect(0, 0, pixmap.width(), pixmap.height()), mode, state)
        painter.end()
        return pixmap

    @override
    def clone(self) -> QIconEngine:
        return RecoloredSvgIconEngine(self.__svg)
