"""Tests for DurationEdit: human-text parsing and the live line-edit + spin-box sync."""

from collections.abc import Callable

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QLineEdit, QSpinBox
from pytest import mark, param
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.widgets.duration_edit import DurationEdit


def internal_line_edit(edit: DurationEdit) -> QLineEdit:
    """Return the widget's private internal line edit -- ``DurationEdit`` exposes no accessor of its own.

    :param edit: the widget to inspect.
    :returns: the internal ``QLineEdit``.
    """
    return edit._DurationEdit__line_edit  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def internal_spin_box(edit: DurationEdit) -> QSpinBox:
    """Return the widget's private internal spin box -- ``DurationEdit`` exposes no accessor of its own.

    :param edit: the widget to inspect.
    :returns: the internal ``QSpinBox``.
    """
    return edit._DurationEdit__spin_box  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def spin_box_clear_action(edit: DurationEdit) -> QAction:
    """Return the spin box's clear trailing action.

    :param edit: the widget to inspect.
    :returns: the ``QAction`` that resets the spin box to zero.
    """
    spin_box = internal_spin_box(edit)
    line_edit = spin_box.lineEdit()
    assert line_edit is not None
    return line_edit.actions()[0]


# region parse() tests
@mark.parametrize(
    ("text", "expected"),
    [
        param("1h", 3600, id="hour-abbreviation"),
        param("1hour", 3600, id="hour-singular-word"),
        param("1hours", 3600, id="hour-plural-word"),
        param("2hours 30mins", 9000, id="hours-and-minutes-words"),
        param("1h 30m", 5400, id="hour-and-minute-abbreviations"),
        param("1h 30m 15s", 5415, id="hour-minute-second-abbreviations"),
        param("30m 45s", 1845, id="minute-and-second-abbreviations"),
        param("1h30m", 5400, id="no-space-between-tokens"),
        param("123456", 123456, id="bare-integer-is-seconds"),
        param("0", 0, id="bare-zero"),
        param("0h", 0, id="zero-hours"),
        param("1H", 3600, id="uppercase-abbreviation"),
        param("1HOUR", 3600, id="uppercase-word"),
        param("2 hours 30 mins", 9000, id="spaced-out-words"),
        param("", None, id="empty-is-unparseable"),
        param("   ", None, id="whitespace-only-is-unparseable"),
        param("not a duration", None, id="garbage-text"),
        param("1h 30", None, id="trailing-number-with-no-unit"),
        param("-5h", None, id="negative-is-rejected"),
        param("1h x", None, id="trailing-garbage-after-a-valid-token"),
    ],
)
def test_parse(text: str, expected: int | None) -> None:
    """``parse`` recognizes unit-word runs, a unitless bare integer, and rejects everything else.

    **Test steps:**

    * parse each ``text``
    * verify it matches ``expected`` (the total seconds, or ``None`` when unparseable)
    """
    assert DurationEdit.parse(text) == expected


# endregion


# region format() tests
@mark.parametrize(
    ("seconds", "expected"),
    [
        param(0, "", id="zero-is-empty-not-0s"),
        param(30, "30s", id="seconds-only-under-a-minute"),
        param(45 * 60 + 30, "45m 30s", id="minutes-and-seconds-under-an-hour"),
        param(45 * 60, "45m", id="minutes-only-when-seconds-are-zero"),
        param(2 * 3600 + 15 * 60, "2h 15m", id="hours-and-minutes-drop-trailing-seconds"),
        param(2 * 3600, "2h", id="hours-only-when-minutes-are-zero"),
        param(2 * 3600 + 5, "2h", id="leftover-seconds-are-noise-once-hours-are-present"),
        param(123 * 3600 + 45 * 60, "123h 45m", id="large-values-never-roll-into-days"),
    ],
)
def test_format(seconds: int, expected: str) -> None:
    """``format`` renders whole seconds per [[field-schema#duration-format]].

    **Test steps:**

    * format each ``seconds`` value
    * verify it matches ``expected``
    """
    assert DurationEdit.format(seconds) == expected


# endregion


# region widget tests
def test_duration_edit_starts_at_zero_by_default(qtbot: QtBot) -> None:
    """A freshly built ``DurationEdit`` shows an empty line edit and a zero spin box.

    **Test steps:**

    * build a default ``DurationEdit``
    * verify its value is zero and both internal widgets match
    """
    edit = DurationEdit()
    qtbot.addWidget(edit)

    assert edit.value == 0
    assert internal_line_edit(edit).text() == ""
    assert internal_spin_box(edit).value() == 0


