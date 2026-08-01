"""Tests for ContentCountEdit: the stored spin box, the computed label, and the explicit apply between them."""

# the measure/apply/busy contract is the one every measure row's tests pin, because all three rows are
# one `MeasuredValueEdit`; each suite pins it through its own row, which is where a user meets it
# pylint: disable=duplicate-code

from borco_pyside.widgets import UnboundedSpinBox
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.widgets.content_count_edit import ContentCountEdit

from .measure_row_internals import (
    internal_apply_button,
    internal_compute_button,
    internal_computed_label,
    internal_editor,
)


def internal_spin_box(edit: ContentCountEdit) -> UnboundedSpinBox:
    """Return the row's stored-count spin box, named for what this row puts there.

    :param edit: the widget to inspect.
    :returns: the internal ``UnboundedSpinBox``.
    """
    return internal_editor(edit)


def test_edit_starts_unset_with_nothing_computed(qtbot: QtBot) -> None:
    """A fresh row holds no stored count, shows no computed one, and offers nothing to apply.

    **Test steps:**

    * build the widget
    * verify the value and the computed count are both unset, the label is empty and apply is disabled
    """
    edit = ContentCountEdit()
    qtbot.addWidget(edit)

    assert edit.value is None
    assert edit.computed is None
    assert internal_computed_label(edit).text() == ""
    assert not internal_apply_button(edit).isEnabled()


def test_editing_the_spin_box_writes_the_value_through(qtbot: QtBot) -> None:
    """The spin box is the field's value: typing in it moves ``value``.

    **Test steps:**

    * build the widget and set the spin box's value
    * verify ``value`` followed
    """
    edit = ContentCountEdit()
    qtbot.addWidget(edit)

    internal_spin_box(edit).setValue(42)

    assert edit.value == 42


def test_setting_the_value_echoes_into_the_spin_box(qtbot: QtBot) -> None:
    """A value set from outside (the model, or apply) shows up in the spin box, with no feedback loop.

    **Test steps:**

    * build the widget and set ``value`` directly, as a bound model change would
    * verify the spin box shows it and the value survived the echo unchanged
    """
    edit = ContentCountEdit()
    qtbot.addWidget(edit)

    edit.set_value(42)  # type: ignore[attr-defined]  # the slot SimpleProperty synthesizes

    assert internal_spin_box(edit).value == 42
    assert edit.value == 42


def test_compute_asks_the_owner_rather_than_measuring(qtbot: QtBot) -> None:
    """Pressing ``Compute`` only emits -- the widget knows nothing about archives, paths, or settings.

    **Test steps:**

    * build the widget and press ``Compute``
    * verify ``compute_requested`` fired and nothing else changed
    """
    edit = ContentCountEdit()
    qtbot.addWidget(edit)

    with qtbot.waitSignal(edit.compute_requested):
        internal_compute_button(edit).click()

    assert edit.computed is None
    assert edit.value is None


def test_a_computed_count_is_shown_without_touching_the_value(qtbot: QtBot) -> None:
    """A measurement fills the label beside the stored count and leaves the stored count alone -- the
    disagreement is information, not something to silently resolve ([[data-model#image-meanings]]).

    **Test steps:**

    * build the widget over a stored ``7`` and hand it a computed ``9``
    * verify the label shows ``9`` while the value and spin box still read ``7``
    """
    edit = ContentCountEdit()
    qtbot.addWidget(edit)
    edit.set_value(7)  # type: ignore[attr-defined]

    edit.computed = 9

    assert internal_computed_label(edit).text() == "9"
    assert edit.value == 7
    assert internal_spin_box(edit).value == 7


def test_a_computed_zero_shows_as_zero_not_as_nothing(qtbot: QtBot) -> None:
    """A measured ``0`` renders honestly, distinct from the empty "never measured" label
    ([[field-schema#deferred-items]]).

    **Test steps:**

    * hand the widget a computed ``0``
    * verify the label reads ``"0"``
    """
    edit = ContentCountEdit()
    qtbot.addWidget(edit)

    edit.computed = 0

    assert internal_computed_label(edit).text() == "0"


