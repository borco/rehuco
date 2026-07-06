"""Keep a checkable action's icon recolored to match the current app theme."""

from PySide6.QtCore import QFile, QIODevice, QObject
from PySide6.QtGui import QAction, QIcon, QPalette
from PySide6.QtWidgets import QApplication

from borco_pyside.gui.svg_recolor import recolored_svg_icon


class ActionIconThemeHandler(QObject):
    """Keeps a checkable action's icon recolored to match the current app theme.

    ``icon`` (an SVG resource/file path) is assumed to already be drawn for the light theme's
    unchecked (normal) state, and is kept as the source glyph; a checked variant is derived from
    it via :func:`~borco_pyside.gui.recolored_svg_icon`, using ``QPalette.ColorRole.ButtonText``/
    ``HighlightedText`` so both automatically track whatever palette the current theme provides --
    no separate light/dark master assets needed. Recoloring the SVG's own fill (rather than a
    rasterized pixmap) keeps the icon exactly as crisp at any size as an untouched SVG-backed
    ``QIcon``. Icons are built lazily, one per ``checked`` state, and rebuilt from scratch whenever
    ``QApplication.paletteChanged`` fires -- that signal (not ``QStyleHints.colorSchemeChanged``,
    which can fire before the palette itself has actually been updated) is the authoritative point
    at which the new theme's colors are available to read.

    A ``QObject``, parented to ``action`` by default -- ``ActionIconThemeHandler(action, icon)``
    alone is enough, with nothing to hold onto: Qt destroys it along with ``action``, and its own
    signal connections keep it alive as long as ``action`` does regardless.

    :param action: the checkable action to keep recolored.
    :param icon: path (Qt resource or filesystem) to the source SVG, drawn for the light theme's
        unchecked (normal) state. Must be genuinely monochrome, in the narrow sense
        :func:`~borco_pyside.gui.recolor_svg` actually requires -- a multi-color source loses its
        color distinctions rather than being preserved.
    :param parent: optional Qt parent; defaults to ``action`` itself.
    """

    def __init__(self, action: QAction, icon: str, parent: QObject | None = None) -> None:
        super().__init__(parent if parent is not None else action)
        self.__action = action
        self.__svg: bytes = self.__read_file(icon)
        self.__cache: dict[bool, QIcon] = {}

        action.toggled.connect(self.__update_icon)
        app = QApplication.instance()
        if not isinstance(app, QApplication):
            raise RuntimeError("ActionIconThemeHandler requires a running QApplication")
        app.paletteChanged.connect(self.__on_palette_changed)

        self.__update_icon()

    def set_icon(self, icon: str) -> None:
        """Switch the source SVG this handler recolors, rebuilding the current icon immediately.

        For an action whose glyph itself changes (e.g. a mode-cycling action swapping between
        sun/moon/auto), rather than just its color -- the new source is still kept themed exactly
        like the original one.

        :param icon: path (Qt resource or filesystem) to the new source SVG, drawn for the light
            theme's unchecked (normal) state.
        """
        self.__svg = self.__read_file(icon)
        self.__cache.clear()
        self.__update_icon()

    def __on_palette_changed(self, *_args: object) -> None:
        # the app's palette only reflects a theme switch once this fires -- rebuilding eagerly on
        # colorSchemeChanged instead read the still-stale pre-switch palette and cached it forever
        # under that scheme's key (confirmed: the save icon then never picked up the real colors).
        self.__cache.clear()
        self.__update_icon()

    def __update_icon(self, *_args: object) -> None:
        checked = self.__action.isChecked()
        icon = self.__cache.get(checked)
        if icon is None:
            icon = self.__build_icon(checked)
            self.__cache[checked] = icon  # pylint: disable=unsupported-assignment-operation
        self.__action.setIcon(icon)

    def __build_icon(self, checked: bool) -> QIcon:
        role = QPalette.ColorRole.HighlightedText if checked else QPalette.ColorRole.ButtonText
        color = QApplication.palette().color(role)
        return recolored_svg_icon(self.__svg, color)

    def __read_file(self, path: str) -> bytes:
        """Read ``path`` (Qt resource or filesystem) fully into memory.

        :param path: the file to read, e.g. a ``:/...`` Qt resource path or a plain filesystem path.
        :returns: the file's full contents.
        :raises RuntimeError: if ``path`` cannot be opened for reading.
        """
        file = QFile(path)
        if not file.open(QIODevice.OpenModeFlag.ReadOnly):
            raise RuntimeError(f"cannot open {path!r} for reading")
        try:
            return bytes(file.readAll().data())
        finally:
            file.close()
