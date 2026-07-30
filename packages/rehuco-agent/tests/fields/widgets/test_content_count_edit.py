"""Tests for ContentCountEdit: the stored spin box, the computed label, and the explicit apply between them."""

from borco_pyside.widgets import UnboundedSpinBox
from PySide6.QtWidgets import QLabel, QPushButton
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.widgets.content_count_edit import ContentCountEdit


def internal_spin_box(edit: ContentCountEdit) -> UnboundedSpinBox:
    """Return the widget's private stored-count spin box -- ``ContentCountEdit`` exposes no accessor.

    :param edit: the widget to inspect.
    :returns: the internal ``UnboundedSpinBox``.
    """
    return edit._ContentCountEdit__spin_box  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def internal_computed_label(edit: ContentCountEdit) -> QLabel:
    """Return the widget's private computed-count label -- ``ContentCountEdit`` exposes no accessor.

    :param edit: the widget to inspect.
    :returns: the internal ``QLabel``.
    """
    return edit._ContentCountEdit__computed_label  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def internal_apply_button(edit: ContentCountEdit) -> QPushButton:
    """Return the widget's private apply button -- ``ContentCountEdit`` exposes no accessor.

    :param edit: the widget to inspect.
    :returns: the internal ``QPushButton``.
    """
    return edit._ContentCountEdit__apply_button  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def internal_compute_button(edit: ContentCountEdit) -> QPushButton:
    """Return the widget's private compute button -- ``ContentCountEdit`` exposes no accessor.

    :param edit: the widget to inspect.
    :returns: the internal ``QPushButton``.
    """
    return edit._ContentCountEdit__compute_button  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


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
