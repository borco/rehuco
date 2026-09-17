"""One shared, self-updating ``QIcon`` per source SVG, colored from the palette as it paints.

The whole point is that a themed glyph's color stops being state that has to be kept up to date. An
icon built here reads ``QApplication.palette()`` at the moment Qt asks it to draw, so there is nothing
to rebuild, nothing to subscribe to, and nothing that can be left stale -- which is what #304 was: with
several documents restored from the session, a theme switch recolored only the one that happened to be
focused, because every other document's icons were built once, before the saved theme was applied, and
depended on a ``palette_changed`` round-trip they did not all survive. Icons are shared per source SVG
as well, so two windows showing the same action cannot disagree about it even in principle.
"""

from typing import Final, override

from PySide6.QtCore import QByteArray, QObject, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QIconEngine, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

from .checked_chrome import CheckedToolButtonChrome
from .glyph_icon import GlyphIconEngine
from .svg_recolor import recolor_svg
from .utils import painted_pixmap, read_resource_bytes


class PaletteSvgIconEngine(QIconEngine):
    """Renders a monochrome SVG in whatever color the *current* palette calls for, at any size.

    Colors are resolved per request rather than baked in at construction: ``ButtonText`` for the
    unchecked state, and for the checked state whatever
    :meth:`~borco_pyside.theming.CheckedToolButtonChrome.glyph_color` measures to read against the
    chrome this style paints -- each from the ``Disabled`` color group when the mode is ``Disabled``.
    Qt supplies no auto-grey fallback for a custom engine (``QStyle.generatedIconPixmap`` only applies
    to the default pixmap engine), so the disabled look is this engine's own responsibility.

    Renderers are memoized against the palette's ``cacheKey()``, so a repaint under an unchanged
    palette costs a dict lookup rather than an SVG re-parse, and a palette change drops the whole memo
    rather than growing it.

    :param svg: the source SVG document, as raw bytes. Must be genuinely monochrome in the narrow
        sense :func:`~borco_pyside.theming.recolor_svg` requires.
    :param flat: draw the checked state in the plain unchecked color -- for an action whose context
        paints no filled chrome behind the glyph at all, e.g. a menu row, where its own native
        checkmark communicates checked-ness instead.
    """

    def __init__(self, svg: bytes, *, flat: bool = False) -> None:
        super().__init__()
        self.__svg: Final = svg
        self.__flat: Final = flat
        self.__palette_key: int | None = None
        self.__renderers: dict[tuple[QIcon.Mode, QIcon.State], QSvgRenderer] = {}

    def __color(self, palette: QPalette, mode: QIcon.Mode, state: QIcon.State) -> QColor:
        disabled = mode == QIcon.Mode.Disabled
        group = QPalette.ColorGroup.Disabled if disabled else QPalette.ColorGroup.Active
        if state == QIcon.State.On and not self.__flat:
            return CheckedToolButtonChrome.glyph_color(palette, enabled=not disabled)
        return palette.color(group, QPalette.ColorRole.ButtonText)

    def __renderer_for(self, mode: QIcon.Mode, state: QIcon.State) -> QSvgRenderer:
        palette = QApplication.palette()
        key = palette.cacheKey()
        if key != self.__palette_key:
            self.__palette_key = key
            self.__renderers = {}
        renderer = self.__renderers.get((mode, state))
        if renderer is None:
            renderer = QSvgRenderer(QByteArray(recolor_svg(self.__svg, self.__color(palette, mode, state))))
            self.__renderers[(mode, state)] = renderer  # pylint: disable=unsupported-assignment-operation
        return renderer

    @override
    def paint(self, painter: QPainter, rect: QRect, mode: QIcon.Mode, state: QIcon.State) -> None:
        self.__renderer_for(mode, state).render(painter, QRectF(rect))

    @override
    def pixmap(self, size: QSize, mode: QIcon.Mode, state: QIcon.State) -> QPixmap:
        return painted_pixmap(self, size, mode, state)

    @override
    def clone(self) -> QIconEngine:
        return PaletteSvgIconEngine(self.__svg, flat=self.__flat)