def test_apply_is_offered_only_while_the_two_counts_differ(qtbot: QtBot) -> None:
    """``Apply`` enables exactly when there is a measurement that disagrees with the stored count.

    **Test steps:**

    * verify apply stays disabled while a measurement matches the stored count
    * verify it enables once they differ, and disables again once the stored count catches up
    """
    edit = ContentCountEdit()
    qtbot.addWidget(edit)
    edit.set_value(7)  # type: ignore[attr-defined]

    edit.computed = 7
    assert not internal_apply_button(edit).isEnabled()

    edit.computed = 9
    assert internal_apply_button(edit).isEnabled()

    edit.set_value(9)  # type: ignore[attr-defined]
    assert not internal_apply_button(edit).isEnabled()


def test_apply_stores_the_computed_count(qtbot: QtBot) -> None:
    """``Apply`` is the one action here that changes the value -- and it reports it as a value change.

    **Test steps:**

    * build the widget over a stored ``7`` with a computed ``9``
    * press apply and verify ``value_changed`` fired with the measured count
    * verify the spin box followed and apply went back to disabled
    """
    edit = ContentCountEdit()
    qtbot.addWidget(edit)
    edit.set_value(7)  # type: ignore[attr-defined]
    edit.computed = 9

    with qtbot.waitSignal(edit.value_changed) as blocker:  # type: ignore[attr-defined]
        internal_apply_button(edit).click()

    assert blocker.args == [9]
    assert edit.value == 9
    assert internal_spin_box(edit).value == 9
    assert not internal_apply_button(edit).isEnabled()


def test_an_unmeasurable_count_shows_nothing_and_applies_nothing(qtbot: QtBot) -> None:
    """A measurement that could not run (``None`` -- e.g. a document with no path yet) leaves the label
    empty and apply disabled, rather than offering to store "no count".

    **Test steps:**

    * build the widget over a stored ``7`` and hand it a computed ``None``
    * verify the label is empty and apply is disabled
    """
    edit = ContentCountEdit()
    qtbot.addWidget(edit)
    edit.set_value(7)  # type: ignore[attr-defined]

    edit.computed = None

    assert internal_computed_label(edit).text() == ""
    assert not internal_apply_button(edit).isEnabled()


def test_compute_enters_the_busy_state_and_disables_both_actions(qtbot: QtBot) -> None:
    """A count in flight disables the buttons: opening every archive a pack holds takes time, and
    neither a second count nor an apply of a half-finished answer may be pressed meanwhile (#198, #223).

    **Test steps:**

    * build the widget over a stored count with a stale measurement already showing, so apply is offered
    * press ``Compute``
    * verify the widget is busy and both buttons are disabled
    """
    edit = ContentCountEdit()
    qtbot.addWidget(edit)
    edit.set_value(7)  # type: ignore[attr-defined]
    edit.computed = 9
    assert internal_apply_button(edit).isEnabled()

    internal_compute_button(edit).click()

    assert edit.busy is True
    assert not internal_compute_button(edit).isEnabled()
    assert not internal_apply_button(edit).isEnabled()


def test_showing_a_measurement_leaves_the_busy_state(qtbot: QtBot) -> None:
    """The owner's answer is what ends the count: the buttons come back and the result is on screen.

    **Test steps:**

    * press ``Compute``, then hand the widget a result
    * verify it is no longer busy, the readout shows the result, and both buttons are offered again
    """
    edit = ContentCountEdit()
    qtbot.addWidget(edit)
    internal_compute_button(edit).click()

    edit.show_measurement(9)

    assert edit.busy is False
    assert edit.computed == 9
    assert internal_computed_label(edit).text() == "9"
    assert internal_compute_button(edit).isEnabled()
    assert internal_apply_button(edit).isEnabled()


def test_a_failed_measurement_still_leaves_the_busy_state(qtbot: QtBot) -> None:
    """A count that measured nothing still hands back an answer, so the row never strands itself busy
    with a permanently dead ``Compute``.

    **Test steps:**

    * press ``Compute``, then hand the widget ``None``
    * verify it is no longer busy and compute is offered again
    """
    edit = ContentCountEdit()
    qtbot.addWidget(edit)
    internal_compute_button(edit).click()

    edit.show_measurement(None)

    assert edit.busy is False
    assert internal_compute_button(edit).isEnabled()
