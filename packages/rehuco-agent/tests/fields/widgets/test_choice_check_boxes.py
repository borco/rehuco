"""Tests for ChoiceCheckBoxes: the value-widget contract over a multi-select checkbox group."""

from PySide6.QtWidgets import QCheckBox
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.widgets.choice_check_boxes import ChoiceCheckBoxes

CHOICES = ("beginner", "intermediate", "advanced", "any")


def checkboxes(widget: ChoiceCheckBoxes) -> dict[str, QCheckBox]:
    """Return the group's checkboxes keyed by their label.

    :param widget: the widget to inspect.
    :returns: a ``label -> QCheckBox`` map.
    """
    return {checkbox.text(): checkbox for checkbox in widget.findChildren(QCheckBox)}


def test_choice_check_boxes_has_one_box_per_choice(qtbot: QtBot) -> None:
    """The group builds one checkbox per choice, all unchecked to start.

    **Test steps:**

    * build a `ChoiceCheckBoxes` over the four choices
    * verify it holds four boxes and reports an empty value
    """
    widget = ChoiceCheckBoxes(CHOICES)
    qtbot.addWidget(widget)

    assert set(checkboxes(widget)) == set(CHOICES)
    assert not widget.value


def test_choice_check_boxes_reports_value_in_choices_order(qtbot: QtBot) -> None:
    """``value`` is reported in ``choices`` order regardless of click order, emitting on each toggle.

    **Test steps:**

    * build the group and record ``value_changed`` emissions
    * check ``advanced`` then ``beginner``
    * verify ``value`` orders them by ``choices`` and the signal fired with each recomputed selection
    """
    widget = ChoiceCheckBoxes(CHOICES)
    qtbot.addWidget(widget)
    seen: list[list[str]] = []
    widget.value_changed.connect(seen.append)
    boxes = checkboxes(widget)

    boxes["advanced"].setChecked(True)
    boxes["beginner"].setChecked(True)

    assert widget.value == ["beginner", "advanced"]
    assert seen == [["advanced"], ["beginner", "advanced"]]


def test_choice_check_boxes_value_setter_writes_through_set_value(qtbot: QtBot) -> None:
    """Assigning ``value`` routes through ``set_value`` -- the same guarded resync, no re-emit.

    **Test steps:**

    * build the group and record ``value_changed`` emissions
    * assign ``value``
    * verify the boxes reflect it and no signal fired
    """
    widget = ChoiceCheckBoxes(CHOICES)
    qtbot.addWidget(widget)
    seen: list[list[str]] = []
    widget.value_changed.connect(seen.append)

    widget.value = ["intermediate"]

    assert widget.value == ["intermediate"]
    assert not seen


def test_header_height_is_one_checkboxs_height(qtbot: QtBot) -> None:
    """``header_height`` is a single checkbox's natural height.

    **Test steps:**

    * build the group over the four choices
    * verify ``header_height`` matches any one checkbox's sizeHint height
    """
    widget = ChoiceCheckBoxes(CHOICES)
    qtbot.addWidget(widget)

    assert widget.header_height == next(iter(checkboxes(widget).values())).sizeHint().height()


def test_header_height_falls_back_to_a_throwaway_checkbox_when_choices_is_empty(qtbot: QtBot) -> None:
    """With no choices (no boxes to measure), ``header_height`` falls back to a plain ``QCheckBox``.

    **Test steps:**

    * build the group over an empty choice set
    * verify ``header_height`` matches a throwaway ``QCheckBox``'s sizeHint height
    """
    widget = ChoiceCheckBoxes(())
    qtbot.addWidget(widget)

    assert widget.header_height == QCheckBox().sizeHint().height()


def test_choice_check_boxes_set_value_resyncs_without_re_emitting(qtbot: QtBot) -> None:
    """``set_value`` applies a selection under the echo guard, emitting nothing, ignoring unknowns.

    **Test steps:**

    * build the group and record ``value_changed`` emissions
    * call ``set_value`` with two known choices plus an unknown one
    * verify only the known boxes checked, the value reflects them, and no signal fired
    """
    widget = ChoiceCheckBoxes(CHOICES)
    qtbot.addWidget(widget)
    seen: list[list[str]] = []
    widget.value_changed.connect(seen.append)

    widget.set_value(["any", "beginner", "nonexistent"])

    boxes = checkboxes(widget)
    assert boxes["beginner"].isChecked() is True
    assert boxes["any"].isChecked() is True
    assert boxes["intermediate"].isChecked() is False
    assert widget.value == ["beginner", "any"]
    assert not seen
