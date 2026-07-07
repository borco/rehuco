"""Recolor a monochrome SVG icon, rendering fresh at whatever exact size Qt requests.

Unlike rasterizing once and recoloring pixels (see :mod:`~borco_pyside.theming.icon_recolor`), this
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


def recolored_svg_icon(svg: bytes, color: QColor, on_color: QColor | None = None) -> QIcon:
    """Build a scalable ``QIcon`` that renders ``svg`` recolored to ``color``, at any size, on demand.

    Pass ``on_color`` for a distinct *checked* (``QIcon.State.On``) variant, so one icon can serve a
    checkable action -- Qt renders ``color`` when unchecked and ``on_color`` when checked, without
    the caller swapping icons on state changes. Left ``None``, the state is ignored and every state
    renders in ``color``.

    :param svg: the source SVG document, as raw bytes.
    :param color: the color for the unchecked (``State.Off``) variant, and any state with no variant.
    :param on_color: the color for the checked (``State.On``) variant; ``None`` reuses ``color``.
    :returns: a scalable ``QIcon`` backed by a :class:`RecoloredSvgIconEngine`.
    """
    on_svg = recolor_svg(svg, on_color) if on_color is not None else None
    return QIcon(RecoloredSvgIconEngine(recolor_svg(svg, color), on_svg))


class RecoloredSvgIconEngine(QIconEngine):
    """Renders an already-recolored SVG fresh at whatever exact size/mode/state Qt requests.

    Optionally carries a distinct ``on_svg`` for the checked (``QIcon.State.On``) state; left
    ``None``, the state is ignored and ``svg`` renders for every state. One engine thus covers a
    checkable icon's Off/On without a separate engine per state combination.

    :param svg: the (already recolored) SVG to render, as raw bytes.
    :param on_svg: the (already recolored) SVG to render for ``State.On``; ``None`` reuses ``svg``.
    """

    def __init__(self, svg: bytes, on_svg: bytes | None = None) -> None:
        super().__init__()
        self.__svg: Final = svg
        self.__on_svg: Final = on_svg
        self.__renderer: Final = QSvgRenderer(QByteArray(svg))
        self.__on_renderer: Final = QSvgRenderer(QByteArray(on_svg)) if on_svg is not None else None

    def __renderer_for(self, state: QIcon.State) -> QSvgRenderer:
        if state == QIcon.State.On and self.__on_renderer is not None:
            return self.__on_renderer
        return self.__renderer

    @override
    def paint(  # pylint: disable=unused-argument
        self,
        painter: QPainter,
        rect: QRect,
        mode: QIcon.Mode,
        state: QIcon.State,
    ) -> None:
        self.__renderer_for(state).render(painter, QRectF(rect))

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
        return RecoloredSvgIconEngine(self.__svg, self.__on_svg)
