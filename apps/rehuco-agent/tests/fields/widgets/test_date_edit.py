"""Tests for DateEdit: partial-precision date parsing and the free-text + calendar-popup editor."""

from collections.abc import Callable

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QCalendarWidget, QLineEdit
from pytest import mark, param
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.widgets.date_edit import DateEdit


def internal_line_edit(edit: DateEdit) -> QLineEdit:
    """Return the widget's private internal line edit -- ``DateEdit`` exposes no accessor of its own.

    :param edit: the widget to inspect.
    :returns: the internal ``QLineEdit``.
    """
    return edit._DateEdit__line_edit  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


# region parse() tests
@mark.parametrize(
    ("text", "expected"),
    [
        param("", "", id="empty-is-a-valid-unknown-date"),
        param("   ", "", id="whitespace-only-is-a-valid-unknown-date"),
        param("2026", "2026", id="bare-year"),
        param("2026/10", "2026-10", id="year-and-month-with-slash"),
        param("2026/10/20", "2026-10-20", id="full-date-with-slash"),
        param("2026.10", "2026-10", id="year-and-month-with-dot"),
        param("2026.10.20", "2026-10-20", id="full-date-with-dot"),
        param("2026-10-20", "2026-10-20", id="full-date-with-dash-already-canonical"),
        param("2026/13", None, id="invalid-month-is-rejected"),
        param("2026/02/30", None, id="calendar-invalid-day-is-rejected"),
        param("2026/10.20", None, id="mismatched-separators-are-rejected"),
        param("2026 AD", "2026", id="human-year-only-text"),
        param("January 2026", "2026-01", id="human-month-name-then-year"),
        param("2026 Jan", "2026-01", id="human-year-then-month-abbreviation"),
        param("Jan 1, 2026", "2026-01-01", id="human-month-day-year"),
        param("not a date", None, id="unparseable-garbage-is-rejected"),
        param("March", None, id="bare-month-name-with-no-year-is-rejected"),
    ],
)
def test_parse(text: str, expected: str | None) -> None:
    """``parse`` recognizes the numeric and human date shapes, and rejects everything else.

    The dot-separated cases (``2026.10``/``2026.10.20``) specifically exercise the numeric fast
    path, not :mod:`dateutil` -- which silently drops the month from a dot-separated ``YYYY.MM``
    (confirmed empirically, #24).

    **Test steps:**

    * parse each ``text``
    * verify it matches ``expected`` (the canonical string, or ``None`` when unparseable)
    """
    assert DateEdit.parse(text) == expected


# endregion


# region widget tests
def test_date_edit_starts_none_by_default(qtbot: QtBot) -> None:
    """A freshly built ``DateEdit`` starts unreleased/unknown (``None``), with an empty line edit
    ([[field-schema#deferred-items]]).

    **Test steps:**

    * build a default ``DateEdit``
    * verify its value is ``None`` and the internal line edit is empty
    """
    edit = DateEdit()
    qtbot.addWidget(edit)

    assert edit.value is None
    assert internal_line_edit(edit).text() == ""


def test_date_edit_line_edit_writes_through_once_text_parses(qtbot: QtBot) -> None:
    """A keystroke that parses to a valid partial date updates ``value``.

    **Test steps:**

    * build the widget
    * type a full numeric date
    * verify ``value`` holds the canonical form
    """
    edit = DateEdit()
    qtbot.addWidget(edit)

    internal_line_edit(edit).setText("2026/10/20")

    assert edit.value == "2026-10-20"


def test_date_edit_line_edit_does_not_write_through_unparseable_text(qtbot: QtBot) -> None:
    """Text that doesn't parse (yet, or ever) leaves ``value`` untouched.

    **Test steps:**

    * build the widget with a valid starting value
    * type incomplete/garbage text
    * verify ``value`` is unchanged
    """
    edit = DateEdit()
    qtbot.addWidget(edit)
    edit.value = "2025-03"

    internal_line_edit(edit).setText("Ja")

    assert edit.value == "2025-03"


def test_date_edit_clearing_the_line_edit_resets_value_to_none(qtbot: QtBot) -> None:
    """Emptying the line edit writes ``None`` (unreleased/unknown) through, not a stored ``""``
    ([[field-schema#deferred-items]]).

    **Test steps:**

    * build the widget with a valid starting value
    * clear the internal line edit's text
    * verify ``value`` is ``None``
    """
    edit = DateEdit()
    qtbot.addWidget(edit)
    edit.value = "2025-03"

    internal_line_edit(edit).clear()

    assert edit.value is None


