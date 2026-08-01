"""Tests for FileSizeEdit: the stored spin box between its two readouts, and the explicit apply and
busy state around the measurement.
"""

# the measure/apply/busy contract is the one every measure row's tests pin, because all three rows are
# one `MeasuredValueEdit`; each suite pins it through its own row, which is where a user meets it
# pylint: disable=duplicate-code

from borco_pyside.widgets import UnboundedSpinBox
from pytest import mark, param
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.widgets.file_size_edit import COMPUTED_TOOLTIP, STORED_TOOLTIP, FileSizeEdit
from rehuco_agent.fields.widgets.value_readout import ValueReadout

from .measure_row_internals import (
    internal_apply_button,
    internal_compute_button,
    internal_computed_label,
    internal_editor,
    internal_stored_label,
)


def internal_spin_box(edit: FileSizeEdit) -> UnboundedSpinBox:
    """Return the row's stored-size spin box, named for what this row puts there.

    :param edit: the widget to inspect.
    :returns: the internal ``UnboundedSpinBox``.
    """
    return internal_editor(edit)


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
def test_edit_starts_unmeasured_with_nothing_computed(qtbot: QtBot) -> None:
    """A fresh row holds no stored size, shows no measured one, and offers nothing to apply.

    **Test steps:**

    * build the widget
    * verify both values are unset, both readouts are empty, apply is disabled and compute is offered
    """
    edit = FileSizeEdit()
    qtbot.addWidget(edit)

    assert edit.value is None
    assert edit.computed is None
    assert edit.busy is False
    assert internal_stored_label(edit).text() == ""
    assert internal_computed_label(edit).text() == ""
    assert not internal_apply_button(edit).isEnabled()
    assert internal_compute_button(edit).isEnabled()


def test_edit_spin_box_has_no_upper_bound(qtbot: QtBot) -> None:
    """The internal spin box has a zero minimum (sizes are never negative) and no maximum -- a
    multi-terabyte resource overflows the C++ int32 ceiling by orders of magnitude (#40).

    **Test steps:**

    * build the widget
    * verify the internal spin box's ``minimum()``/``maximum()``
    """
    edit = FileSizeEdit()
    qtbot.addWidget(edit)

    spin_box = internal_spin_box(edit)
    assert spin_box.minimum() == 0
    assert spin_box.maximum() is None


@mark.parametrize(
    "readout",
    [
        param(internal_stored_label, id="human-readable-readout"),
        param(internal_computed_label, id="computed-readout"),
    ],
)
def test_both_readouts_are_the_shared_read_only_readout(qtbot: QtBot, readout: object) -> None:
    """Both readouts are the row-agnostic `ValueReadout` -- framed, selectable, read-only -- rather than
    something this row styles for itself, so the count row beside it cannot end up looking different.
    What that widget guarantees is pinned by its own tests.

    **Test steps:**

    * build the widget
    * verify the readout is a ``ValueReadout`` and names what it shows
    """
    edit = FileSizeEdit()
    qtbot.addWidget(edit)

    label = readout(edit)  # type: ignore[operator]  # a parametrized accessor from this module

    assert isinstance(label, ValueReadout)
    assert label.toolTip() in (STORED_TOOLTIP, COMPUTED_TOOLTIP)


def test_editing_the_spin_box_writes_the_value_through(qtbot: QtBot) -> None:
    """The spin box is the field's value: typing in it moves ``value``.

    **Test steps:**

    * build the widget and set the spin box's value
    * verify ``value`` followed
    """
    edit = FileSizeEdit()
    qtbot.addWidget(edit)

    internal_spin_box(edit).setValue(5368709120)

    assert edit.value == 5368709120


