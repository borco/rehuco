"""Tests for SingleChoiceRadioButtons: the value-widget contract over a single-select radio group (#310)."""

from PySide6.QtWidgets import QRadioButton
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.widgets.single_choice_radio_buttons import SingleChoiceRadioButtons

CHOICES = (("tutorial", "Tutorial"), ("reference_images", "Reference Images"), ("", "(no type)"))


def buttons(widget: SingleChoiceRadioButtons) -> dict[str, QRadioButton]:
    """Return the group's radio buttons keyed by their label.

    :param widget: the widget to inspect.
    :returns: a ``label -> QRadioButton`` map.
    """
    return {button.text(): button for button in widget.findChildren(QRadioButton)}


def test_single_choice_radio_buttons_has_one_button_per_choice(qtbot: QtBot) -> None:
    """The group builds one radio button per choice, all unchecked and enabled to start.

    **Test steps:**

    * build a `SingleChoiceRadioButtons` over the three choices
    * verify it holds three buttons, none checked, all enabled, and reports an empty value
    """
    widget = SingleChoiceRadioButtons(CHOICES)
    qtbot.addWidget(widget)

    group = buttons(widget)
    assert set(group) == {"Tutorial", "Reference Images", "(no type)"}
    assert all(not button.isChecked() for button in group.values())
    assert all(button.isEnabled() for button in group.values())
    assert widget.value == ""


def test_checking_a_button_reports_its_value_and_emits(qtbot: QtBot) -> None:
    """Checking a button drives ``value`` and emits ``value_changed`` with the same value, once.

    **Test steps:**

    * build the group and record ``value_changed`` emissions
    * check ``Reference Images``
    * verify ``value`` reports its key and the signal fired exactly once with it
    """
    widget = SingleChoiceRadioButtons(CHOICES)
    qtbot.addWidget(widget)
    seen: list[str] = []
    widget.value_changed.connect(seen.append)

    buttons(widget)["Reference Images"].setChecked(True)

    assert widget.value == "reference_images"
    assert seen == ["reference_images"]


def test_checking_a_second_button_switches_the_value_and_emits_once(qtbot: QtBot) -> None:
    """The group is exclusive: checking a new button unchecks the old one, and only the new checked
    state is reported through ``value_changed`` (the old button's uncheck is filtered out).

    **Test steps:**

    * check ``Tutorial``, then ``Reference Images``
    * verify only ``Reference Images`` ends up checked and exactly two emissions fired
    """
    widget = SingleChoiceRadioButtons(CHOICES)
    qtbot.addWidget(widget)
    seen: list[str] = []
    widget.value_changed.connect(seen.append)
    group = buttons(widget)

    group["Tutorial"].setChecked(True)
    group["Reference Images"].setChecked(True)

    assert group["Tutorial"].isChecked() is False
    assert group["Reference Images"].isChecked() is True
    assert seen == ["tutorial", "reference_images"]


def test_value_setter_writes_through_set_value(qtbot: QtBot) -> None:
    """Assigning ``value`` routes through ``set_value`` -- the same guarded resync, no re-emit.

    **Test steps:**

    * build the group and record ``value_changed`` emissions
    * assign ``value``
    * verify the matching button checks and no signal fired
    """
    widget = SingleChoiceRadioButtons(CHOICES)
    qtbot.addWidget(widget)
    seen: list[str] = []
    widget.value_changed.connect(seen.append)

    widget.value = "tutorial"

    assert widget.value == "tutorial"
    assert buttons(widget)["Tutorial"].isChecked() is True
    assert not seen


def test_set_value_resyncs_without_re_emitting_and_ignores_unknowns(qtbot: QtBot) -> None:
    """``set_value`` checks the matching button under the echo guard, emitting nothing, and leaves the
    selection unchanged for an unknown value.

    **Test steps:**

    * build the group and record ``value_changed`` emissions
    * call ``set_value`` with a known choice, then with an unknown one
    * verify the known button checked, the unknown call left it checked, and no signal fired either time
    """
    widget = SingleChoiceRadioButtons(CHOICES)
    qtbot.addWidget(widget)
    seen: list[str] = []
    widget.value_changed.connect(seen.append)

    widget.set_value("reference_images")
    widget.set_value("nonexistent")

    assert widget.value == "reference_images"
    assert not seen


def test_disabled_choices_are_shown_but_not_selectable(qtbot: QtBot) -> None:
    """A value in ``disabled`` still gets a button, but it is disabled -- shown as the value in effect,
    not re-pickable (#310).

    **Test steps:**

    * build the group with ``tutorial`` disabled
    * seed it to ``tutorial``
    * verify the ``Tutorial`` button is checked yet disabled, and its siblings stay enabled
    """
    widget = SingleChoiceRadioButtons(CHOICES, disabled=("tutorial",))
    qtbot.addWidget(widget)

    widget.set_value("tutorial")

    group = buttons(widget)
    assert group["Tutorial"].isChecked() is True
    assert group["Tutorial"].isEnabled() is False
    assert group["Reference Images"].isEnabled() is True
    assert group["(no type)"].isEnabled() is True


def test_header_height_is_one_radio_buttons_height(qtbot: QtBot) -> None:
    """``header_height`` is a single radio button's natural height.

    **Test steps:**

    * build the group over the three choices
    * verify ``header_height`` matches any one button's sizeHint height
    """
    widget = SingleChoiceRadioButtons(CHOICES)
    qtbot.addWidget(widget)

    assert widget.header_height == next(iter(buttons(widget).values())).sizeHint().height()


def test_header_height_falls_back_to_a_throwaway_radio_button_when_choices_is_empty(qtbot: QtBot) -> None:
    """With no choices (no buttons to measure), ``header_height`` falls back to a plain ``QRadioButton``.

    **Test steps:**

    * build the group over an empty choice set
    * verify ``header_height`` matches a throwaway ``QRadioButton``'s sizeHint height
    """
    widget = SingleChoiceRadioButtons(())
    qtbot.addWidget(widget)

    assert widget.header_height == QRadioButton().sizeHint().height()
