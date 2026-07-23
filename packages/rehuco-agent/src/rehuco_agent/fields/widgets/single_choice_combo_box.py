"""A single-select combo-box value widget for a fixed choice set ([[plugins#field-toolkit]])."""

from collections.abc import Sequence

from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtWidgets import QComboBox, QWidget


class SingleChoiceComboBox(QComboBox):
    """A ``QComboBox`` over a fixed ``(value, label)`` choice set, exposing the value-widget contract
    ([[plugins#field-toolkit]]): a ``value`` property, a ``value_changed`` signal, and a ``set_value``
    slot -- so a single-choice field binds through
    :meth:`~rehuco_agent.fields.field.Field.bind_value_widget` like every other content field, and the
    echo guard lives here, once.

    Each choice carries its **value** as item data and its **label** as display text, so a value that
    reads differently from how it shows (a ``""`` no-selection sentinel behind a ``"(no type)"``
    placeholder, a block key behind a title-cased label) round-trips as its value, never its label.
    :attr:`value` reports the selected item's data; :meth:`set_value` selects the item whose data
    matches, under a signal-blocking guard so a bound model change never bounces back out as an edit.

    :param choices: the fixed, ordered ``(value, label)`` pairs; the value is stored, the label shown.
    :param parent: optional Qt parent.
    """

    value_changed = Signal(str)

    def __init__(self, choices: Sequence[tuple[str, str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        for value, label in choices:
            self.addItem(label, value)
        self.currentIndexChanged.connect(lambda _index: self.value_changed.emit(self.value))

    @property
    def value(self) -> str:
        """The selected choice's value (its item data), or ``""`` when nothing is selected
        (the value-widget contract getter)."""
        data = self.currentData()
        return data if isinstance(data, str) else ""

    @value.setter
    def value(self, value: str) -> None:
        self.set_value(value)

    def set_value(self, value: str) -> None:
        """Select the choice whose value is ``value`` without re-emitting ``value_changed`` (the echo
        guard). An unknown value leaves the selection unchanged.

        :param value: the value to select.
        """
        index = self.findData(value)
        if index != -1 and index != self.currentIndex():
            with QSignalBlocker(self):
                self.setCurrentIndex(index)
