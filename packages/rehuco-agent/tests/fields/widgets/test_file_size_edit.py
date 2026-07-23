"""Tests for FileSizeEdit: GNU-style size text parsing and the live line-edit + spin-box sync."""

from collections.abc import Callable

from borco_pyside.widgets import UnboundedSpinBox
from PySide6.QtWidgets import QLineEdit
from pytest import mark, param
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.widgets.file_size_edit import FileSizeEdit


def internal_line_edit(edit: FileSizeEdit) -> QLineEdit:
    """Return the widget's private internal line edit -- ``FileSizeEdit`` exposes no accessor of its own.

    :param edit: the widget to inspect.
    :returns: the internal ``QLineEdit``.
    """
    return edit._FileSizeEdit__line_edit  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def internal_spin_box(edit: FileSizeEdit) -> UnboundedSpinBox:
    """Return the widget's private internal spin box -- ``FileSizeEdit`` exposes no accessor of its own.

    :param edit: the widget to inspect.
    :returns: the internal ``UnboundedSpinBox``.
    """
    return edit._FileSizeEdit__spin_box  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


# region parse() tests
@mark.parametrize(
    ("text", "expected"),
    [
        param("42", 42, id="bare-number-is-bytes"),
        param("0B", 0, id="zero-bytes"),
        param("1B", 1, id="one-byte"),
        param("300B", 300, id="sub-kilo-with-byte-suffix"),
        param("1K", 1024, id="one-kilo"),
        param("1.4G", 1503238554, id="fractional-giga"),
        param("5.0G", 5368709120, id="five-giga"),
        param("1P", 2**50, id="one-peta"),
        param("1k", 1024, id="lowercase-unit"),
        param("  1G  ", 2**30, id="surrounding-whitespace-is-stripped"),
        param("", None, id="empty-is-unparseable"),
        param("   ", None, id="whitespace-only-is-unparseable"),
        param("not a size", None, id="garbage-text"),
        param("1 G", 2**30, id="space-between-number-and-unit-is-tolerated"),
        param("-5G", None, id="negative-is-rejected"),
        param("1X", None, id="unrecognized-unit-letter"),
    ],
)
def test_parse(text: str, expected: int | None) -> None:
    """``parse`` recognizes GNU-style ``<number><unit>`` text, a unitless bare number, and rejects
    everything else.

    **Test steps:**

    * parse each ``text``
    * verify it matches ``expected`` (the total bytes, or ``None`` when unparseable)
    """
    assert FileSizeEdit.parse(text) == expected


# endregion


# region format() tests
@mark.parametrize(
    ("size", "expected"),
    [
        param(None, "", id="none-is-empty-unmeasured"),
        param(0, "0B", id="zero-renders-honestly-not-empty"),
        param(1, "1B", id="one-byte"),
        param(300, "300B", id="sub-kilo"),
        param(1024, "1.0K", id="exactly-one-kilo"),
        param(1500000000, "1.4G", id="giga-rounded"),
        param(5368709120, "5.0G", id="five-giga-exact"),
        param(2**50, "1.0P", id="one-peta"),
    ],
)
def test_format(size: int | None, expected: str) -> None:
    """``format`` renders whole bytes GNU ``ls -sh`` style (``humanize.naturalsize(size, gnu=True)``).

    **Test steps:**

    * format each ``size`` value
    * verify it matches ``expected``
    """
    assert FileSizeEdit.format(size) == expected


# endregion


# region widget tests
def test_file_size_edit_starts_unmeasured_by_default(qtbot: QtBot) -> None:
    """A freshly built ``FileSizeEdit`` starts unmeasured (``None``): an empty line edit and a zero
    spin box, the spin box's own empty-state stand-in ([[field-schema#deferred-items]]).

    **Test steps:**

    * build a default ``FileSizeEdit``
    * verify its value is ``None`` and both internal widgets match
    """
    edit = FileSizeEdit()
    qtbot.addWidget(edit)

    assert edit.value is None
    assert internal_line_edit(edit).text() == ""
    assert internal_spin_box(edit).value == 0


