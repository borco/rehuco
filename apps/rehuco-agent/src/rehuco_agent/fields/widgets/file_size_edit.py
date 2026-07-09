"""A file-size editor: human text (`1.4G`) kept in sync with a raw-bytes `UnboundedSpinBox`."""

import re
from typing import Final

import humanize
import humanize.filesize
from borco_pyside.core import SimpleProperty
from borco_pyside.widgets import (
    UnboundedSpinBox,
    equal_width_row,
    parsed_value_or_reset,
    resync_line_edit,
    toggle_dynamic_property,
)
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLineEdit, QWidget

from rehuco_agent.fields.colors import WARNING_COLOR


class FileSizeEdit(QWidget):
    """A file-size editor: human text kept in sync with a raw-bytes ``UnboundedSpinBox``, exposing only
    ``value``/``value_changed`` -- mirrors :class:`~rehuco_agent.fields.widgets.DurationEdit`'s
    "wrap, don't subclass" shape.

    Formatted via ``humanize.naturalsize(value, gnu=True)`` (GNU ``ls -sh`` style: ``1.4G``, ``300B``
    -- base 1024, single-letter suffix, no space). :meth:`parse` accepts that same shape back, plus a
    bare number with no suffix at all (taken as bytes, matching the field toolkit's other numeric
    editors). Backed by :class:`~borco_pyside.widgets.UnboundedSpinBox` (#40), not ``QSpinBox`` -- a
    single ~2 GB resource already sits at the C++ int32 ceiling ([[field-schema#duration-size]]).

    :param parent: optional Qt parent.
    """

    UNIT_MULTIPLIERS: Final = {
        letter: 1024 ** (index + 1) for index, letter in enumerate(humanize.filesize.suffixes["gnu"])
    }
    """Byte multiplier per GNU-style suffix letter, built from ``humanize``'s own suffix order
    (``humanize.filesize.suffixes["gnu"]``) rather than a second, hand-duplicated letter list."""

    UNIT_PATTERN: Final = re.compile(
        r"^([0-9]+(?:\.[0-9]+)?)\s*([B" + humanize.filesize.suffixes["gnu"] + r"]?)$", re.IGNORECASE
    )
    """One ``<number><unit>`` token -- a bare number, or one explicitly suffixed ``B`` (bytes, e.g.
    ``humanize``'s own ``"300B"`` for a sub-1024 value -- not part of ``suffixes["gnu"]``, which only
    covers the *scaled* letters), is bytes; a single GNU-style scale letter (case-insensitive) scales
    it by :attr:`UNIT_MULTIPLIERS`."""

    WARNING_STYLESHEET: Final = f'QLineEdit[warning="true"] {{ color: {WARNING_COLOR}; }}'
    """Paints the line edit's text in the warning color while it holds non-blank, unparseable text."""

    value_changed = Signal(object)
    value = SimpleProperty(0, value_type=object)
    """The current size in whole bytes, an unbounded Python ``int``; ``set_value`` is the slot-usable
    setter ([[plugins#field-toolkit]] bindings)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__line_edit: Final = QLineEdit(self)
        self.__line_edit.setToolTip("Formatted file size (e.g. 1.4G)")
        self.__line_edit.setStyleSheet(self.WARNING_STYLESHEET)

        self.__spin_box: Final = UnboundedSpinBox(minimum=0)
        self.__spin_box.setToolTip("Size in bytes")

        equal_width_row(self, self.__line_edit, self.__spin_box)

        self.__line_edit.textChanged.connect(self.__on_text_changed)
        self.__spin_box.value_changed.connect(self.set_value)  # type: ignore[attr-defined]
        self.value_changed.connect(self.__render)  # type: ignore[attr-defined]

    @classmethod
    def parse(cls, text: str) -> int | None:
        """Parse human size text into whole bytes.

        :param text: the text to parse.
        :returns: the size in bytes, or ``None`` if ``text`` is blank or not a recognized shape.
        """
        text = text.strip()
        if not text:
            return None
        match = cls.UNIT_PATTERN.match(text)
        if match is None:
            return None
        amount, unit = match.groups()
        multiplier = cls.UNIT_MULTIPLIERS.get(unit.upper(), 1)
        return round(float(amount) * multiplier)

    @staticmethod
    def format(size: int) -> str:
        """Render whole bytes as GNU ``ls -sh`` style text.

        :param size: the size in bytes.
        :returns: the formatted string, e.g. ``"1.4G"``, ``"300B"``; ``""`` for ``0`` (not ``"0B"``),
            matching :meth:`~rehuco_agent.fields.widgets.DurationEdit.format`'s "0 renders blank"
            convention -- without it, clearing the line edit to blank always snapped back to ``"0B"``
            (:meth:`__render`'s echo guard treats blank text as unparseable, not zero).
        """
        return humanize.naturalsize(size, gnu=True) if size else ""

    def __on_text_changed(self, text: str) -> None:
        """Write a keystroke through to :attr:`value`, or reset it to ``0`` once the line edit is
        emptied.

        A blank line edit is treated as an explicit reset, not "incomplete typing" -- distinct from
        genuinely unparseable non-empty text, which is left unwritten so mid-keystroke typing is
        never clobbered (mirrors :class:`~rehuco_agent.fields.widgets.DurationEdit`'s own guard).

        :param text: the line edit's current text.
        """
        value = parsed_value_or_reset(text, 0, self.parse)
        toggle_dynamic_property(self.__line_edit, "warning", value is None)
        if value is not None:
            self.value = value

    def __render(self, value: int) -> None:
        """Re-sync the line edit and the spin box to ``value`` (echo guard for each).

        :param value: the new value.
        """
        resync_line_edit(self.__line_edit, value, self.parse, self.format)
        if self.__spin_box.value != value:
            self.__spin_box.setValue(value)
