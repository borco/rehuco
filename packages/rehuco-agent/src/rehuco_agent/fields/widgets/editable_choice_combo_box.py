"""An editable combo box offering known texts, as a value widget ([[plugins#field-toolkit]], #678)."""

from collections.abc import Sequence

from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtWidgets import QComboBox, QWidget


class EditableChoiceComboBox(QComboBox):
    """A ``QComboBox`` offering known texts that any other text can still be typed beside -- a license id the scan
    writes, or one it never has -- with the value-widget contract: :attr:`value`, ``value_changed`` and
    :meth:`set_value`, so a field binds it through :meth:`~rehuco_agent.fields.field.Field.bind_value_widget`.

    The value is the line's text, whether picked or typed, and empty at first. Where :class:`SingleChoiceComboBox`
    is a closed list, this one is a hint: a stored text no choice names shows as it is.

    :param choices: the texts offered, in order.
    :param parent: optional Qt parent.
    """

    value_changed = Signal(str)

    def __init__(self, choices: Sequence[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.addItems(list(choices))
        self.setCurrentIndex(-1)
        self.editTextChanged.connect(self.value_changed.emit)

    @property
    def value(self) -> str:
        """The text shown, picked or typed; the value-widget contract's getter."""
        return self.currentText()

    @value.setter
    def value(self, value: str) -> None:
        self.set_value(value)

    def set_value(self, value: str) -> None:
        """Show ``value`` without re-emitting ``value_changed`` (the echo guard).

        The text check is what keeps the cursor where it is when a keystroke is echoed back into the line.

        :param value: the text to show.
        """
        if self.currentText() != value:
            with QSignalBlocker(self):
                self.setCurrentText(value)
