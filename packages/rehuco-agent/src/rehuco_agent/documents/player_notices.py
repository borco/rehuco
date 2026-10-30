"""What the player's banner says about the video it shows ([[plugins#in-app-player]], #317, #580)."""

from typing import Final

from borco_pyside.widgets import MessageBanner, MessageBannerRow, MessageBannerSeverity
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction

AV1_LIBRARIES_HINT: Final = " An external FFmpeg's libraries with the dav1d decoder would play it."
TOOLS_ACTION_TEXT: Final = "Set up in Tools"


class PlayerNotices(QObject):
    """The warnings the player shows for the video selected: added as they are found, cleared with the video.

    A notice ending in :data:`AV1_LIBRARIES_HINT` carries the one remedy a row offers, a button to the Tools page,
    whose press is :attr:`tools_requested`. The same action serves every such row, as the banner asks
    (:class:`~borco_pyside.widgets.MessageBannerRow`).

    :param banner: the strip the notices are shown in.
    :param parent: optional Qt parent.
    """

    tools_requested = Signal()
    """The user asked to set up the FFmpeg libraries an AV1 video needs; the window above opens the Tools page."""

    def __init__(self, banner: MessageBanner, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__banner: Final = banner
        self.__texts: Final[list[str]] = []
        self.__tools_action: Final = QAction(TOOLS_ACTION_TEXT, self)
        self.__tools_action.triggered.connect(self.tools_requested)

    def add(self, text: str) -> None:
        """Add a warning, once.

        :param text: what it says.
        """
        if text not in self.__texts:
            self.__texts.append(text)
            self.__show()

    def clear(self) -> None:
        """Show nothing: the video changed, or went."""
        self.__texts.clear()
        self.__show()

    def __show(self) -> None:
        """Put the warnings on the banner, or empty it."""
        self.__banner.set_rows(
            [
                MessageBannerRow(
                    MessageBannerSeverity.WARNING,
                    text,
                    self.__tools_action if text.endswith(AV1_LIBRARIES_HINT) else None,
                )
                for text in self.__texts
            ]
        )
