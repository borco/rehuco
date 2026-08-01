"""Tests for MeasuredDurationEdit: the stored `DurationEdit` beside the duration a scan found, and the
explicit apply and busy state around the measurement (#224).
"""

# the measure/apply/busy contract is the one the size and count rows' tests also pin, because all three
# are the same `MeasuredValueEdit`; each suite pins it through its own row, which is where a user meets it
# pylint: disable=duplicate-code

from PySide6.QtWidgets import QToolButton
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.widgets.duration_edit import DurationEdit
from rehuco_agent.fields.widgets.measured_duration_edit import COMPUTED_TOOLTIP, MeasuredDurationEdit
from rehuco_agent.fields.widgets.value_readout import ValueReadout

from .measure_row_internals import (
    internal_apply_button,
    internal_compute_button,
    internal_computed_label,
    internal_editor,
    internal_row_widgets,
    internal_stored_label,
)


def internal_duration_edit(edit: MeasuredDurationEdit) -> DurationEdit:
    """Return the row's stored-duration editor, named for what this row puts there.

    :param edit: the widget to inspect.
    :returns: the internal ``DurationEdit``.
    """
    return internal_editor(edit)


def test_the_row_reads_left_to_right_as_stored_then_measured(qtbot: QtBot) -> None:
    """The row is the ``[duration editor] [apply] [computed] [compute]`` shape #224 asks for -- the human
    reading and the seconds are the `DurationEdit`'s own two halves, so no fourth widget is added for
    them.

    **Test steps:**

    * build the widget
    * verify the laid-out widgets, left to right, and that no separate stored readout was added
    """
    edit = MeasuredDurationEdit()
    qtbot.addWidget(edit)

    assert internal_row_widgets(edit) == [
        internal_duration_edit(edit),
        internal_apply_button(edit),
        internal_computed_label(edit),
        internal_compute_button(edit),
    ]
    assert internal_stored_label(edit) is None


def test_edit_starts_unmeasured_with_nothing_computed(qtbot: QtBot) -> None:
    """A fresh row holds no stored duration, shows no measured one, and offers nothing to apply.

    **Test steps:**

    * build the widget
    * verify both values are unset, the readout is empty, apply is disabled and compute is offered
    """
    edit = MeasuredDurationEdit()
    qtbot.addWidget(edit)

    assert edit.value is None
    assert edit.computed is None
    assert edit.busy is False
    assert internal_computed_label(edit).text() == ""
    assert not internal_apply_button(edit).isEnabled()
    assert internal_compute_button(edit).isEnabled()


def test_the_computed_readout_is_the_shared_read_only_readout(qtbot: QtBot) -> None:
    """The readout is the row-agnostic `ValueReadout` the size and count rows use, so a form showing all
    three cannot end up with one that looks different.

    **Test steps:**

    * build the widget
    * verify the readout is a ``ValueReadout`` naming what it shows
    """
    edit = MeasuredDurationEdit()
    qtbot.addWidget(edit)

    readout = internal_computed_label(edit)

    assert isinstance(readout, ValueReadout)
    assert readout.toolTip() == COMPUTED_TOOLTIP


def test_the_two_buttons_are_told_apart_by_what_they_do(qtbot: QtBot) -> None:
    """Both buttons are icon-only, so what each does is in its tooltip -- named for durations rather
    than borrowed from the shared base's generic wording.

    **Test steps:**

    * build the widget
    * verify each button is a ``QToolButton`` whose tooltip names its own action
    """
    edit = MeasuredDurationEdit()
    qtbot.addWidget(edit)

    apply_button = internal_apply_button(edit)
    compute_button = internal_compute_button(edit)

    assert isinstance(apply_button, QToolButton)
    assert isinstance(compute_button, QToolButton)
    assert apply_button.toolTip() == "Store the computed duration"
    assert compute_button.toolTip() == "Measure how long this resource's videos run"


