"""An integer spin box with no C++ `int` (32-bit) ceiling, backed by a Python `int`."""

from typing import Final, override

from PySide6.QtCore import QSignalBlocker
from PySide6.QtGui import QValidator
from PySide6.QtWidgets import QAbstractSpinBox, QWidget

from ..core import SimpleProperty


class UnboundedSpinBox(QAbstractSpinBox):
    """A `QSpinBox`-like editor -- up/down buttons, keyboard entry, live editing -- with no C++ `int`
    ceiling: `QSpinBox` hard-caps at ``-2_147_483_648``..``2_147_483_647`` regardless of what
    `setRange` is given, because it stores its value as a native C++ ``int``. This subclasses
    `QAbstractSpinBox` directly instead (which, unlike `QSpinBox`, has no value storage of its own)
    and keeps :attr:`value` as a plain Python ``int``, so it accepts any integer Python can
    represent (a multi-terabyte size value overflows int32 by three to four orders of magnitude,
    which is the motivating case for this widget's existence).

    ``value_changed`` is ``Signal(object)`` and :attr:`value` forces ``value_type=object`` --
    *not* ``Signal(int)``/a native ``int`` Qt property, both of which marshal through C++ ``int``
    and would silently truncate or raise on a value outside int32, defeating the entire point. ``value``
    may also be ``None`` -- an explicit empty state, distinct from any stored ``0``: a blank line
    edit writes ``None`` through, and ``None`` renders as blank text rather than the string ``"None"``.

    :attr:`value`/``set_value`` (the plain ``SimpleProperty`` and its synthesized slot) write
    through unclamped -- use :meth:`setValue` instead, the ``QSpinBox.setValue`` counterpart, when
    ``minimum``/``maximum`` should be enforced (e.g. a field's echo guard reflecting a model value
    that may fall outside this editor's configured range).

    :param value: the starting value; clamped to ``minimum``/``maximum`` if given, or ``None`` for the
        empty state.
    :param minimum: the lowest value accepted; ``None`` for no lower bound.
    :param maximum: the highest value accepted; ``None`` for no upper bound.
    :param single_step: the amount `stepBy` (the up/down buttons, arrow keys, wheel) changes the value by.
    :param parent: optional Qt parent.
    """

    value = SimpleProperty[int | None](0, value_type=object)
    """The current value, an unbounded Python ``int``, or ``None`` for the empty state; ``set_value``
    is the slot-usable setter (for binding to signals)."""

    def __init__(
        self,
        value: int | None = 0,
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

    def setValue(self, value: int | None) -> None:  # pylint: disable=invalid-name
        """Set :attr:`value`, boxed into ``minimum``/``maximum`` -- the ``QSpinBox.setValue``
        counterpart; a raw ``value =`` assignment or ``set_value`` slot call writes through unclamped.
        ``None`` (the empty state) is never clamped -- there is nothing to box into range.

        Named to match ``QSpinBox``'s own method, not ``snake_case`` -- ``set_value`` is already taken,
        as the unclamped slot ``SimpleProperty`` itself synthesizes for :attr:`value`.

        :param value: the value to set, or ``None`` for the empty state.
        """
        self.value = value if value is None else self.__clamp(value)

    @override
    def stepBy(self, steps: int) -> None:
        self.setValue(self.__effective_value() + steps * self.__single_step)

    @override
    def stepEnabled(self) -> QAbstractSpinBox.StepEnabledFlag:
        flags = QAbstractSpinBox.StepEnabledFlag.StepNone
        value = self.__effective_value()
        if self.__maximum is None or value < self.__maximum:
            flags |= QAbstractSpinBox.StepEnabledFlag.StepUpEnabled
        if self.__minimum is None or value > self.__minimum:
            flags |= QAbstractSpinBox.StepEnabledFlag.StepDownEnabled
        return flags

    def __effective_value(self) -> int:
        """:attr:`value`, or -- while it holds the empty state (``None``) -- the value stepping from
        empty should be measured against: :attr:`minimum` if bounded below, ``0`` otherwise.

        :returns: the value to step/compare from.
        """
        if self.value is not None:
            return self.value
        return self.__minimum if self.__minimum is not None else 0

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
        stripped = input.strip()
        if not stripped:
            return ""
        try:
            return str(self.__clamp(int(stripped)))
        except ValueError:
            return str(self.value) if self.value is not None else ""

    def __on_text_changed(self, text: str) -> None:
        """Write a keystroke through to :attr:`value` once it parses as a whole number, or reset it to
        the empty state (``None``) once the line edit is emptied.

        A blank line edit is treated as an explicit reset, not "incomplete typing" -- distinct from
        genuinely unparseable non-empty text (e.g. a bare ``-`` mid-typing), which is left unwritten so
        mid-keystroke typing is never clobbered.

        :param text: the line edit's current text.
        """
        stripped = text.strip()
        if not stripped:
            self.value = None
            return
        try:
            parsed = int(stripped)
        except ValueError:
            return
        self.setValue(parsed)

    def __render(self, value: int | None) -> None:
        """Re-sync the line edit to ``value`` (echo guard).

        :param value: the new value, or ``None`` for the empty state (rendered as blank text).
        """
        text = str(value) if value is not None else ""
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