def test_setting_the_value_echoes_into_the_spin_box_and_its_human_reading(qtbot: QtBot) -> None:
    """A value set from outside (the model, or apply) shows up in the spin box and in the readout
    beside it, with no feedback loop.

    **Test steps:**

    * build the widget and set ``value`` directly, as a bound model change would
    * verify the spin box holds the bytes, the readout shows them formatted, and the value survived
    """
    edit = FileSizeEdit()
    qtbot.addWidget(edit)

    edit.set_value(5368709120)  # type: ignore[attr-defined]  # the slot SimpleProperty synthesizes

    assert internal_spin_box(edit).value == 5368709120
    assert internal_stored_label(edit).text() == "5.0G"
    assert edit.value == 5368709120


def test_a_stored_zero_reads_honestly_where_unmeasured_reads_empty(qtbot: QtBot) -> None:
    """The human readout keeps the absent/zero distinction the value itself carries
    ([[field-schema#deferred-items]]).

    **Test steps:**

    * set a genuine ``0`` and verify the readout shows ``"0B"``
    * set ``None`` and verify it goes blank
    """
    edit = FileSizeEdit()
    qtbot.addWidget(edit)

    edit.set_value(0)  # type: ignore[attr-defined]
    assert internal_stored_label(edit).text() == "0B"

    edit.set_value(None)  # type: ignore[attr-defined]
    assert internal_stored_label(edit).text() == ""


def test_a_value_beyond_int32_is_held_exactly(qtbot: QtBot) -> None:
    """A size far past the C++ int32 ceiling round-trips exactly through the spin box (the point of #40).

    **Test steps:**

    * set a petabyte-scale value
    * verify the value and the spin box hold it exactly, and the readout formats it
    """
    edit = FileSizeEdit()
    qtbot.addWidget(edit)

    edit.set_value(2**50)  # type: ignore[attr-defined]

    assert edit.value == 2**50
    assert internal_spin_box(edit).value == 2**50
    assert internal_stored_label(edit).text() == "1.0P"


def test_compute_asks_the_owner_rather_than_measuring(qtbot: QtBot) -> None:
    """Pressing ``Compute`` only emits -- the widget knows nothing about files, paths, or settings.

    **Test steps:**

    * build the widget and press ``Compute``
    * verify ``compute_requested`` fired and neither value changed
    """
    edit = FileSizeEdit()
    qtbot.addWidget(edit)

    with qtbot.waitSignal(edit.compute_requested):
        internal_compute_button(edit).click()

    assert edit.computed is None
    assert edit.value is None


def test_compute_enters_the_busy_state_and_disables_both_actions(qtbot: QtBot) -> None:
    """A scan in flight disables the buttons: a multi-gigabyte tree takes seconds, and neither a second
    scan nor an apply of a half-finished answer may be pressed meanwhile (#223).

    **Test steps:**

    * build the widget over a stored size with a stale measurement already showing, so apply is offered
    * press ``Compute``
    * verify the widget is busy and both buttons are disabled
    """
    edit = FileSizeEdit()
    qtbot.addWidget(edit)
    edit.set_value(1024)  # type: ignore[attr-defined]
    edit.computed = 2048
    assert internal_apply_button(edit).isEnabled()

    internal_compute_button(edit).click()

    assert edit.busy is True
    assert not internal_compute_button(edit).isEnabled()
    assert not internal_apply_button(edit).isEnabled()


def test_showing_a_measurement_leaves_the_busy_state(qtbot: QtBot) -> None:
    """The owner's answer is what ends the scan: the buttons come back and the result is on screen.

    **Test steps:**

    * press ``Compute``, then hand the widget a result
    * verify it is no longer busy, the readout shows the result, and both buttons are offered again
    """
    edit = FileSizeEdit()
    qtbot.addWidget(edit)
    internal_compute_button(edit).click()

    edit.show_measurement(2048)

    assert edit.busy is False
    assert edit.computed == 2048
    assert internal_computed_label(edit).text() == "2048"
    assert internal_compute_button(edit).isEnabled()
    assert internal_apply_button(edit).isEnabled()