def test_file_size_edit_spin_box_has_no_upper_bound(qtbot: QtBot) -> None:
    """The internal spin box has a zero minimum (sizes are never negative) and no maximum.

    **Test steps:**

    * build the widget
    * verify the internal spin box's ``minimum()``/``maximum()``
    """
    edit = FileSizeEdit()
    qtbot.addWidget(edit)

    spin_box = internal_spin_box(edit)
    assert spin_box.minimum() == 0
    assert spin_box.maximum() is None


def test_file_size_edit_typing_a_valid_size_updates_value_and_spin_box(qtbot: QtBot) -> None:
    """Typing a valid GNU-style size updates ``value`` and the spin box.

    **Test steps:**

    * build the widget
    * type a size into the internal line edit
    * verify ``value`` and the spin box both follow
    """
    edit = FileSizeEdit()
    qtbot.addWidget(edit)

    internal_line_edit(edit).setText("5.0G")

    assert edit.value == 5368709120
    assert internal_spin_box(edit).value == 5368709120


def test_file_size_edit_typing_a_valid_size_updates_the_spin_boxs_displayed_text(qtbot: QtBot) -> None:
    """Typing a valid size updates the spin box's own *displayed* text, not just its ``value``
    attribute -- distinct from the attribute, since ``UnboundedSpinBox`` syncs its internal line edit
    by listening to its own ``value_changed``, which a naive blanket signal-blocker around the
    programmatic sync would also silence (confirmed empirically: ``value`` updated but the displayed
    text stayed stale).

    **Test steps:**

    * build the widget
    * type a size into the internal line edit
    * verify the spin box's own internal line edit shows the new number
    """
    edit = FileSizeEdit()
    qtbot.addWidget(edit)

    internal_line_edit(edit).setText("5.0G")

    assert internal_spin_box(edit).lineEdit().text() == "5368709120"


def test_file_size_edit_typing_a_value_beyond_int32_updates_value_exactly(qtbot: QtBot) -> None:
    """Typing a size far past the C++ int32 ceiling updates ``value`` exactly (the point of #40).

    **Test steps:**

    * build the widget
    * type a size beyond int32 into the internal line edit
    * verify ``value`` holds it exactly
    """
    edit = FileSizeEdit()
    qtbot.addWidget(edit)

    internal_line_edit(edit).setText("1P")

    assert edit.value == 2**50


def test_file_size_edit_typing_a_bare_zero_writes_a_genuine_zero_not_none(qtbot: QtBot) -> None:
    """Typing ``"0"`` writes a genuine ``0``, distinct from clearing the line edit (which writes
    ``None``) -- both are non-blank-vs-blank on the same text-changed path
    ([[field-schema#deferred-items]]).

    **Test steps:**

    * build the widget starting unmeasured
    * type ``"0"`` into the line edit
    * verify ``value`` is ``0``, not ``None``
    """
    edit = FileSizeEdit()
    qtbot.addWidget(edit)

    internal_line_edit(edit).setText("0")

    assert edit.value == 0


def test_file_size_edit_typing_unparseable_text_does_not_change_value(qtbot: QtBot) -> None:
    """Text that doesn't parse (yet, or ever) leaves ``value`` untouched.

    **Test steps:**

    * build the widget with a valid starting value
    * type garbage text into the line edit
    * verify ``value`` is unchanged
    """
    edit = FileSizeEdit()
    qtbot.addWidget(edit)
    edit.value = 1024

    internal_line_edit(edit).setText("1X")

    assert edit.value == 1024


