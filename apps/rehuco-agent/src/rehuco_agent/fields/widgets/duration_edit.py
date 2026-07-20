"""A duration editor: human text (`1h 30m`) kept in sync with a raw-seconds `QSpinBox`."""

import re
from typing import Final, cast

from borco_pyside.core import SimpleProperty
from borco_pyside.theming import GlyphActionIconThemeHandler
from borco_pyside.widgets import equal_width_row, parsed_value_or_reset, resync_line_edit, toggle_dynamic_property
from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QLineEdit, QSpinBox, QWidget

from ...glyphs import CLEAR_ACTION_GLYPH
from ..colors import WARNING_COLOR


class DurationEdit(QWidget):
    """A duration editor: human text kept in sync with a raw-seconds ``QSpinBox``, exposing only
    ``value``/``value_changed`` -- a caller cannot reach in and desync the line edit, the spin box,
    and ``value`` from each other (mirrors :class:`~borco_pyside.widgets.Rating`'s "wrap, don't
    subclass" shape).

    The line edit accepts a run of ``<number><unit>`` tokens (``1h``, ``1hour``, ``2hours 30mins``,
    ``1h 30m 15s``, or a bare number with no unit at all, taken as seconds) via :meth:`parse` --
    including text dropped onto it, which a ``QLineEdit`` accepts by default. The spin box is a
    plain integer editor over the raw seconds -- never a parsed formatted string
    ([[field-schema#ms-leak-history]]'s ms-vs-seconds leak was caused by exactly that:
    reconstructing the stored value from its own coarse display). Editing either updates ``value``;
    the other then follows via :attr:`value_changed`.

    :param parent: optional Qt parent.
    """

    MINIMUM: Final = 0
    MAXIMUM: Final = 2_147_483_647

    UNIT_SECONDS: Final = {
        "hours": 3600,
        "hour": 3600,
        "h": 3600,
        "minutes": 60,
        "minute": 60,
        "mins": 60,
        "min": 60,
        "m": 60,
        "seconds": 1,
        "second": 1,
        "secs": 1,
        "sec": 1,
        "s": 1,
    }
    """Recognized unit words/abbreviations (case-insensitive) and their length in seconds."""

    TOKEN_PATTERN: Final = re.compile(
        r"(\d+)\s*(" + "|".join(sorted(UNIT_SECONDS, key=len, reverse=True)) + ")",
        re.IGNORECASE,
    )
    """One ``<number><unit>`` token, built from :attr:`UNIT_SECONDS`'s own keys rather than a second,
    hand-duplicated word list -- sorted longest-first so e.g. ``"hours"`` isn't cut short by the bare
    ``"h"`` abbreviation (a regex alternation tries alternatives in listed order, not longest-match).
    Anchored at an arbitrary offset via ``match(text, pos)`` in :meth:`__parse_tokens` rather than
    scanned for, so a run of tokens can be validated as covering the *entire* input, with no
    unrecognized leftover text silently ignored."""

    WARNING_STYLESHEET: Final = f'QLineEdit[warning="true"] {{ color: {WARNING_COLOR}; }}'
    """Paints the line edit's text in the warning color while it holds non-blank, unparseable text."""

    value_changed = Signal(int)
    value = SimpleProperty(0)
    """The current duration in whole seconds; ``set_value`` is the slot-usable setter
    ([[plugins#field-toolkit]] bindings)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__line_edit: Final = QLineEdit(self)
        self.__line_edit.setToolTip("Formatted duration (e.g. 1h 30m)")
        self.__line_edit.setStyleSheet(self.WARNING_STYLESHEET)

        self.__spin_box: Final = QSpinBox(self)
        self.__spin_box.setRange(self.MINIMUM, self.MAXIMUM)
        self.__spin_box.setToolTip("Duration in seconds")

        # QSpinBox always has an internal line edit once constructed; cast rather than a runtime
        # None-check that could never actually be exercised (an untestable, permanently-dead branch).
        spin_box_line_edit = cast(QLineEdit, self.__spin_box.lineEdit())
        clear_action = spin_box_line_edit.addAction(QIcon(), QLineEdit.ActionPosition.TrailingPosition)
        GlyphActionIconThemeHandler(
            clear_action, CLEAR_ACTION_GLYPH.codepoint, CLEAR_ACTION_GLYPH.family, parent=clear_action
        )
        clear_action.setToolTip("Clear")
        clear_action.setVisible(False)
        clear_action.triggered.connect(self.__clear_spin_box)

        equal_width_row(self, self.__line_edit, self.__spin_box)

        self.__line_edit.textChanged.connect(self.__on_text_changed)
        self.__spin_box.valueChanged.connect(self.set_value)  # type: ignore[attr-defined]
        self.value_changed.connect(self.__render)
        self.value_changed.connect(lambda value: clear_action.setVisible(value != self.MINIMUM))

    @classmethod
    def parse(cls, text: str) -> int | None:
        """Parse human duration text into whole seconds.

        Accepts a run of ``<number><unit>`` tokens (``1h``, ``1hour``, ``2hours 30mins``,
        ``1h 30m 15s``, ``30m 45s``, ...), case-insensitive and optionally space-separated -- or,
        with no unit at all, a bare non-negative integer taken directly as seconds (``123456``).

        :param text: the text to parse.
        :returns: the total whole seconds, or ``None`` if ``text`` is blank or not a recognized shape.
        """
        text = text.strip()
        if not text:
            return None
        if text.isdigit():
            return int(text)
        return cls.__parse_tokens(text)

    @classmethod
    def __parse_tokens(cls, text: str) -> int | None:
        """Parse a run of ``<number><unit>`` tokens covering the entire text.

        :param text: the text to parse -- already stripped by :meth:`parse`, the only caller, so it
            can never end in whitespace (an internal invariant, not re-validated here).
        :returns: the summed seconds, or ``None`` if any part of ``text`` doesn't match a token.
        """
        total = 0
        pos = 0
        length = len(text)
        matched_any = False
        while pos < length:
            while text[pos].isspace():
                pos += 1
            match = cls.TOKEN_PATTERN.match(text, pos)
            if match is None:
                return None
            amount, unit = match.groups()
            total += int(amount) * cls.UNIT_SECONDS[unit.lower()]
            pos = match.end()
            matched_any = True
        return total if matched_any else None

    @staticmethod
    def format(seconds: int) -> str:
        """Render whole seconds as ``2h 15m`` per [[field-schema#duration-format]].

        :param seconds: the duration in whole seconds.
        :returns: the formatted string; ``""`` for ``0`` (not ``"0s"``).
        """
        hours, remainder = divmod(seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        parts: list[str] = []
        if hours:
            parts.append(f"{hours}h")
        if minutes:
            parts.append(f"{minutes}m")
        if secs and not hours:
            parts.append(f"{secs}s")
        return " ".join(parts)

    def __on_text_changed(self, text: str) -> None:
        """Write a keystroke (or drop) through to :attr:`value`, or reset it to :attr:`MINIMUM` once
        the line edit is emptied (e.g. by its clear action).

        A blank line edit is treated as an explicit reset, not "incomplete typing" -- distinct from
        genuinely unparseable non-empty text (``"1h 3"``), which is left unwritten as before, so
        mid-keystroke typing is never clobbered. Without this, clearing the line edit left the spin
        box (and ``value``) holding the old number, since :meth:`parse` itself treats blank text as
        unparseable (``None``), not zero (confirmed empirically, #24).

        :param text: the line edit's current text.
        """
        value = parsed_value_or_reset(text, self.MINIMUM, self.parse)
        toggle_dynamic_property(self.__line_edit, "warning", value is None)
        if value is not None:
            self.value = value

    def __render(self, value: int) -> None:
        """Re-sync the line edit and the spin box to ``value`` (echo guard for each).

        :param value: the new value.
        """
        resync_line_edit(self.__line_edit, value, self.parse, self.format)
        if self.__spin_box.value() != value:
            with QSignalBlocker(self.__spin_box):
                self.__spin_box.setValue(value)

    def __clear_spin_box(self) -> None:
        """Reset :attr:`value` to :attr:`MINIMUM` and restore focus to the spin box.

        Deliberately not the app-wide ``LineEditClearActionFilter``'s job (see its docstring): a
        spin box's internal line edit needs a *value* reset, not just an emptied display -- clearing
        only the text there leaves ``value()`` untouched, so ``interpretText()`` (e.g. a focus
        change) snaps the old number right back (confirmed empirically).
        """
        self.value = self.MINIMUM
        self.__spin_box.setFocus()
