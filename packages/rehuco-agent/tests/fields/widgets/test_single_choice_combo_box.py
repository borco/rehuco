"""Tests for SingleChoiceComboBox: the value-widget contract over a ``(value, label)`` choice set."""

from PySide6.QtWidgets import QComboBox
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.widgets.single_choice_combo_box import SingleChoiceComboBox

CHOICES = [("", "(no type)"), ("tutorial", "Tutorial"), ("reference_images", "Reference Images")]


def test_single_choice_combo_box_is_a_combo_box_showing_labels(qtbot: QtBot) -> None:
    """A `SingleChoiceComboBox` is a ``QComboBox`` displaying each choice's **label**, holding its value.

    **Test steps:**

    * build one over the sample choices
    * verify it is a ``QComboBox``, shows the labels, and reports the first choice's value
    """
    combo = SingleChoiceComboBox(CHOICES)
    qtbot.addWidget(combo)

    assert isinstance(combo, QComboBox)
    assert [combo.itemText(i) for i in range(combo.count())] == ["(no type)", "Tutorial", "Reference Images"]
    assert combo.value == ""


def test_selecting_an_item_emits_value_changed_with_its_value_not_its_label(qtbot: QtBot) -> None:
    """Choosing an item emits ``value_changed`` with the item's **value** (its data), never its label.

    **Test steps:**

    * build a combo and record ``value_changed`` emissions
    * select the ``tutorial`` item by index
    * verify ``value`` follows and the signal fired once with the value, not the label
    """
    combo = SingleChoiceComboBox(CHOICES)
    qtbot.addWidget(combo)
    seen: list[str] = []
    combo.value_changed.connect(seen.append)

    combo.setCurrentIndex(1)

    assert combo.value == "tutorial"
    assert seen == ["tutorial"]


def test_set_value_selects_the_matching_choice_without_re_emitting(qtbot: QtBot) -> None:
    """``set_value`` selects the choice whose value matches, without re-emitting ``value_changed``
    (the echo guard).

    **Test steps:**

    * build a combo and record ``value_changed`` emissions
    * call ``set_value`` with a value
    * verify the selection moved to that value's item but no ``value_changed`` fired
    """
    combo = SingleChoiceComboBox(CHOICES)
    qtbot.addWidget(combo)
    seen: list[str] = []
    combo.value_changed.connect(seen.append)

    combo.set_value("reference_images")

    assert combo.value == "reference_images"
    assert not seen


def test_set_value_with_an_unknown_value_leaves_the_selection_unchanged(qtbot: QtBot) -> None:
    """A value not among the choices leaves the current selection alone rather than clearing it.

    **Test steps:**

    * build a combo already on the ``tutorial`` item
    * call ``set_value`` with a value not offered
    * verify the selection is unchanged and no signal fired
    """
    combo = SingleChoiceComboBox(CHOICES)
    qtbot.addWidget(combo)
    combo.set_value("tutorial")
    seen: list[str] = []
    combo.value_changed.connect(seen.append)

    combo.set_value("daz3d")

    assert combo.value == "tutorial"
    assert not seen


def test_value_setter_delegates_to_set_value(qtbot: QtBot) -> None:
    """Assigning ``value`` selects the matching choice through the same guarded path as ``set_value``.

    **Test steps:**

    * build a combo and record ``value_changed`` emissions
    * assign ``value``
    * verify the selection moved and no ``value_changed`` fired
    """
    combo = SingleChoiceComboBox(CHOICES)
    qtbot.addWidget(combo)
    seen: list[str] = []
    combo.value_changed.connect(seen.append)

    combo.value = "tutorial"

    assert combo.value == "tutorial"
    assert not seen
