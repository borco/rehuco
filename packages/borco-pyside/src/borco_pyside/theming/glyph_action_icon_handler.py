"""Keep a `QAction`'s glyph-rendered icon matching the current app theme."""

from typing import Final

from PySide6.QtCore import QObject
from PySide6.QtGui import QAction, QPalette
from PySide6.QtWidgets import QApplication

from .glyph_icon import glyph_icon


class GlyphActionIconThemeHandler(QObject):
    """Keeps ``action``'s icon -- one font glyph, not an SVG -- colored from the current palette.

    The glyph/font/palette-role combination is fixed at construction; only the palette role's actual
    color is re-read, on every ``QApplication.paletteChanged`` -- the point at which a theme switch's
    new colors are genuinely available, matching :class:`~borco_pyside.theming.ActionIconThemeHandler`.
    Unlike that SVG-based handler, this one always renders a single, non-checkable state: there is no
    enabled/disabled or checked/unchecked split to bake in.

    A ``QObject``, parented to ``action`` by default -- ``GlyphActionIconThemeHandler(action, ...)``
    alone is enough, with nothing to hold onto: Qt destroys it along with ``action``.

    :param action: the action to keep themed.
    :param glyph: the glyph character drawn as the icon.
    :param family: the font family ``glyph`` resolves in; must already be loaded application-wide.
    :param color_role: the palette role the glyph is colored with.
    :param parent: optional Qt parent; defaults to ``action`` itself.
    """

    def __init__(
        self,
        action: QAction,
        glyph: str,
        family: str,
        color_role: QPalette.ColorRole = QPalette.ColorRole.Text,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent if parent is not None else action)
        self.__action: Final = action
        self.__glyph: Final = glyph
        self.__family: Final = family
        self.__color_role: Final = color_role

        app = QApplication.instance()
        if not isinstance(app, QApplication):
            raise RuntimeError("GlyphActionIconThemeHandler requires a running QApplication")
        app.paletteChanged.connect(self.__on_palette_changed)

        self.__apply_icon()

    def __on_palette_changed(self, *_args: object) -> None:
        self.__apply_icon()

    def __apply_icon(self) -> None:
        color = QApplication.palette().color(self.__color_role)
        self.__action.setIcon(glyph_icon(self.__glyph, self.__family, color))
