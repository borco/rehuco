"""A thin horizontal rule: a `QFrame` styled as an ``HLine`` for separating stacked content."""

from PySide6.QtWidgets import QFrame, QWidget


class HorizontalLine(QFrame):
    """A one-pixel horizontal divider drawn by Qt's native `QFrame` ``HLine`` shape, for separating
    stacked blocks (e.g. a label from the full-width content below it in a vertical field row).

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.HLine)
        self.setFrameShadow(QFrame.Shadow.Sunken)
