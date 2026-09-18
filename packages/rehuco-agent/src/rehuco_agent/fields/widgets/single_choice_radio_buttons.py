"""A single-select radio-button group value widget for a fixed choice set ([[plugins#field-toolkit]])."""

from collections.abc import Sequence
from typing import Final

from borco_pyside.widgets import FlowLayout
from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtWidgets import QAbstractButton, QButtonGroup, QRadioButton, QWidget


class SingleChoiceRadioButtons(QWidget):
    """A `FlowLayout` of radio buttons over a fixed ``(value, label)`` choice set, exposing the
    value-widget contract ([[plugins#field-toolkit]]): a ``value`` property, a ``value_changed`` signal,
    and a ``set_value`` slot -- so a single-choice field binds through
    :meth:`~rehuco_agent.fields.field.Field.bind_value_widget` like every other content field.

    Every choice is visible at once and exactly one button is checked once :meth:`set_value` has seeded
    the group (`bind_value_widget` always does this immediately after construction), so the row never
    settles in a state :attr:`value` cannot name. :attr:`value` reports the checked button's value;
    :meth:`set_value` checks the matching button under a signal-blocking echo guard so a bound model
    change never bounces back out as an edit.

    Radios stop scaling somewhere around six or seven entries -- past that a combo reads better; this
    widget is a deliberate trade for a small, fully-visible choice set (#310), not the general answer for
    a growing one.

    :param choices: the fixed, ordered ``(value, label)`` pairs; the value is stored, the label shown.
    :param disabled: values whose button is shown but not selectable -- e.g. the document's current type
        when it names no installed plugin: still shown as the type in effect, but not re-pickable.
    :param parent: optional Qt parent.
    """

    value_changed = Signal(str)

    def __init__(
        self,
        choices: Sequence[tuple[str, str]],
        disabled: Sequence[str] = (),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        disabled_values = set(disabled)
        layout = FlowLayout(self)
        self.__group: Final = QButtonGroup(self)
        self.__group.setExclusive(True)
        self.__buttons: Final[dict[str, QRadioButton]] = {}
        self.__values: Final[dict[QAbstractButton, str]] = {}
        for value, label in choices:
            button = QRadioButton(label)
            button.setEnabled(value not in disabled_values)
            layout.addWidget(button)
            self.__group.addButton(button)
            self.__buttons[value] = button  # pylint: disable=unsupported-assignment-operation
            self.__values[button] = value  # pylint: disable=unsupported-assignment-operation
        self.__group.buttonToggled.connect(self.__on_toggled)

    @property
    def header_height(self) -> int:
        """One radio button's natural height, stable regardless of how many rows the `FlowLayout`
        wraps into (`HeaderPinned` contract, [[plugins#field-toolkit]])."""
        button = next(iter(self.__buttons.values()), None)
        return (button if button is not None else QRadioButton()).sizeHint().height()

    @property
    def value(self) -> str:
        """The checked choice's value, or ``""`` when nothing is checked yet (the value-widget contract
        getter)."""
        for value, button in self.__buttons.items():
            if button.isChecked():
                return value
        return ""

    @value.setter
    def value(self, value: str) -> None:
        self.set_value(value)

    def set_value(self, value: str) -> None:
        """Check the button for ``value`` without re-emitting ``value_changed`` (the echo guard). An
        unknown value leaves the selection unchanged.

        :param value: the value to select.
        """
        button = self.__buttons.get(value)
        if button is not None and not button.isChecked():
            with QSignalBlocker(self.__group):
                button.setChecked(True)

    def __on_toggled(self, button: QAbstractButton, checked: bool) -> None:
        """Emit ``value_changed`` with the newly-checked button's value.

        :param button: the button whose checked state changed -- always one of this group's own, so
            the value lookup cannot miss.
        :param checked: ``True`` only for the button that *became* checked -- the group's automatic
            uncheck of the previous button also fires this signal, which this filters out.
        """
        if checked:
            self.value_changed.emit(self.__values[button])