def test_editing_the_duration_writes_the_value_through(qtbot: QtBot) -> None:
    """The duration editor is the field's value: editing it moves ``value``.

    **Test steps:**

    * build the widget and set the duration editor's value
    * verify ``value`` followed
    """
    edit = MeasuredDurationEdit()
    qtbot.addWidget(edit)

    internal_duration_edit(edit).value = 8100

    assert edit.value == 8100


def test_setting_the_value_echoes_into_the_duration_editor(qtbot: QtBot) -> None:
    """A value set from outside (the model, or apply) shows up in the editor, with no feedback loop.

    **Test steps:**

    * build the widget and set ``value`` directly, as a bound model change would
    * verify the editor holds the seconds and the value survived
    """
    edit = MeasuredDurationEdit()
    qtbot.addWidget(edit)

    edit.set_value(8100)  # type: ignore[attr-defined]  # the slot SimpleProperty synthesizes

    assert internal_duration_edit(edit).value == 8100
    assert edit.value == 8100


def test_clearing_the_value_reaches_the_duration_editor_too(qtbot: QtBot) -> None:
    """``None`` -- unmeasured -- echoes through as well, distinct from a genuine ``0``
    ([[field-schema#deferred-items]]): the editor's own empty state is what shows it.

    **Test steps:**

    * set a duration, then clear it
    * verify the editor is unset too
    """
    edit = MeasuredDurationEdit()
    qtbot.addWidget(edit)
    edit.set_value(8100)  # type: ignore[attr-defined]

    edit.set_value(None)  # type: ignore[attr-defined]

    assert internal_duration_edit(edit).value is None
    assert edit.value is None


def test_compute_asks_the_owner_rather_than_measuring(qtbot: QtBot) -> None:
    """Pressing ``Compute`` only emits -- the widget knows nothing about files, probes, or settings.

    **Test steps:**

    * build the widget and press ``Compute``
    * verify ``compute_requested`` fired and neither value changed
    """
    edit = MeasuredDurationEdit()
    qtbot.addWidget(edit)

    with qtbot.waitSignal(edit.compute_requested):
        internal_compute_button(edit).click()

    assert edit.computed is None
    assert edit.value is None


def test_compute_enters_the_busy_state_and_disables_both_actions(qtbot: QtBot) -> None:
    """A scan in flight disables the buttons: probing hundreds of videos takes seconds, and neither a
    second scan nor an apply of a half-finished answer may be pressed meanwhile (#224).

    **Test steps:**

    * build the widget over a stored duration with a stale measurement showing, so apply is offered
    * press ``Compute``
    * verify the widget is busy and both buttons are disabled
    """
    edit = MeasuredDurationEdit()
    qtbot.addWidget(edit)
    edit.set_value(8100)  # type: ignore[attr-defined]
    edit.computed = 4050
    assert internal_apply_button(edit).isEnabled()

    internal_compute_button(edit).click()

    assert edit.busy is True
    assert not internal_compute_button(edit).isEnabled()
    assert not internal_apply_button(edit).isEnabled()


def test_showing_a_measurement_leaves_the_busy_state(qtbot: QtBot) -> None:
    """The owner's answer is what ends the scan: the buttons come back and the result is on screen.

    **Test steps:**

    * press ``Compute``, then hand the widget a result
    * verify it is no longer busy, the readout shows the seconds, and both buttons are offered again
    """
    edit = MeasuredDurationEdit()
    qtbot.addWidget(edit)
    internal_compute_button(edit).click()

    edit.show_measurement(8100)

    assert edit.busy is False
    assert edit.computed == 8100
    assert internal_computed_label(edit).text() == "8100"
    assert internal_compute_button(edit).isEnabled()
    assert internal_apply_button(edit).isEnabled()


