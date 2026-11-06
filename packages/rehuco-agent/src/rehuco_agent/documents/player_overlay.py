"""The player maximized over the document, the main window or the screen ([[plugins#player-maximized]], #574)."""

from collections.abc import Iterable
from typing import Final

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QBoxLayout, QVBoxLayout, QWidget

from ..fields.widgets.overlay_surface import OverlayMode, OverlaySurface, viewer_mode_for
from ..settings.videos_settings import shared_videos_settings


class PlayerOverlay(OverlaySurface):
    """The surface a maximized player's stage and transport bar are lifted onto: the lightbox's three surfaces and its
    focus discipline (`OverlaySurface`), the window's own background, and the player's keys.

    :param mode: which surface to cover.
    :param document: the open document the player belongs to.
    :param parts: the stage and the bar, top to bottom; each is reparented here.
    :param actions: the player's actions, armed while the focus is here as they are within the dock.
    """

    def __init__(
        self, mode: OverlayMode, document: QWidget, parts: Iterable[QWidget], actions: Iterable[QAction]
    ) -> None:
        super().__init__(mode, document)
        self.setAutoFillBackground(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        for part in parts:
            layout.addWidget(part)
        # one action serves every surface: added here too, its keys answer wherever the player's widgets are
        self.addActions(list(actions))


class PlayerMaximizer(QObject):
    """Lifts the player's stage and transport bar into a `PlayerOverlay` and puts them back where they were.

    The video keeps playing through both moves: Qt reparents a `QVideoWidget`'s native window rather than recreating
    it (#315), and libvlc's surface is an ordinary widget. Whichever way the overlay closes -- Esc, a double-click,
    the restore button, its document going -- the parts are back in the dock before it deletes itself.

    :param layout: the player's layout the parts sit in.
    :param parts: the stage and the bar, top to bottom.
    :param restore_button: the bar's button that restores, shown only while maximized.
    :param document: the open document the player belongs to, which the overlay covers or resolves its window from.
    :param parent: the player, which owns this and whose actions the overlay carries.
    """

    def __init__(
        self,
        layout: QBoxLayout,
        parts: Iterable[QWidget],
        restore_button: QWidget,
        document: QWidget,
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self.__layout: Final = layout
        self.__parts: Final = tuple(parts)
        self.__restore_button: Final = restore_button
        self.__document: Final = document
        self.__player: Final = parent
        self.__overlay: PlayerOverlay | None = None
        self.__mode: OverlayMode | None = None
        restore_button.hide()

    @property
    def mode(self) -> OverlayMode | None:
        """The surface the player is maximized over, or ``None`` while it is in its dock -- what a session restore
        reads (#576)."""
        return self.__mode

    @property
    def overlay(self) -> PlayerOverlay | None:
        """The overlay the player is maximized in, or ``None`` while it is in its dock."""
        return self.__overlay

    def toggle(self, modifiers: Qt.KeyboardModifier) -> None:
        """Maximize the player, or put it back when it is maximized -- what a double-click on the picture does.

        :param modifiers: the keys held, which pick the surface over the Videos page's choice as they do for an image.
        """
        if self.__overlay is not None:
            self.restore()
        else:
            self.maximize(viewer_mode_for(modifiers, shared_videos_settings().maximize_mode))

    def maximize(self, mode: OverlayMode) -> None:
        """Lift the stage and the bar over ``mode``'s surface and give it the keyboard; the player is in its dock.

        :param mode: the surface to cover.
        """
        if self.__overlay is not None:
            return
        overlay = PlayerOverlay(mode, self.__document, self.__parts, self.__player.actions())
        overlay.closed.connect(self.__on_closed)
        self.__overlay = overlay
        self.__mode = mode
        self.__restore_button.show()
        overlay.reveal()

    def restore(self) -> None:
        """Put the player back in its dock, when it is maximized."""
        if self.__overlay is not None:
            self.__overlay.close()

    def __on_closed(self) -> None:
        """Put the parts back in the player's layout, below what stays there, before the overlay deletes itself."""
        self.__overlay = None
        self.__mode = None
        self.__restore_button.hide()
        for part in self.__parts:
            self.__layout.addWidget(part)
