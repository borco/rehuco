"""Keep a checkable action's icon recolored to match the current app theme."""

from PySide6.QtCore import QFile, QIODevice, QObject
from PySide6.QtGui import QAction, QPalette
from PySide6.QtWidgets import QApplication

from borco_pyside.theming.svg_recolor import recolored_svg_icon


class ActionIconThemeHandler(QObject):
    """Keeps a checkable action's icon recolored to match the current app theme.

    ``icon`` (an SVG resource/file path) is the source glyph; the handler sets **one** scalable
    ``QIcon`` (via :func:`~borco_pyside.theming.recolored_svg_icon` with an ``on_color``) carrying
    both variants -- the unchecked glyph coloured ``QPalette.ColorRole.ButtonText`` as
    ``QIcon.State.Off`` and the checked glyph coloured ``HighlightedText`` as ``State.On`` -- so
    **Qt** picks the right one from the action's own checked state; the handler never swaps icons on
    ``toggled``. The whole icon is rebuilt whenever ``QApplication.paletteChanged`` fires -- that
    signal (not
    ``QStyleHints.colorSchemeChanged``, which can fire before the palette itself has actually been
    updated) is the authoritative point at which the new theme's colours are available to read.

    A ``QObject``, parented to ``action`` by default -- ``ActionIconThemeHandler(action, icon)``
    alone is enough, with nothing to hold onto: Qt destroys it along with ``action``, and its own
    signal connections keep it alive as long as ``action`` does regardless.

    :param action: the checkable action to keep recolored.
    :param icon: path (Qt resource or filesystem) to the source SVG, drawn for the light theme's
        unchecked (normal) state. Must be genuinely monochrome, in the narrow sense
        :func:`~borco_pyside.theming.recolor_svg` actually requires -- a multi-color source loses its
        color distinctions rather than being preserved.
    :param parent: optional Qt parent; defaults to ``action`` itself.
    """

    def __init__(self, action: QAction, icon: str, parent: QObject | None = None) -> None:
        super().__init__(parent if parent is not None else action)
        self.__action = action
        self.__svg: bytes = self.__read_file(icon)

        app = QApplication.instance()
        if not isinstance(app, QApplication):
            raise RuntimeError("ActionIconThemeHandler requires a running QApplication")
        app.paletteChanged.connect(self.__on_palette_changed)

        self.__apply_icon()

    def set_icon(self, icon: str) -> None:
        """Switch the source SVG this handler recolors, rebuilding the icon immediately.

        For an action whose glyph itself changes (e.g. a mode-cycling action swapping between
        sun/moon/auto), rather than just its color -- the new source is still kept themed exactly
        like the original one.

        :param icon: path (Qt resource or filesystem) to the new source SVG, drawn for the light
            theme's unchecked (normal) state.
        """
        self.__svg = self.__read_file(icon)
        self.__apply_icon()

    def __on_palette_changed(self, *_args: object) -> None:
        # the app's palette only reflects a theme switch once this fires -- rebuilding eagerly on
        # colorSchemeChanged instead reads the still-stale pre-switch palette (confirmed: the save
        # icon then never picked up the real colors).
        self.__apply_icon()

    def __apply_icon(self) -> None:
        # One scalable QIcon carrying both variants -- unchecked (ButtonText) as State.Off, checked
        # (HighlightedText) as State.On -- and let Qt pick per the action's checked state. Nothing
        # is swapped on `toggled`, which would miss state changes that don't emit it (a dock closed
        # via its tab's [x], or CDockManager.restoreState() flipping toggleViewAction()).
        palette = QApplication.palette()
        self.__action.setIcon(
            recolored_svg_icon(
                self.__svg,
                palette.color(QPalette.ColorRole.ButtonText),
                palette.color(QPalette.ColorRole.HighlightedText),
            )
        )

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