def test_duration_edit_spin_box_has_a_non_negative_range(qtbot: QtBot) -> None:
    """The spin box's range spans zero to :attr:`DurationEdit.MAXIMUM` -- duration is never negative.

    **Test steps:**

    * build the widget
    * verify the internal spin box's actual range matches the class constants
    """
    edit = DurationEdit()
    qtbot.addWidget(edit)

    spin_box = internal_spin_box(edit)
    assert spin_box.minimum() == DurationEdit.MINIMUM
    assert spin_box.maximum() == DurationEdit.MAXIMUM


def test_duration_edit_line_edit_accepts_drops(qtbot: QtBot) -> None:
    """The line edit accepts dropped text, same as any typed text -- ``QLineEdit``'s own default.

    **Test steps:**

    * build the widget
    * verify the internal line edit's ``acceptDrops`` is on
    """
    edit = DurationEdit()
    qtbot.addWidget(edit)

    assert internal_line_edit(edit).acceptDrops() is True


def test_duration_edit_spin_box_shows_the_bare_number_at_zero(qtbot: QtBot) -> None:
    """The spin box shows the plain ``"0"`` at zero -- no special-value hint.

    Shown explicitly -- a native ``QSpinBox``'s displayed text is only populated on first paint,
    not merely by construction, so an unshown widget's ``text()`` reads ``""`` regardless (confirmed
    empirically, #24).

    **Test steps:**

    * build and show the widget
    * verify the internal spin box's displayed text at the default zero value
    """
    edit = DurationEdit()
    qtbot.addWidget(edit)
    edit.show()

    assert internal_spin_box(edit).text() == "0"


def test_duration_edit_spin_box_shows_the_bare_number_once_nonzero(qtbot: QtBot) -> None:
    """The spin box shows the plain number once ``value`` is nonzero.

    **Test steps:**

    * build the widget and set a nonzero value
    * verify the internal spin box's displayed text is the bare number
    """
    edit = DurationEdit()
    qtbot.addWidget(edit)

    edit.value = 3661

    assert internal_spin_box(edit).text() == "3661"


def test_duration_edit_clearing_the_line_edit_resets_value_and_spin_box(qtbot: QtBot) -> None:
    """Emptying the line edit (e.g. via its clear action) resets ``value`` and the spin box to zero.

    A blank line edit is an explicit reset, not "incomplete typing" -- unlike genuinely unparseable
    non-empty text, which leaves ``value`` untouched (confirmed empirically, #24: without this, the
    spin box kept its old number after clearing the line edit).

    **Test steps:**

    * build the widget with a nonzero value
    * clear the internal line edit's text
    * verify ``value`` and the spin box both reset to zero
    """
    edit = DurationEdit()
    qtbot.addWidget(edit)
    edit.value = 7

    internal_line_edit(edit).clear()

    assert edit.value == 0
    assert internal_spin_box(edit).value() == 0


def test_duration_edit_typing_a_valid_duration_updates_value_and_spin_box(qtbot: QtBot) -> None:
    """Typing a valid human duration updates ``value`` and the spin box.

    **Test steps:**

    * build the widget
    * type a duration into the internal line edit
    * verify ``value`` and the spin box both follow
    """
    edit = DurationEdit()
    qtbot.addWidget(edit)

    internal_line_edit(edit).setText("1h 30m")

    assert edit.value == 5400
    assert internal_spin_box(edit).value() == 5400


def test_duration_edit_typing_unparseable_text_does_not_change_value(qtbot: QtBot) -> None:
    """Text that doesn't parse (yet, or ever) leaves ``value`` untouched.

    **Test steps:**

    * build the widget with a valid starting value
    * type incomplete text into the line edit
    * verify ``value`` is unchanged
    """
    edit = DurationEdit()
    qtbot.addWidget(edit)
    edit.value = 3600

    internal_line_edit(edit).setText("1h 30")

    assert edit.value == 3600


@mark.parametrize(
    ("text", "expected_warning"),
    [
        param("", False, id="blank-is-not-a-warning"),
        param("1h 30m", False, id="valid-text-is-not-a-warning"),
        param("1h 30", True, id="unparseable-non-blank-text-is-a-warning"),
    ],
)
def test_duration_edit_line_edit_warns_only_for_non_blank_unparseable_text(
    qtbot: QtBot, text: str, expected_warning: bool
) -> None:
    """The line edit's ``warning`` dynamic property (driving :attr:`DurationEdit.WARNING_STYLESHEET`)
    is set exactly when the typed text is non-blank and unparseable.

    **Test steps:**

    * build the widget, seed the line edit with placeholder text, then set it to ``text`` (so a
      blank ``text`` case genuinely fires ``textChanged``, rather than a no-op ``setText("")`` on an
      already-empty line edit)
    * verify the internal line edit's ``warning`` property matches ``expected_warning``
    """
    # pylint: disable=duplicate-code
    edit = DurationEdit()
    qtbot.addWidget(edit)
    line_edit = internal_line_edit(edit)
    line_edit.setText("seed")

    line_edit.setText(text)

    assert line_edit.property("warning") is expected_warning