class ThemedIcons(QObject):
    """The application's one cache of themed icons, keyed by source SVG and variant.

    Parented to the ``QApplication`` and found through :meth:`for_application`, the same shape
    :class:`~borco_pyside.theming.ApplicationPaletteChangeNotifier` uses -- so a caller never has to
    hold one, and the cache lives exactly as long as the application does. That lifetime is also what
    keeps each engine's Python object owned on the Python side, rather than handed to a ``QIcon`` and
    left unreferenced.

    :param app: the application to cache icons for, and to parent this to.
    """

    def __init__(self, app: QApplication) -> None:
        super().__init__(app)
        self.__icons: Final[dict[tuple[str, bool], QIcon]] = {}
        self.__glyph_icons: Final[dict[tuple[str, str, QPalette.ColorRole], QIcon]] = {}
        self.__engines: Final[list[QIconEngine]] = []

    @classmethod
    def for_application(cls, app: QApplication) -> ThemedIcons:
        """Return ``app``'s cache, creating and parenting it on first use.

        :param app: the application to return the cache for.
        :returns: the one cache belonging to ``app``.
        """
        existing = app.findChild(cls, options=Qt.FindChildOption.FindDirectChildrenOnly)
        if existing is not None:
            return existing
        return cls(app)

    def clear(self) -> None:
        """Drop every cached icon, so the next request rebuilds from the source path again.

        For tests, which mock what a path reads back and would otherwise be served a previous test's
        SVG from the cache. Production has no reason to call this: an icon resource's *content* never
        changes within a run, and the colors are not cached at all.
        """
        self.__icons.clear()
        self.__glyph_icons.clear()
        self.__engines.clear()

    def icon(self, path: str, *, flat: bool = False) -> QIcon:
        """Return the shared themed icon for ``path``, building it on first request.

        The same ``(path, flat)`` always returns the same ``QIcon``, so every action drawn from one
        source SVG shares a single engine and they cannot disagree about its color.

        :param path: the source SVG, Qt resource or filesystem path.
        :param flat: draw the checked state in the plain unchecked color; see
            :class:`PaletteSvgIconEngine`.
        :returns: the shared icon.
        :raises RuntimeError: if ``path`` cannot be opened for reading.
        """
        key = (path, flat)
        cached = self.__icons.get(key)
        if cached is not None:
            return cached
        engine = PaletteSvgIconEngine(read_resource_bytes(path), flat=flat)
        self.__engines.append(engine)
        icon = QIcon(engine)
        self.__icons[key] = icon  # pylint: disable=unsupported-assignment-operation
        return icon

    def glyph_icon(self, glyph: str, family: str, color_role: QPalette.ColorRole) -> QIcon:
        """Return the shared themed icon for one icon-font glyph, building it on first request.

        The glyph equivalent of :meth:`icon`: the same ``(glyph, family, color_role)`` always returns
        the same ``QIcon``, and the engine reads ``color_role`` from the live palette as it paints.

        :param glyph: the character to draw.
        :param family: the font family ``glyph`` resolves in; must already be loaded.
        :param color_role: the palette role to draw the glyph in.
        :returns: the shared icon.
        """
        key = (glyph, family, color_role)
        cached = self.__glyph_icons.get(key)
        if cached is not None:
            return cached
        engine = GlyphIconEngine(glyph, family, color_role)
        self.__engines.append(engine)
        icon = QIcon(engine)
        self.__glyph_icons[key] = icon  # pylint: disable=unsupported-assignment-operation
        return icon


def themed_svg_icon(path: str, *, flat: bool = False) -> QIcon:
    """Return the application-wide shared themed icon for ``path``.

    :param path: the source SVG, Qt resource or filesystem path.
    :param flat: draw the checked state in the plain unchecked color; see
        :class:`PaletteSvgIconEngine`.
    :returns: the shared icon.
    :raises RuntimeError: if there is no running ``QApplication``, or ``path`` cannot be read.
    """
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        raise RuntimeError("themed_svg_icon requires a running QApplication")
    return ThemedIcons.for_application(app).icon(path, flat=flat)


def themed_glyph_icon(glyph: str, family: str, color_role: QPalette.ColorRole) -> QIcon:
    """Return the application-wide shared themed icon for one icon-font glyph.

    :param glyph: the character to draw.
    :param family: the font family ``glyph`` resolves in; must already be loaded.
    :param color_role: the palette role to draw the glyph in, read as it paints.
    :returns: the shared icon.
    :raises RuntimeError: if there is no running ``QApplication``.
    """
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        raise RuntimeError("themed_glyph_icon requires a running QApplication")
    return ThemedIcons.for_application(app).glyph_icon(glyph, family, color_role)
