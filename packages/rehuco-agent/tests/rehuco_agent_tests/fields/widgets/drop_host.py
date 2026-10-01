"""A stand-in for the Main Editor dock around a drop-accepting editor (#272, #385)."""

from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QWidget


class DropHost(QWidget):
    """A widget around the editor that accepts drops, like the Main Editor dock, and records the ones it got."""

    def __init__(self) -> None:
        super().__init__()
        self.dropped = False
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802 (Qt override)
        event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802 (Qt override)
        self.dropped = True
        event.acceptProposedAction()
