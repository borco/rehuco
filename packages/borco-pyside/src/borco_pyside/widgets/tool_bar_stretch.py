"""A stretch item for `QToolBar`: an empty widget that takes all the spare room."""

from PySide6.QtWidgets import QSizePolicy, QWidget


class ToolBarStretch(QWidget):
    """An empty, expanding `QWidget` for ``QToolBar.addWidget``: `QToolBar` has no stretch item of its
    own, so this is the standard stand-in, pushing every action added after it to the far end of the
    bar -- in either orientation.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