def test_a_failed_measurement_still_leaves_the_busy_state(qtbot: QtBot) -> None:
    """A scan that measured nothing still hands back an answer, so the row never strands itself busy
    with a permanently dead ``Compute``.

    **Test steps:**

    * press ``Compute``, then hand the widget ``None``
    * verify it is no longer busy and compute is offered again
    """
    edit = MeasuredDurationEdit()
    qtbot.addWidget(edit)
    internal_compute_button(edit).click()

    edit.show_measurement(None)

    assert edit.busy is False
    assert internal_compute_button(edit).isEnabled()


def test_a_computed_duration_is_shown_in_exact_seconds(qtbot: QtBot) -> None:
    """The measurement is shown as a **second count**, not as ``2h 15m``: it is compared against the
    seconds spin box beside it digit for digit, and a coarse reading a range of durations would share
    could not settle whether the two agree ([[field-schema#ms-leak-history]]).

    **Test steps:**

    * build the widget over a stored duration and hand it a computed one
    * verify the readout shows the exact seconds while the stored value is untouched
    """
    edit = MeasuredDurationEdit()
    qtbot.addWidget(edit)
    edit.set_value(8100)  # type: ignore[attr-defined]

    edit.computed = 8137

    assert internal_computed_label(edit).text() == "8137"
    assert edit.value == 8100
    assert internal_duration_edit(edit).value == 8100


def test_a_computed_zero_shows_as_zero_not_as_nothing(qtbot: QtBot) -> None:
    """A tutorial holding no video measures a genuine ``0``, which reads differently from never having
    measured ([[field-schema#deferred-items]]).

    **Test steps:**

    * hand the widget a computed ``0``
    * verify the readout reads ``"0"``
    """
    edit = MeasuredDurationEdit()
    qtbot.addWidget(edit)

    edit.computed = 0

    assert internal_computed_label(edit).text() == "0"


def test_apply_is_offered_only_while_the_two_durations_differ(qtbot: QtBot) -> None:
    """``Apply`` enables exactly when there is a measurement that disagrees with the stored duration.

    **Test steps:**

    * verify apply stays disabled while a measurement matches the stored duration
    * verify it enables once they differ, and disables again once the stored duration catches up
    """
    edit = MeasuredDurationEdit()
    qtbot.addWidget(edit)
    edit.set_value(8100)  # type: ignore[attr-defined]

    edit.computed = 8100
    assert not internal_apply_button(edit).isEnabled()

    edit.computed = 4050
    assert internal_apply_button(edit).isEnabled()

    edit.set_value(4050)  # type: ignore[attr-defined]
    assert not internal_apply_button(edit).isEnabled()


def test_apply_stores_the_computed_duration(qtbot: QtBot) -> None:
    """``Apply`` is the one action here that changes the value -- and it reports it as a value change.

    **Test steps:**

    * build the widget over a stored ``8100`` with a computed ``4050``
    * press apply and verify ``value_changed`` fired with the measured seconds
    * verify the editor followed and apply went back to disabled
    """
    edit = MeasuredDurationEdit()
    qtbot.addWidget(edit)
    edit.set_value(8100)  # type: ignore[attr-defined]
    edit.computed = 4050

    with qtbot.waitSignal(edit.value_changed) as blocker:  # type: ignore[attr-defined]
        internal_apply_button(edit).click()

    assert blocker.args == [4050]
    assert edit.value == 4050
    assert internal_duration_edit(edit).value == 4050
    assert not internal_apply_button(edit).isEnabled()


def test_an_unmeasurable_duration_shows_nothing_and_applies_nothing(qtbot: QtBot) -> None:
    """A measurement that could not run (``None`` -- a document with no path yet, or a probe backend
    that cannot run at all) leaves the readout empty and apply disabled, rather than offering to store
    "no duration".

    **Test steps:**

    * build the widget over a stored duration and hand it a computed ``None``
    * verify the readout is empty and apply is disabled
    """
    edit = MeasuredDurationEdit()
    qtbot.addWidget(edit)
    edit.set_value(8100)  # type: ignore[attr-defined]

    edit.computed = None

    assert internal_computed_label(edit).text() == ""
    assert not internal_apply_button(edit).isEnabled()
