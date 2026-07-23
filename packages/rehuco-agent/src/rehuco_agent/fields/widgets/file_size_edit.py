"""A file-size editor: human text (`1.4G`) kept in sync with a raw-bytes `UnboundedSpinBox`."""

import re
from typing import Final

import humanize
import humanize.filesize
from borco_pyside.core import SimpleProperty
from borco_pyside.widgets import (
    UnboundedSpinBox,
    equal_width_row,
    resync_line_edit,
    write_through_or_none,
)
from PySide6.QtWidgets import QLineEdit, QWidget

from ..colors import WARNING_COLOR


class FileSizeEdit(QWidget):
    """A file-size editor: human text kept in sync with a raw-bytes ``UnboundedSpinBox``, exposing only
    ``value``/``value_changed`` -- mirrors :class:`~rehuco_agent.fields.widgets.DurationEdit`'s
    "wrap, don't subclass" shape.

    Formatted via ``humanize.naturalsize(value, gnu=True)`` (GNU ``ls -sh`` style: ``1.4G``, ``300B``
    -- base 1024, single-letter suffix, no space). :meth:`parse` accepts that same shape back, plus a
    bare number with no suffix at all (taken as bytes, matching the field toolkit's other numeric
    editors). Backed by :class:`~borco_pyside.widgets.UnboundedSpinBox` (#40), not ``QSpinBox`` -- a
    single ~2 GB resource already sits at the C++ int32 ceiling ([[field-schema#duration-size]]).

    ``value`` may also be ``None`` -- unmeasured, distinct from a genuine ``0`` bytes
    ([[field-schema#deferred-items]]): emptying the line edit writes ``None`` through rather than
    resetting to ``0``. The inner spin box has no such empty state of its own -- it shows ``0`` while
    ``value`` is ``None``, with the line edit left blank as the one place the empty state is actually
    visible.

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

    value = SimpleProperty[int | None](None)
    """The current size in whole bytes, an unbounded Python ``int``, or ``None`` when unmeasured;
    ``set_value`` is the slot-usable setter ([[plugins#field-toolkit]] bindings)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__line_edit: Final = QLineEdit(self)
        self.__line_edit.setToolTip("Formatted file size (e.g. 1.4G)")
        self.__line_edit.setStyleSheet(self.WARNING_STYLESHEET)

        self.__spin_box: Final = UnboundedSpinBox(minimum=0)
        self.__spin_box.setToolTip("Size in bytes")

        self.__rendering = False
        """True only while :meth:`__render` is programmatically syncing the spin box -- guards
        :meth:`__on_spin_box_value_changed` so that sync is never mistaken for a user edit (see its
        own docstring)."""

        equal_width_row(self, self.__line_edit, self.__spin_box)

        self.__line_edit.textChanged.connect(self.__on_text_changed)
        self.__spin_box.value_changed.connect(self.__on_spin_box_value_changed)  # type: ignore[attr-defined]
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
    def format(size: int | None) -> str:
        """Render whole bytes as GNU ``ls -sh`` style text.

        :param size: the size in bytes, or ``None`` when unmeasured.
        :returns: the formatted string, e.g. ``"1.4G"``, ``"300B"``; ``""`` for ``None`` (unmeasured);
            ``"0B"`` -- honestly, not blank -- for a genuine ``0``.
        """
        if size is None:
            return ""
        return humanize.naturalsize(size, gnu=True)

    def __on_text_changed(self, text: str) -> None:
        """Write a keystroke through to :attr:`value`, or reset it to ``None`` (unmeasured) once the
        line edit is emptied.

        A blank line edit is treated as an explicit reset, not "incomplete typing" -- distinct from
        genuinely unparseable non-empty text, which is left unwritten so mid-keystroke typing is
        never clobbered (mirrors :class:`~rehuco_agent.fields.widgets.DurationEdit`'s own guard).

        :param text: the line edit's current text.
        """
        write_through_or_none(self.__line_edit, text, self.parse, lambda value: setattr(self, "value", value))

    def __on_spin_box_value_changed(self, value: int) -> None:
        """Write the spin box's own value through to :attr:`value`, unless it just changed because
        :meth:`__render` is itself syncing it to match -- not a real user edit.

        Deliberately not a plain ``self.__spin_box.value_changed.connect(self.set_value)`` (the
        pre-#101 shape): :class:`~borco_pyside.widgets.UnboundedSpinBox` syncs its own displayed text
        by listening to its *own* ``value_changed`` (unlike a native ``QSpinBox``, which updates its
        display directly regardless of signal state) -- so silencing it with a blanket
        ``QSignalBlocker`` during :meth:`__render`'s ``0``-for-``None`` substitution, as tried first,
        also breaks that internal self-sync (confirmed empirically): the stored value updates but the
        spin box's own displayed text does not. Guarding the forwarding here instead leaves the spin
        box's own signal free to fire and keep its own display in sync.

        :param value: the spin box's new value.
        """
        if not self.__rendering:
            self.value = value

    def __render(self, value: int | None) -> None:
        """Re-sync the line edit and the spin box to ``value`` (echo guard for each).

        The inner spin box has no empty state of its own -- it shows ``0`` while ``value`` is
        ``None``, matching the line edit, which is blank.

        :param value: the new value, or ``None`` when unmeasured.
        """
        resync_line_edit(self.__line_edit, value, self.parse, self.format)
        spin_box_value = value if value is not None else 0
        if self.__spin_box.value != spin_box_value:
            self.__rendering = True
            try:
                self.__spin_box.setValue(spin_box_value)
            finally:
                self.__rendering = False