@mark.parametrize(
    "set_value",
    [
        param(lambda edit: setattr(edit, "value", "2025-03-08"), id="via-value-property"),
        param(lambda edit: edit.set_value("2025-03-08"), id="via-set-value-slot"),  # type: ignore[attr-defined]
    ],
)
def test_date_edit_setting_the_value_any_way_updates_the_line_edit(
    qtbot: QtBot, set_value: Callable[[DateEdit], None]
) -> None:
    """However ``value`` gets set -- the property or the synthesized slot -- the line edit follows.

    **Test steps:**

    * build the widget
    * set the value via ``set_value``
    * verify the line edit follows
    """
    edit = DateEdit()
    qtbot.addWidget(edit)

    set_value(edit)

    assert internal_line_edit(edit).text() == "2025-03-08"


def test_date_edit_setting_the_value_to_none_blanks_the_line_edit(qtbot: QtBot) -> None:
    """Setting ``value`` to ``None`` directly (as a model reseed would) blanks the line edit.

    **Test steps:**

    * build the widget with a valid starting value
    * set ``value`` to ``None``
    * verify the line edit is blank
    """
    edit = DateEdit()
    qtbot.addWidget(edit)
    edit.value = "2025-03-08"

    edit.value = None

    assert internal_line_edit(edit).text() == ""


def test_date_edit_keeps_typed_human_text_once_it_matches_value(qtbot: QtBot) -> None:
    """Typed human text that already parses to the current value is left displayed as typed.

    The echo guard compares *parsed* text, not raw text -- so a human-readable form ``value``
    itself echoes back does not get silently rewritten to the canonical ISO form.

    **Test steps:**

    * build the widget
    * type a human-readable date
    * verify it's still displayed as typed, with ``value`` holding the canonical form
    """
    edit = DateEdit()
    qtbot.addWidget(edit)

    internal_line_edit(edit).setText("Jan 1, 2026")

    assert edit.value == "2026-01-01"
    assert internal_line_edit(edit).text() == "Jan 1, 2026"


# endregion


# region calendar popup tests
def test_date_edit_calendar_action_writes_the_picked_date_through(qtbot: QtBot) -> None:
    """Triggering the calendar action opens a popup whose click writes the full date to ``value``.

    **Test steps:**

    * build the widget and trigger its trailing calendar action
    * find the popup ``QCalendarWidget``
    * emit its ``clicked`` signal with a date
    * verify ``value`` holds the full canonical date
    """
    edit = DateEdit()
    qtbot.addWidget(edit)
    line_edit = internal_line_edit(edit)

    actions = line_edit.actions()
    assert len(actions) == 1
    actions[0].trigger()

    calendar = edit.findChild(QCalendarWidget)
    assert calendar is not None
    calendar.clicked.emit(QDate(2026, 5, 20))

    assert edit.value == "2026-05-20"


def test_date_edit_calendar_seeds_from_a_full_date_already_typed(qtbot: QtBot) -> None:
    """Opening the calendar over a fully-typed date seeds it to that date, not today.

    **Test steps:**

    * build the widget, type a full date
    * trigger the calendar action
    * verify the popup's selected date matches what was typed
    """
    edit = DateEdit()
    qtbot.addWidget(edit)
    line_edit = internal_line_edit(edit)

    line_edit.setText("2026-05-20")
    line_edit.actions()[0].trigger()

    calendar = edit.findChild(QCalendarWidget)
    assert calendar is not None
    assert calendar.selectedDate() == QDate(2026, 5, 20)


def test_date_edit_calendar_seeds_today_when_no_full_date_is_typed(qtbot: QtBot) -> None:
    """Opening the calendar over a partial (or empty) date seeds it to today.

    **Test steps:**

    * build the widget over an empty value
    * trigger the calendar action
    * verify the popup's selected date is today
    """
    edit = DateEdit()
    qtbot.addWidget(edit)
    line_edit = internal_line_edit(edit)

    line_edit.actions()[0].trigger()

    calendar = edit.findChild(QCalendarWidget)
    assert calendar is not None
    assert calendar.selectedDate() == QDate.currentDate()


def test_date_edit_calendar_is_built_once_and_reused(qtbot: QtBot) -> None:
    """Opening the calendar twice reuses the same instance rather than building a new one each time.

    A fresh, throwaway-per-click ``QCalendarWidget`` crashed under pytest-qt's post-test event
    flush (its ``WA_DeleteOnClose`` deferred deletion landed badly); reuse sidesteps that lifecycle
    entirely -- this locks in the reuse so a regression back to per-click construction is caught.

    **Test steps:**

    * build the widget and trigger the calendar action twice, picking a date each time
    * verify both opens found exactly one popup, and it's the same object both times
    """
    edit = DateEdit()
    qtbot.addWidget(edit)
    line_edit = internal_line_edit(edit)

    line_edit.actions()[0].trigger()
    first = edit.findChild(QCalendarWidget)
    assert first is not None
    first.clicked.emit(QDate(2026, 5, 20))

    line_edit.actions()[0].trigger()
    second = edit.findChild(QCalendarWidget)

    assert second is first


# endregion
