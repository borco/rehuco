"""A checkbox whose caption is a word-wrapping `QLabel`, so a long caption never forces a min width."""

from typing import override

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QWidget


class WrappingCheckBox(QWidget):
    """A checkbox paired with a word-wrapping caption label.

    A bare `QCheckBox` reports its full caption width as its minimum width and never wraps, so a
    long caption forces its whole column wider. This composes a caption-less `QCheckBox` with a
    wrapping `QLabel` instead: the label wraps to the available width (growing taller, not wider),
    and a click anywhere on the label toggles the box -- so it still behaves like one checkbox.

    Both are vertically centered, so a single-line caption lines up with the checkbox indicator (and a
    wrapped caption centers as a block beside it). Exposes the checkbox's ``toggled`` signal and
    snake_case accessors for its checked state and caption text; set the caption with :meth:`set_text`
    (there is no caption constructor argument, so the ``parent``-only signature stays promotable inside
    a ``.ui``, like `ElidedLabel`).

    :param parent: optional Qt parent.
    """

    toggled = Signal(bool)
    """Re-emitted from the inner checkbox whenever its checked state changes."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__check_box = QCheckBox(self)
        self.__label = QLabel(self)
        self.__label.setWordWrap(True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.__check_box, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.__label, 1, Qt.AlignmentFlag.AlignVCenter)

        self.__check_box.toggled.connect(self.toggled)
        self.__label.installEventFilter(self)

    def is_checked(self) -> bool:
        """Whether the checkbox is currently checked."""
        return self.__check_box.isChecked()

    def set_checked(self, checked: bool) -> None:
        """Check or uncheck the checkbox (fires ``toggled`` if the state changes).

        :param checked: the checked state to set.
        """
        self.__check_box.setChecked(checked)

    def text(self) -> str:
        """The caption text."""
        return self.__label.text()

    def set_text(self, text: str) -> None:
        """Set the caption text.

        :param text: the caption to show next to the checkbox.
        """
        self.__label.setText(text)

    @override
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802  (Qt API name)
        """Toggle the checkbox when its caption label is clicked, so the label acts as part of the
        checkbox rather than as inert decoration.

        :param watched: the object the event is for; the caption label when this filter fires.
        :param event: the intercepted event.
        :returns: ``True`` (consuming the event) for a click released on the label, else the base result.
        """
        if watched is self.__label and event.type() == QEvent.Type.MouseButtonRelease:
            if self.__check_box.isEnabled():
                self.__check_box.click()
            return True
        return super().eventFilter(watched, event)
