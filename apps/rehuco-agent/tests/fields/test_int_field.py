"""Tests for IntField: label viewer and the live ``QSpinBox`` editor binding (negatives allowed)."""

from PySide6.QtWidgets import QLabel, QSpinBox
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields.int_field import IntField


def test_int_field_viewer_shows_and_tracks_the_value(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The viewer label shows the integer and re-renders when the model changes.

    **Test steps:**

    * build an ``images_count`` viewer over a model seeded ``0``
    * verify the label starts at ``"0"``
    * change ``model.images_count`` and verify the label updates live
    """
    field = IntField("images_count")
    viewer = field.make_viewer(model.bind(field))
    qtbot.addWidget(viewer)

    assert isinstance(viewer, QLabel)
    assert viewer.text() == "0"

    model.images_count = 42
    assert viewer.text() == "42"


def test_int_field_editor_writes_back_to_the_model(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Editing the spin box writes through to the model, including negative values.

    **Test steps:**

    * build the ``images_count`` editor (a single ``QSpinBox``)
    * set a negative value and verify ``model.images_count`` follows (``int`` is plain, negatives allowed)
    """
    field = IntField("images_count")
    editors = field.make_editors(model.bind(field))
    assert len(editors) == 1
    spin_box = editors[0]
    qtbot.addWidget(spin_box)
    assert isinstance(spin_box, QSpinBox)

    spin_box.setValue(-7)
    assert model.images_count == -7


def test_int_field_editor_and_viewer_echo_without_a_feedback_loop(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Editor -> model -> viewer stays live with no feedback loop (live "both").

    **Test steps:**

    * build an editor and a viewer over the same ``images_count`` field and model
    * set the editor's value
    * verify the viewer reflects it and the editor still holds the value once (no echo loop)
    """
    field = IntField("images_count")
    editor = field.make_editors(model.bind(field))[0]
    viewer = field.make_viewer(model.bind(field))
    qtbot.addWidget(editor)
    qtbot.addWidget(viewer)
    assert isinstance(editor, QSpinBox)
    assert isinstance(viewer, QLabel)

    editor.setValue(9)

    assert model.images_count == 9
    assert viewer.text() == "9"
    assert editor.value() == 9


def test_int_field_editor_follows_an_external_model_change(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A model change from elsewhere updates the editor under the echo guard.

    **Test steps:**

    * build the ``images_count`` editor
    * change ``model.images_count`` directly (as another surface would)
    * verify the spin box follows
    """
    field = IntField("images_count")
    editor = field.make_editors(model.bind(field))[0]
    qtbot.addWidget(editor)
    assert isinstance(editor, QSpinBox)

    model.images_count = 13
    assert editor.value() == 13


def test_int_field_editor_defaults_to_the_full_int32_range(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """With no explicit ``minimum``/``maximum``, the editor spans ``IntField.MINIMUM``/``MAXIMUM``.

    **Test steps:**

    * build the editor for an ``IntField`` with no range arguments
    * verify the spin box's actual range matches the class constants
    """
    field = IntField("images_count")
    editor = field.make_editors(model.bind(field))[0]
    qtbot.addWidget(editor)
    assert isinstance(editor, QSpinBox)

    assert editor.minimum() == IntField.MINIMUM
    assert editor.maximum() == IntField.MAXIMUM


def test_int_field_editor_uses_a_narrower_explicit_range(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Explicit ``minimum``/``maximum`` narrower than the int32 bounds are used as given.

    **Test steps:**

    * build the editor for an ``IntField`` constructed with ``minimum=-10``, ``maximum=10``
    * verify the spin box's actual range matches those values, not the class constants
    """
    field = IntField("images_count", minimum=-10, maximum=10)
    editor = field.make_editors(model.bind(field))[0]
    qtbot.addWidget(editor)
    assert isinstance(editor, QSpinBox)

    assert editor.minimum() == -10
    assert editor.maximum() == 10


def test_int_field_editor_boxes_a_wider_explicit_range_to_int32(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """An explicit ``minimum``/``maximum`` wider than int32 is boxed to ``IntField.MINIMUM``/``MAXIMUM``.

    **Test steps:**

    * build the editor for an ``IntField`` constructed with a range wider than the ``QSpinBox`` can hold
    * verify the spin box's actual range is clamped to the class constants, not the wider request
    """
    field = IntField("images_count", minimum=IntField.MINIMUM - 1, maximum=IntField.MAXIMUM + 1)
    editor = field.make_editors(model.bind(field))[0]
    qtbot.addWidget(editor)
    assert isinstance(editor, QSpinBox)

    assert editor.minimum() == IntField.MINIMUM
    assert editor.maximum() == IntField.MAXIMUM
