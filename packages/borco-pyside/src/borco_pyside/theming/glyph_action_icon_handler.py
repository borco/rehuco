"""Give a `QAction` a glyph-rendered icon that colors itself from the current app theme."""

from typing import Final

from PySide6.QtCore import QObject
from PySide6.QtGui import QAction, QPalette
from PySide6.QtWidgets import QApplication

from .themed_icons import themed_glyph_icon


class GlyphActionIconThemeHandler(QObject):
    """Gives ``action`` an icon -- one font glyph, not an SVG -- colored from the current palette.

    The glyph/font/palette-role combination is fixed at construction, and the shared icon assigned
    from it reads that role's color from ``QApplication.palette()`` **as it paints**, so a theme
    switch needs nothing rebuilt and nothing notified. See
    :mod:`~borco_pyside.theming.themed_icons` for why that matters, and
    :class:`~borco_pyside.theming.ActionIconThemeHandler` for the SVG equivalent. Unlike that handler,
    this one always renders a single, non-checkable state: there is no enabled/disabled or
    checked/unchecked split to bake in.

    A ``QObject``, parented to ``action`` by default, and holding nothing -- an action with a fixed
    glyph can equally well be given :func:`~borco_pyside.theming.themed_glyph_icon` directly; this
    class exists to keep the two icon handlers a matched pair at their call sites.

    :param action: the action to give a themed icon.
    :param glyph: the glyph character drawn as the icon.
    :param family: the font family ``glyph`` resolves in; must already be loaded application-wide.
    :param color_role: the palette role the glyph is colored with.
    :param parent: optional Qt parent; defaults to ``action`` itself.
    :raises RuntimeError: if there is no running ``QApplication``.
    """

    def __init__(
        self,
        action: QAction,
        glyph: str,
        family: str,
        color_role: QPalette.ColorRole = QPalette.ColorRole.Text,
        parent: QObject | None = None,
    ) -> None:
        # checked before super().__init__() runs at all: that call fully constructs and parents a
        # live QObject, and raising after it would leave a half-initialized one attached to the parent
        # with no Python reference left to it -- an object neither this constructor nor its caller can
        # ever clean up, since the exception unwinds before either holds one
        app = QApplication.instance()
        if not isinstance(app, QApplication):
            raise RuntimeError("GlyphActionIconThemeHandler requires a running QApplication")

        super().__init__(parent if parent is not None else action)
        self.__action: Final = action
        self.__action.setIcon(themed_glyph_icon(glyph, family, color_role))