def test_duration_edit_line_edit_warning_clears_once_text_becomes_valid(qtbot: QtBot) -> None:
    """The warning property clears once unparseable text is completed into valid text.

    **Test steps:**

    * type unparseable text, then complete it into a valid duration
    * verify the ``warning`` property clears
    """
    # pylint: enable=duplicate-code
    edit = DurationEdit()
    qtbot.addWidget(edit)
    line_edit = internal_line_edit(edit)
    line_edit.setText("1h 30")
    assert line_edit.property("warning") is True

    line_edit.setText("1h 30m")

    assert line_edit.property("warning") is False


@mark.parametrize(
    "set_value",
    [
        param(lambda edit: internal_spin_box(edit).setValue(5400), id="via-spin-box"),
        param(lambda edit: setattr(edit, "value", 5400), id="via-value-property"),
        param(lambda edit: edit.set_value(5400), id="via-set-value-slot"),  # type: ignore[attr-defined]
    ],
)
def test_duration_edit_setting_the_value_any_way_syncs_both_widgets(
    qtbot: QtBot, set_value: Callable[[DurationEdit], None]
) -> None:
    """However ``value`` gets set -- the spin box, the property, or the synthesized slot -- both
    internal widgets end up in sync with it.

    **Test steps:**

    * build the widget
    * set the value via ``set_value``
    * verify ``value``, the line edit (formatted), and the spin box all agree
    """
    edit = DurationEdit()
    qtbot.addWidget(edit)

    set_value(edit)

    assert edit.value == 5400
    assert internal_line_edit(edit).text() == "1h 30m"
    assert internal_spin_box(edit).value() == 5400


def test_duration_edit_line_edit_keeps_typed_text_once_it_matches_value(qtbot: QtBot) -> None:
    """Typed text that already parses to the current value is left displayed as typed.

    The echo guard compares *parsed* text, not raw text -- so e.g. ``"1h30m"`` (no space) isn't
    silently reformatted to ``"1h 30m"`` the moment it round-trips through ``value``.

    **Test steps:**

    * build the widget
    * type a duration with no space between tokens
    * verify it's still displayed exactly as typed
    """
    edit = DurationEdit()
    qtbot.addWidget(edit)

    internal_line_edit(edit).setText("1h30m")

    assert edit.value == 5400
    assert internal_line_edit(edit).text() == "1h30m"


# endregion


# region spin box clear action tests
@mark.parametrize(
    ("value", "expected_visible"),
    [
        param(0, False, id="hidden-at-zero"),
        param(60, True, id="visible-once-nonzero"),
    ],
)
def test_duration_edit_spin_box_clear_action_visibility_matches_value(
    qtbot: QtBot, value: int, expected_visible: bool
) -> None:
    """The spin box's clear action is visible exactly when ``value`` is nonzero.

    **Test steps:**

    * build the widget and set ``value``
    * verify the spin box's clear action's visibility matches ``expected_visible``
    """
    edit = DurationEdit()
    qtbot.addWidget(edit)

    edit.value = value

    assert spin_box_clear_action(edit).isVisible() is expected_visible


def test_duration_edit_spin_box_clear_action_resets_the_value_not_just_the_text(qtbot: QtBot) -> None:
    """Triggering the spin box's clear action resets ``value`` (and the spin box's own ``value()``)
    to zero -- not just the displayed text, which would otherwise snap back on a focus change
    (confirmed empirically: a plain text-clear leaves ``QSpinBox.value()`` untouched, and
    ``interpretText()`` -- what a focus-out triggers -- restores the old number).

    **Test steps:**

    * build the widget with a nonzero value
    * trigger the spin box's clear action
    * verify ``value`` and the spin box's own ``value()`` both reflect zero, and simulating a
      focus-out doesn't resurrect the old number
    """
    edit = DurationEdit()
    qtbot.addWidget(edit)
    edit.value = 3600
    spin_box = internal_spin_box(edit)

    spin_box_clear_action(edit).trigger()

    assert edit.value == 0
    assert spin_box.value() == 0

    spin_box.interpretText()
    assert spin_box.value() == 0


def test_duration_edit_spin_box_clear_action_hides_again_after_clearing(qtbot: QtBot) -> None:
    """Triggering the spin box's clear action hides it again, matching the now-zero value.

    **Test steps:**

    * build the widget with a nonzero value
    * trigger the spin box's clear action
    * verify the clear action is hidden again
    """
    edit = DurationEdit()
    qtbot.addWidget(edit)
    edit.value = 3600

    spin_box_clear_action(edit).trigger()

    assert spin_box_clear_action(edit).isVisible() is False


# endregion
