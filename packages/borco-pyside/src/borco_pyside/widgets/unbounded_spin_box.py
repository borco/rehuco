"""An integer spin box with no C++ `int` (32-bit) ceiling, backed by a Python `int`."""

from typing import Final, override

from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtGui import QValidator
from PySide6.QtWidgets import QAbstractSpinBox, QWidget

from ..core import SimpleProperty


class UnboundedSpinBox(QAbstractSpinBox):
    """A `QSpinBox`-like editor -- up/down buttons, keyboard entry, live editing -- with no C++ `int`
    ceiling: `QSpinBox` hard-caps at ``-2_147_483_648``..``2_147_483_647`` regardless of what
    `setRange` is given, because it stores its value as a native C++ ``int``. This subclasses
    `QAbstractSpinBox` directly instead (which, unlike `QSpinBox`, has no value storage of its own)
    and keeps :attr:`value` as a plain Python ``int``, so it accepts any integer Python can
    represent ([[field-schema#duration-size]]'s ``size`` field type is the motivating consumer -- a
    multi-terabyte catalog overflows int32 by three to four orders of magnitude, #40).

    ``value_changed`` is ``Signal(object)`` and :attr:`value` forces ``value_type=object`` --
    *not* ``Signal(int)``/a native ``int`` Qt property, both of which marshal through C++ ``int``
    and would silently truncate or raise on a value outside int32, defeating the entire point.

    :attr:`value`/``set_value`` (the plain ``SimpleProperty`` and its synthesized slot) write
    through unclamped -- use :meth:`setValue` instead, the ``QSpinBox.setValue`` counterpart, when
    ``minimum``/``maximum`` should be enforced (e.g. a field's echo guard reflecting a model value
    that may fall outside this editor's configured range).

    :param value: the starting value; clamped to ``minimum``/``maximum`` if given.
    :param minimum: the lowest value accepted; ``None`` for no lower bound.
    :param maximum: the highest value accepted; ``None`` for no upper bound.
    :param single_step: the amount `stepBy` (the up/down buttons, arrow keys, wheel) changes the value by.
    :param parent: optional Qt parent.
    """

    value_changed = Signal(object)
    value = SimpleProperty(0, value_type=object)
    """The current value, an unbounded Python ``int``; ``set_value`` is the slot-usable setter
    ([[plugins#field-toolkit]] bindings)."""

    def __init__(
        self,
        value: int = 0,
        minimum: int | None = None,
        maximum: int | None = None,
        single_step: int = 1,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.__minimum: Final = minimum
        self.__maximum: Final = maximum
        self.__single_step: Final = single_step

        self.lineEdit().textChanged.connect(self.__on_text_changed)
        self.value_changed.connect(self.__render)  # type: ignore[attr-defined]
        self.setValue(value)
        self.__render(self.value)

    def minimum(self) -> int | None:
        """The lowest value accepted, or ``None`` for no lower bound (unlike ``QSpinBox.minimum``,
        which always reads back an actual ``int``)."""
        return self.__minimum

    def maximum(self) -> int | None:
        """The highest value accepted, or ``None`` for no upper bound (unlike ``QSpinBox.maximum``,
        which always reads back an actual ``int``)."""
        return self.__maximum

    def setValue(self, value: int) -> None:  # pylint: disable=invalid-name
        """Set :attr:`value`, boxed into ``minimum``/``maximum`` -- the ``QSpinBox.setValue``
        counterpart; a raw ``value =`` assignment or ``set_value`` slot call writes through unclamped.

        Named to match ``QSpinBox``'s own method, not ``snake_case`` -- ``set_value`` is already taken,
        as the unclamped slot ``SimpleProperty`` itself synthesizes for :attr:`value`.

        :param value: the value to set.
        """
        self.value = self.__clamp(value)

    @override
    def stepBy(self, steps: int) -> None:
        self.setValue(self.value + steps * self.__single_step)

    @override
    def stepEnabled(self) -> QAbstractSpinBox.StepEnabledFlag:
        flags = QAbstractSpinBox.StepEnabledFlag.StepNone
        if self.__maximum is None or self.value < self.__maximum:
            flags |= QAbstractSpinBox.StepEnabledFlag.StepUpEnabled
        if self.__minimum is None or self.value > self.__minimum:
            flags |= QAbstractSpinBox.StepEnabledFlag.StepDownEnabled
        return flags

    @override
    def validate(self, input: str, pos: int) -> tuple[QValidator.State, str, int]:  # pylint: disable=redefined-builtin
        stripped = input.strip()
        if stripped in ("", "-", "+"):
            return QValidator.State.Intermediate, input, pos
        try:
            int(stripped)
        except ValueError:
            return QValidator.State.Invalid, input, pos
        return QValidator.State.Acceptable, input, pos

    @override
    def fixup(self, input: str) -> str:  # pylint: disable=redefined-builtin
        try:
            return str(self.__clamp(int(input.strip())))
        except ValueError:
            return str(self.value)

    def __on_text_changed(self, text: str) -> None:
        """Write a keystroke through to :attr:`value` once it parses as a whole number.

        :param text: the line edit's current text.
        """
        try:
            parsed = int(text.strip())
        except ValueError:
            return
        self.setValue(parsed)

    def __render(self, value: int) -> None:
        """Re-sync the line edit to ``value`` (echo guard).

        :param value: the new value.
        """
        text = str(value)
        if self.lineEdit().text() != text:
            with QSignalBlocker(self.lineEdit()):
                self.lineEdit().setText(text)

    def __clamp(self, value: int) -> int:
        """Box ``value`` into ``minimum``/``maximum``.

        :param value: the value to box.
        :returns: ``value``, boxed into range.
        """
        if self.__minimum is not None:
            value = max(value, self.__minimum)
        if self.__maximum is not None:
            value = min(value, self.__maximum)
        return value
