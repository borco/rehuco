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

from PySide6.QtCore import QByteArray, QRect, QRectF, QSize
from PySide6.QtGui import QColor, QIcon, QIconEngine, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from borco_pyside.theming.utils import painted_pixmap


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


def recolored_svg_icon(
    svg: bytes,
    color: QColor,
    on_color: QColor | None = None,
    disabled_color: QColor | None = None,
    on_disabled_color: QColor | None = None,
) -> QIcon:
    """Build a scalable ``QIcon`` that renders ``svg`` recolored to ``color``, at any size, on demand.

    Pass ``on_color`` for a distinct *checked* (``QIcon.State.On``) variant, so one icon can serve a
    checkable action -- Qt renders ``color`` when unchecked and ``on_color`` when checked, without
    the caller swapping icons on state changes. Left ``None``, the state is ignored and every state
    renders in ``color``.

    Pass ``disabled_color`` for a distinct **disabled** (``QIcon.Mode.Disabled``) variant. This is not
    optional in practice for a *custom* icon engine: Qt's usual "auto-grey a disabled icon" fallback
    (``QStyle.generatedIconPixmap``) only applies to the default pixmap-based engine, which stores a
    fixed set of mode/state pixmaps and falls back to that generator for a mode it wasn't given.
    :class:`RecoloredSvgIconEngine` renders every request instead of storing pixmaps, so it is fully
    responsible for the disabled look itself -- without ``disabled_color``, a disabled action's icon
    renders identically to its enabled one (confirmed empirically, #41).

    Pass ``on_disabled_color`` too for a checkable action that can *also* be disabled -- e.g. a toggle
    that mirrors a model flag (a "dirty" indicator, say) but isn't itself user-clickable. Without it,
    ``disabled_color`` wins outright over ``on_color`` whenever ``mode`` is ``Disabled``, so a disabled
    checked icon would look identical to a disabled unchecked one -- fine for a plain disabled action,
    but it defeats a disabled toggle's whole point if it's meant to keep showing its state.

    :param svg: the source SVG document, as raw bytes.
    :param color: the color for the unchecked (``State.Off``) variant, and any state with no variant.
    :param on_color: the color for the checked (``State.On``) variant; ``None`` reuses ``color``.
    :param disabled_color: the color for the disabled+unchecked variant; ``None`` reuses ``color`` (so
        a disabled icon looks identical to an enabled one -- rarely what's wanted for an action whose
        enabled state actually changes).
    :param on_disabled_color: the color for the disabled+checked variant; ``None`` reuses
        ``disabled_color`` (so a disabled toggle can't show checked-ness).
    :returns: a scalable ``QIcon`` backed by a :class:`RecoloredSvgIconEngine`.
    """
    on_svg = recolor_svg(svg, on_color) if on_color is not None else None
    disabled_svg = recolor_svg(svg, disabled_color) if disabled_color is not None else None
    on_disabled_svg = recolor_svg(svg, on_disabled_color) if on_disabled_color is not None else None
    return QIcon(RecoloredSvgIconEngine(recolor_svg(svg, color), on_svg, disabled_svg, on_disabled_svg))


class RecoloredSvgIconEngine(QIconEngine):  # pylint: disable=too-many-instance-attributes
    """Renders an already-recolored SVG fresh at whatever exact size/mode/state Qt requests.

    Optionally carries a distinct SVG per corner of the mode/state space: ``on_svg`` for checked
    (``State.On``), ``disabled_svg`` for disabled+unchecked, and ``on_disabled_svg`` for
    disabled+checked. Resolution, most-specific first: disabled+checked prefers ``on_disabled_svg``,
    falling back to ``disabled_svg``, then ``on_svg``, then ``svg``; disabled+unchecked prefers
    ``disabled_svg``, falling back to ``svg``; enabled+checked prefers ``on_svg``, falling back to
    ``svg``; enabled+unchecked always renders ``svg``. Any variant left ``None`` simply isn't
    preferred at its corner. One engine thus covers a whole icon's mode/state combinations without a
    separate engine per combination.

    :param svg: the (already recolored) SVG to render, as raw bytes.
    :param on_svg: the (already recolored) SVG to render for enabled ``State.On``; ``None`` reuses ``svg``.
    :param disabled_svg: the (already recolored) SVG to render for disabled ``State.Off``; ``None``
        reuses ``svg``.
    :param on_disabled_svg: the (already recolored) SVG to render for disabled ``State.On``; ``None``
        falls back to ``disabled_svg``, then ``on_svg``, then ``svg``.
    """

    def __init__(
        self,
        svg: bytes,
        on_svg: bytes | None = None,
        disabled_svg: bytes | None = None,
        on_disabled_svg: bytes | None = None,
    ) -> None:
        super().__init__()
        self.__svg: Final = svg
        self.__on_svg: Final = on_svg
        self.__disabled_svg: Final = disabled_svg
        self.__on_disabled_svg: Final = on_disabled_svg
        self.__renderer: Final = QSvgRenderer(QByteArray(svg))
        self.__on_renderer: Final = QSvgRenderer(QByteArray(on_svg)) if on_svg is not None else None
        self.__disabled_renderer: Final = QSvgRenderer(QByteArray(disabled_svg)) if disabled_svg is not None else None
        self.__on_disabled_renderer: Final = (
            QSvgRenderer(QByteArray(on_disabled_svg)) if on_disabled_svg is not None else None
        )

    def __renderer_for(self, mode: QIcon.Mode, state: QIcon.State) -> QSvgRenderer:
        checked = state == QIcon.State.On
        if mode == QIcon.Mode.Disabled:
            if checked and self.__on_disabled_renderer is not None:
                return self.__on_disabled_renderer
            if self.__disabled_renderer is not None:
                return self.__disabled_renderer
        if checked and self.__on_renderer is not None:
            return self.__on_renderer
        return self.__renderer

    @override
    def paint(self, painter: QPainter, rect: QRect, mode: QIcon.Mode, state: QIcon.State) -> None:
        self.__renderer_for(mode, state).render(painter, QRectF(rect))

    @override
    def pixmap(self, size: QSize, mode: QIcon.Mode, state: QIcon.State) -> QPixmap:
        return painted_pixmap(self, size, mode, state)

    @override
    def clone(self) -> QIconEngine:
        return RecoloredSvgIconEngine(self.__svg, self.__on_svg, self.__disabled_svg, self.__on_disabled_svg)
