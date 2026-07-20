"""A partial-precision date editor: free-text entry parsed from a range of common human date shapes,
with an inline calendar popup.
"""

import re
from datetime import date as Date
from datetime import datetime
from typing import Final

from borco_pyside.core import SimpleProperty
from borco_pyside.theming import GlyphActionIconThemeHandler
from dateutil import parser as dateutil_parser
from PySide6.QtCore import QDate, QPoint, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QCalendarWidget, QHBoxLayout, QLineEdit, QWidget

from ...glyphs import CALENDAR_ACTION_GLYPH


class DateEdit(QWidget):
    """A partial-precision (``YYYY`` / ``YYYY-MM`` / ``YYYY-MM-DD``) date editor, exposing only
    ``value``/``value_changed`` -- a caller cannot reach in and desync the line edit from ``value``
    (mirrors :class:`~borco_pyside.widgets.Rating`'s "wrap, don't subclass" shape).

    The internal ``QLineEdit`` accepts a range of common human date shapes -- ``2026``, ``2026/10``,
    ``2026.10.20``, ``2026-10-20``, ``January 2026``, ``2026 Jan``, ``Jan 1, 2026`` -- parsed by
    :meth:`parse` into the canonical ``value`` on every keystroke; text that doesn't (yet, or ever)
    parse simply isn't written through, rather than rejected or auto-corrected, so incomplete typing
    never clobbers ``value``. A trailing calendar action opens a small popup ``QCalendarWidget``;
    picking a date writes the full ``YYYY-MM-DD`` straight to ``value``, without going through
    :meth:`parse` at all.

    :param parent: optional Qt parent.
    """

    NUMERIC_PATTERN: Final = re.compile(r"^(\d{4})(?:([./-])(\d{1,2})(?:\2(\d{1,2}))?)?$")
    """Matches the purely-numeric partial-date shapes, with a single separator (``/``, ``.``, or
    ``-``) used consistently between parts. Handled directly, never handed to :mod:`dateutil`, which
    silently drops the month from a dot-separated ``YYYY.MM`` (confirmed empirically, #24)."""

    value_changed = Signal(str)
    value = SimpleProperty("")
    """The current canonical ``YYYY``/``YYYY-MM``/``YYYY-MM-DD`` string (or ``""`` for unknown);
    ``set_value`` is the slot-usable setter ([[plugins#field-toolkit]] bindings)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__line_edit: Final = QLineEdit(self)
        self.__calendar: QCalendarWidget | None = None
        """Lazily built on first use and reused after -- see :meth:`__ensure_calendar`."""

        action = self.__line_edit.addAction(QIcon(), QLineEdit.ActionPosition.TrailingPosition)
        GlyphActionIconThemeHandler(
            action, CALENDAR_ACTION_GLYPH.codepoint, CALENDAR_ACTION_GLYPH.family, parent=action
        )
        action.setToolTip("Pick a date")
        action.triggered.connect(self.__open_calendar)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.__line_edit)

        self.__line_edit.textChanged.connect(self.__on_text_changed)
        self.value_changed.connect(self.__render)

    @classmethod
    def parse(cls, text: str) -> str | None:
        """Parse free-form date text into the canonical stored form.

        :param text: the text to parse.
        :returns: ``""`` for blank text, the canonical ``YYYY``/``YYYY-MM``/``YYYY-MM-DD`` string for
            text recognized as one of those precisions, or ``None`` if ``text`` isn't (yet, or ever
            going to be) one of them.
        """
        text = text.strip()
        if not text:
            return ""
        numeric = cls.__parse_numeric(text)
        if numeric is not None:
            return numeric
        return cls.__parse_human(text)

    @classmethod
    def __parse_numeric(cls, text: str) -> str | None:
        """Parse the purely-numeric ``Y``/``Y/M``/``Y/M/D`` shapes.

        :param text: the trimmed text to parse.
        :returns: the canonical string, or ``None`` if ``text`` doesn't match, or the date is
            calendar-invalid (e.g. month ``13``).
        """
        match = cls.NUMERIC_PATTERN.match(text)
        if not match:
            return None
        year_text, _separator, month_text, day_text = match.groups()
        year = int(year_text)
        if day_text is not None:
            month = int(month_text)
            day = int(day_text)
            try:
                Date(year, month, day)
            except ValueError:
                return None
            return f"{year:04d}-{month:02d}-{day:02d}"
        if month_text is not None:
            month = int(month_text)
            if not 1 <= month <= 12:
                return None
            return f"{year:04d}-{month:02d}"
        return f"{year:04d}"

    @classmethod
    def __parse_human(cls, text: str) -> str | None:
        """Parse free-text month-name shapes (``January 2026``, ``2026 Jan``, ``Jan 1, 2026``) via
        :mod:`dateutil`.

        Detects which of year/month/day were actually specified by parsing twice against two
        different sentinel defaults and comparing -- :mod:`dateutil`'s public API has no direct way
        to ask this (only its private, unstable ``_parse`` does). Calendar validity is a side effect:
        ``dateutil.parser.parse`` itself raises on an invalid date (e.g. day 30 in February).

        :param text: the trimmed text to parse.
        :returns: the canonical string, or ``None`` if unparseable, or has no year -- this schema has
            no precision level coarser than "year" (no bare month/day).
        """
        try:
            first = dateutil_parser.parse(text, default=datetime(1, 1, 1))
            second = dateutil_parser.parse(text, default=datetime(2, 2, 2))
        except dateutil_parser.ParserError, ValueError, OverflowError:
            return None
        year_known = first.year == second.year
        if not year_known:
            return None
        month_known = first.month == second.month
        day_known = first.day == second.day
        if day_known:
            return f"{first.year:04d}-{first.month:02d}-{first.day:02d}"
        if month_known:
            return f"{first.year:04d}-{first.month:02d}"
        return f"{first.year:04d}"

    def __on_text_changed(self, text: str) -> None:
        """Write a keystroke through to :attr:`value` only once it parses to a valid partial date.

        :param text: the line edit's current text.
        """
        parsed = self.parse(text)
        if parsed is not None:
            self.value = parsed

    def __open_calendar(self) -> None:
        """Open the popup calendar under the line edit; picking a date writes the full date to
        :attr:`value`.

        Seeded from the line edit's own current text when it already names a full date (parsed the
        same way typed entry is, so ``"Jan 1, 2026"`` seeds it too, not just the canonical form);
        today's date otherwise.
        """
        calendar = self.__ensure_calendar()
        seeded = self.__full_qdate(self.__line_edit.text())
        calendar.setSelectedDate(seeded if seeded is not None else QDate.currentDate())
        calendar.move(self.__line_edit.mapToGlobal(QPoint(0, self.__line_edit.height())))
        calendar.show()

    def __ensure_calendar(self) -> QCalendarWidget:
        """Build the popup calendar once and reuse it after -- a fresh, throwaway-per-click
        ``QCalendarWidget`` with ``WA_DeleteOnClose`` crashed under pytest-qt's post-test event
        flush (its deferred deletion landed badly); a single instance, owned for as long as this
        widget is, sidesteps that lifecycle entirely.

        :returns: the (possibly newly built) popup calendar.
        """
        if self.__calendar is None:
            calendar = QCalendarWidget(self)
            calendar.setWindowFlag(Qt.WindowType.Popup)
            calendar.clicked.connect(self.__pick)
            self.__calendar = calendar
        return self.__calendar

    def __pick(self, qdate: QDate) -> None:
        """Write the picked date to :attr:`value` and close the popup.

        :param qdate: the date picked in the popup calendar.
        """
        self.value = f"{qdate.year():04d}-{qdate.month():02d}-{qdate.day():02d}"
        self.__ensure_calendar().close()

    @classmethod
    def __full_qdate(cls, text: str) -> QDate | None:
        """Parse ``text`` into a ``QDate``, only when it names a full (``YYYY-MM-DD``-precision) date.

        :param text: the text to parse.
        :returns: the equivalent ``QDate``, or ``None`` if ``text`` doesn't parse to full precision.
        """
        parsed = cls.parse(text)
        if parsed is None or len(parsed) != len("YYYY-MM-DD"):
            return None
        year, month, day = (int(part) for part in parsed.split("-"))
        return QDate(year, month, day)

    def __render(self, value: str) -> None:
        """Update the line edit from a :attr:`value` change without re-emitting ``textChanged`` (echo guard).

        Compares the line edit's own *parsed* text against the incoming value (mirrors
        :class:`~rehuco_agent.fields.text_list_field.TextListField`'s guard) -- a keystroke that
        round-trips through :attr:`value` does not bounce back and reset the cursor, and typed text
        that hasn't (yet) reached a parseable state is left alone rather than overwritten mid-edit.

        :param value: the new value.
        """
        if self.parse(self.__line_edit.text()) != value:
            with QSignalBlocker(self.__line_edit):
                self.__line_edit.setText(value)
