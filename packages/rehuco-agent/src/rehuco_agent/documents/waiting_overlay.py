"""What stands on a maximized view's surface while the view itself cannot be opened yet (#698)."""

from typing import Final, override

from borco_pyside.widgets import BusySpinner
from PySide6.QtCore import Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ..fields.widgets.overlay_surface import OverlayMode, OverlaySurface


class WaitingOverlay(OverlaySurface):
    """A surface saying a maximized view is being restored, with a turning arc while something is still being tried.

    A session restores a maximized player or image viewer over the surface it was on, but the view itself needs its
    document read, which waits for its storage to answer. Until then this stands in its place, so the window comes
    back as it was left and nothing opens over the reader's work later. **A double-click or Esc dismisses it**, which
    is the reader leaving the maximized view: its owner then lets go of the view.

    :param mode: which surface to cover.
    :param document: the open document the view belongs to.
    """

    def __init__(self, mode: OverlayMode, document: QWidget) -> None:
        super().__init__(mode, document)
        self.setAutoFillBackground(True)
        self.__spinner: Final = BusySpinner(self)
        self.__label: Final = QLabel(self)
        self.__label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.__label.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addStretch(1)
        layout.addWidget(self.__spinner, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.__label)
        layout.addStretch(1)

    @property
    def text(self) -> str:
        """What the surface says."""
        return self.__label.text()

    @property
    def busy(self) -> bool:
        """Whether the arc is turning."""
        return self.__spinner.running

    def say(self, text: str, *, busy: bool) -> None:
        """Say what is being waited for.

        :param text: the words.
        :param busy: whether something is still being tried, which turns the arc.
        """
        self.__label.setText(text)
        if busy:
            self.__spinner.start()
        else:
            self.__spinner.stop()

    @override
    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt override)
        """Dismiss on a double-click, as a maximized player does.

        :param event: the Qt mouse event.
        """
        event.accept()
        self.close()
