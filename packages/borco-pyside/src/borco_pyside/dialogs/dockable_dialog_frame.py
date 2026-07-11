"""Wraps arbitrary content with a "Restore on start" checkbox, for `DockableDialog` (#47)."""

from typing import Final

from PySide6.QtWidgets import QCheckBox, QVBoxLayout, QWidget


class DockableDialogFrame(QWidget):
    """``content`` plus a footer "Restore on start" checkbox, hosted inside a `DockableDialog`'s dock.

    Built directly in Python, not a `.ui` file -- a single static row wrapped around an arbitrary
    child is the documented trivial-layout exception (`appendices.code-conventions`).

    :param content: the widget this dialog actually shows; reparented onto this frame's layout.
    :param parent: optional Qt parent.
    """

    def __init__(self, content: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__content: Final = content
        self.__restore_on_start_check_box: Final = QCheckBox("Restore on start", self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(content)
        layout.addWidget(self.__restore_on_start_check_box)

    @property
    def content(self) -> QWidget:
        """The wrapped content widget, as passed to the constructor."""
        return self.__content

    @property
    def restore_on_start(self) -> bool:
        """Whether "Restore on start" is currently checked."""
        return self.__restore_on_start_check_box.isChecked()

    @restore_on_start.setter
    def restore_on_start(self, value: bool) -> None:
        self.__restore_on_start_check_box.setChecked(value)