def test_a_failed_measurement_still_leaves_the_busy_state(qtbot: QtBot) -> None:
    """A scan that measured nothing still hands back an answer, so the row never strands itself busy
    with a permanently dead ``Compute``.

    **Test steps:**

    * press ``Compute``, then hand the widget ``None``
    * verify it is no longer busy and compute is offered again
    """
    edit = FileSizeEdit()
    qtbot.addWidget(edit)
    internal_compute_button(edit).click()

    edit.show_measurement(None)

    assert edit.busy is False
    assert internal_compute_button(edit).isEnabled()


def test_a_computed_size_is_shown_exactly_without_touching_the_value(qtbot: QtBot) -> None:
    """A measurement fills the readout beside the stored size and leaves the stored size alone -- the
    disagreement is information, not something to silently resolve (#223).

    It is shown as an **exact byte count**, so it can be compared against the spin box digit for digit
    rather than through a rounded ``1.4G`` two different sizes would share.

    **Test steps:**

    * build the widget over a stored ``1024`` and hand it a computed ``5368709120``
    * verify the readout shows the exact bytes while the value and spin box still read ``1024``
    """
    edit = FileSizeEdit()
    qtbot.addWidget(edit)
    edit.set_value(1024)  # type: ignore[attr-defined]

    edit.computed = 5368709120

    assert internal_computed_label(edit).text() == "5368709120"
    assert edit.value == 1024
    assert internal_spin_box(edit).value == 1024


def test_a_computed_zero_shows_as_zero_not_as_nothing(qtbot: QtBot) -> None:
    """A measured ``0`` renders honestly, distinct from the empty "never measured" readout
    ([[field-schema#deferred-items]]).

    **Test steps:**

    * hand the widget a computed ``0``
    * verify the readout reads ``"0"``
    """
    edit = FileSizeEdit()
    qtbot.addWidget(edit)

    edit.computed = 0

    assert internal_computed_label(edit).text() == "0"


def test_apply_is_offered_only_while_the_two_sizes_differ(qtbot: QtBot) -> None:
    """``Apply`` enables exactly when there is a measurement that disagrees with the stored size.

    **Test steps:**

    * verify apply stays disabled while a measurement matches the stored size
    * verify it enables once they differ, and disables again once the stored size catches up
    """
    edit = FileSizeEdit()
    qtbot.addWidget(edit)
    edit.set_value(1024)  # type: ignore[attr-defined]

    edit.computed = 1024
    assert not internal_apply_button(edit).isEnabled()

    edit.computed = 2048
    assert internal_apply_button(edit).isEnabled()

    edit.set_value(2048)  # type: ignore[attr-defined]
    assert not internal_apply_button(edit).isEnabled()


def test_apply_stores_the_computed_size(qtbot: QtBot) -> None:
    """``Apply`` is the one action here that changes the value -- and it reports it as a value change.

    **Test steps:**

    * build the widget over a stored ``1024`` with a computed ``2048``
    * press apply and verify ``value_changed`` fired with the measured size
    * verify the spin box and the human readout followed, and apply went back to disabled
    """
    edit = FileSizeEdit()
    qtbot.addWidget(edit)
    edit.set_value(1024)  # type: ignore[attr-defined]
    edit.computed = 2048

    with qtbot.waitSignal(edit.value_changed) as blocker:  # type: ignore[attr-defined]
        internal_apply_button(edit).click()

    assert blocker.args == [2048]
    assert edit.value == 2048
    assert internal_spin_box(edit).value == 2048
    assert internal_stored_label(edit).text() == "2.0K"
    assert not internal_apply_button(edit).isEnabled()


def test_an_unmeasurable_size_shows_nothing_and_applies_nothing(qtbot: QtBot) -> None:
    """A measurement that could not run (``None`` -- e.g. a document with no path yet) leaves the
    readout empty and apply disabled, rather than offering to store "no size".

    **Test steps:**

    * build the widget over a stored ``1024`` and hand it a computed ``None``
    * verify the readout is empty and apply is disabled
    """
    edit = FileSizeEdit()
    qtbot.addWidget(edit)
    edit.set_value(1024)  # type: ignore[attr-defined]

    edit.computed = None

    assert internal_computed_label(edit).text() == ""
    assert not internal_apply_button(edit).isEnabled()


# endregion