@mark.parametrize(
    ("text", "expected_warning"),
    [
        param("", False, id="blank-is-not-a-warning"),
        param("5G", False, id="valid-text-is-not-a-warning"),
        param("1X", True, id="unparseable-non-blank-text-is-a-warning"),
    ],
)
def test_file_size_edit_line_edit_warns_only_for_non_blank_unparseable_text(
    qtbot: QtBot, text: str, expected_warning: bool
) -> None:
    """The line edit's ``warning`` dynamic property (driving :attr:`FileSizeEdit.WARNING_STYLESHEET`)
    is set exactly when the typed text is non-blank and unparseable.

    **Test steps:**

    * build the widget, seed the line edit with placeholder text, then set it to ``text`` (so a
      blank ``text`` case genuinely fires ``textChanged``, rather than a no-op ``setText("")`` on an
      already-empty line edit)
    * verify the internal line edit's ``warning`` property matches ``expected_warning``
    """
    edit = FileSizeEdit()
    qtbot.addWidget(edit)
    line_edit = internal_line_edit(edit)
    line_edit.setText("seed")

    line_edit.setText(text)

    assert line_edit.property("warning") is expected_warning


def test_file_size_edit_line_edit_warning_clears_once_text_becomes_valid(qtbot: QtBot) -> None:
    """The warning property clears once unparseable text is completed into valid text.

    **Test steps:**

    * type unparseable text, then correct it into valid text
    * verify the ``warning`` property clears
    """
    edit = FileSizeEdit()
    qtbot.addWidget(edit)
    line_edit = internal_line_edit(edit)
    line_edit.setText("1X")
    assert line_edit.property("warning") is True

    line_edit.setText("1G")

    assert line_edit.property("warning") is False


def test_file_size_edit_clearing_the_line_edit_resets_value_to_none(qtbot: QtBot) -> None:
    """Emptying the line edit resets ``value`` to ``None`` (unmeasured), with the spin box falling
    back to its empty-state stand-in, zero, and the line edit itself staying blank
    (:meth:`FileSizeEdit.format` renders ``None`` as ``""``, [[field-schema#deferred-items]]).

    A blank line edit is an explicit reset, not "incomplete typing" -- unlike genuinely unparseable
    non-empty text, which leaves ``value`` untouched (mirrors
    :class:`~rehuco_agent.fields.widgets.DurationEdit`'s own guard).

    **Test steps:**

    * build the widget with a nonzero value
    * clear the internal line edit's text
    * verify ``value`` is ``None``, the spin box shows zero, and the line edit stays blank
    """
    edit = FileSizeEdit()
    qtbot.addWidget(edit)
    edit.value = 1024

    internal_line_edit(edit).clear()

    assert edit.value is None
    assert internal_spin_box(edit).value == 0
    assert internal_line_edit(edit).text() == ""


@mark.parametrize(
    "set_value",
    [
        param(lambda edit: internal_spin_box(edit).setValue(5368709120), id="via-spin-box"),
        param(lambda edit: setattr(edit, "value", 5368709120), id="via-value-property"),
        param(lambda edit: edit.set_value(5368709120), id="via-set-value-slot"),  # type: ignore[attr-defined]
    ],
)
def test_file_size_edit_setting_the_value_any_way_syncs_both_widgets(
    qtbot: QtBot, set_value: Callable[[FileSizeEdit], None]
) -> None:
    """However ``value`` gets set -- the spin box, the property, or the synthesized slot -- both
    internal widgets end up in sync with it.

    **Test steps:**

    * build the widget
    * set the value via ``set_value``
    * verify ``value``, the line edit (formatted), and the spin box all agree
    """
    edit = FileSizeEdit()
    qtbot.addWidget(edit)

    set_value(edit)

    assert edit.value == 5368709120
    assert internal_line_edit(edit).text() == "5.0G"
    assert internal_spin_box(edit).value == 5368709120


def test_file_size_edit_line_edit_keeps_typed_text_once_it_matches_value(qtbot: QtBot) -> None:
    """Typed text that already parses to the current value is left displayed as typed.

    The echo guard compares *parsed* text, not raw text -- so e.g. ``"5G"`` isn't silently
    reformatted to ``"5.0G"`` the moment it round-trips through ``value``.

    **Test steps:**

    * build the widget
    * type a size with no decimal point
    * verify it's still displayed exactly as typed
    """
    edit = FileSizeEdit()
    qtbot.addWidget(edit)

    internal_line_edit(edit).setText("5G")

    assert edit.value == 5368709120
    assert internal_line_edit(edit).text() == "5G"


# endregion
