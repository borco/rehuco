"""A multi-select checkbox group value widget for the `multi_choice` field ([[plugins#field-toolkit]])."""

from collections.abc import Sequence
from typing import Final

from borco_pyside.widgets import FlowLayout
from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtWidgets import QCheckBox, QWidget


class ChoiceCheckBoxes(QWidget):
    """A `FlowLayout` of checkboxes over a fixed ``choices`` set, exposing the value-widget contract
    ([[plugins#field-toolkit]]): ``value: list[str]`` + ``value_changed`` + ``set_value`` -- so
    ``multi_choice`` binds through
    :meth:`~rehuco_agent.fields.field.Field.bind_value_widget` like every other content field.

    :attr:`value` is always reported in ``choices`` order regardless of click order (a caller cannot
    desync the reported selection from the boxes), and :meth:`set_value` resyncs every box under a
    signal-blocking echo guard so a bound model change never bounces back out as an edit.

    :param choices: the fixed, ordered set of selectable values.
    :param parent: optional Qt parent.
    """

    value_changed = Signal(object)

    def __init__(self, choices: Sequence[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__choices: Final = tuple(choices)
        layout = FlowLayout(self)
        self.__checkboxes: Final[dict[str, QCheckBox]] = {}
        for choice in self.__choices:
            checkbox = QCheckBox(choice)
            layout.addWidget(checkbox)
            checkbox.toggled.connect(self.__on_toggled)
            self.__checkboxes[choice] = checkbox  # pylint: disable=unsupported-assignment-operation

    @property
    def header_height(self) -> int:
        """One checkbox's natural height, stable regardless of how many rows the `FlowLayout` wraps
        into (`HeaderPinned` contract, [[plugins#field-toolkit]])."""
        checkbox = next(iter(self.__checkboxes.values()), None)
        return (checkbox if checkbox is not None else QCheckBox()).sizeHint().height()

    @property
    def value(self) -> list[str]:
        """The currently-checked choices, in ``choices`` order (the value-widget contract getter)."""
        return [choice for choice in self.__choices if self.__checkboxes[choice].isChecked()]

    @value.setter
    def value(self, value: list[str]) -> None:
        self.set_value(value)

    def set_value(self, value: list[str]) -> None:
        """Resync every checkbox to ``value`` without re-emitting ``value_changed`` (the echo guard).

        :param value: the selection to apply; entries not in ``choices`` are ignored.
        """
        selected = set(value)
        for choice, checkbox in self.__checkboxes.items():
            wanted = choice in selected
            if checkbox.isChecked() != wanted:
                with QSignalBlocker(checkbox):
                    checkbox.setChecked(wanted)

    def __on_toggled(self, _checked: bool) -> None:
        """Emit ``value_changed`` with the full recomputed selection whenever any box toggles.

        :param _checked: the toggled box's new state, unused -- :attr:`value` reads every box live.
        """
        self.value_changed.emit(self.value)
