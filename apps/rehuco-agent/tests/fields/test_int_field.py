"""Tests for IntField: label viewer and the live ``UnboundedSpinBox`` editor binding (negatives, no ceiling)."""

from borco_pyside.widgets import UnboundedSpinBox
from PySide6.QtWidgets import QLabel
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel

from fields.field_testers import IntFieldTester as IntField


def test_int_field_viewer_shows_and_tracks_the_value(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The viewer label shows the integer and re-renders when the model changes; unset (``None``)
    renders empty, not the string ``"None"`` ([[field-schema#deferred-items]]).

    **Test steps:**

    * build an ``images_count`` viewer over a model seeded ``None`` (not yet scanned)
    * verify the label starts empty
    * change ``model.images_count`` and verify the label updates live
    """
    field = IntField("images_count")
    viewer = field.make_viewer(model.bind(field)).viewer
    assert isinstance(viewer, QLabel)
    qtbot.addWidget(viewer)

    assert viewer.text() == ""

    model.images_count = 42
    assert viewer.text() == "42"


def test_int_field_viewer_renders_a_genuine_zero_honestly(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A genuine ``0`` renders as ``"0"``, distinct from the unset (``None``) empty render
    ([[field-schema#deferred-items]]).

    **Test steps:**

    * seed the model with a genuine zero, then build the ``images_count`` viewer
    * verify the label shows ``"0"``, not empty
    """
    model.images_count = 0
    field = IntField("images_count")
    viewer = field.make_viewer(model.bind(field)).viewer
    assert isinstance(viewer, QLabel)
    qtbot.addWidget(viewer)

    assert viewer.text() == "0"


def test_int_field_editor_seeds_blank_when_unset(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The editor seeds blank (``None``) from a model not yet scanned, not a coerced ``0``
    ([[field-schema#deferred-items]]).

    **Test steps:**

    * build the ``images_count`` editor over the default (``None``) model
    * verify the spin box's value and displayed text are both empty
    """
    field = IntField("images_count")
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, UnboundedSpinBox)
    qtbot.addWidget(editor)

    assert editor.value is None
    assert editor.lineEdit().text() == ""


def test_int_field_editor_writes_back_to_the_model(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Editing the spin box writes through to the model, including negative values.

    **Test steps:**

    * build the ``images_count`` editor (an ``UnboundedSpinBox``)
    * set a negative value and verify ``model.images_count`` follows (``int`` is plain, negatives allowed)
    """
    field = IntField("images_count")
    spin_box = field.make_editor(model.bind(field)).editor
    assert isinstance(spin_box, UnboundedSpinBox)
    qtbot.addWidget(spin_box)

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
    editor = field.make_editor(model.bind(field)).editor
    viewer = field.make_viewer(model.bind(field)).viewer
    assert isinstance(editor, UnboundedSpinBox)
    assert isinstance(viewer, QLabel)
    qtbot.addWidget(editor)
    qtbot.addWidget(viewer)

    editor.setValue(9)

    assert model.images_count == 9
    assert viewer.text() == "9"
    assert editor.value == 9


def test_int_field_editor_follows_an_external_model_change(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A model change from elsewhere updates the editor under the echo guard.

    **Test steps:**

    * build the ``images_count`` editor
    * change ``model.images_count`` directly (as another surface would)
    * verify the spin box follows
    """
    field = IntField("images_count")
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, UnboundedSpinBox)
    qtbot.addWidget(editor)

    model.images_count = 13
    assert editor.value == 13


def test_int_field_editor_defaults_to_no_range(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """With no explicit ``minimum``/``maximum``, the editor has no bound in either direction.

    **Test steps:**

    * build the editor for an ``IntField`` with no range arguments
    * verify the spin box's ``minimum()``/``maximum()`` are both ``None``
    """
    field = IntField("images_count")
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, UnboundedSpinBox)
    qtbot.addWidget(editor)

    assert editor.minimum() is None
    assert editor.maximum() is None


def test_int_field_editor_uses_an_explicit_range(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """An explicit ``minimum``/``maximum`` is passed straight through to the editor.

    **Test steps:**

    * build the editor for an ``IntField`` constructed with ``minimum=-10``, ``maximum=10``
    * verify the spin box's actual range matches those values
    """
    field = IntField("images_count", minimum=-10, maximum=10)
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, UnboundedSpinBox)
    qtbot.addWidget(editor)

    assert editor.minimum() == -10
    assert editor.maximum() == 10


def test_int_field_editor_accepts_a_value_beyond_int32(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The editor holds a value far past the C++ ``int`` (32-bit) ceiling ``QSpinBox`` is stuck with --
    the entire point of ``UnboundedSpinBox`` (#40).

    **Test steps:**

    * set ``model.images_count`` to a value beyond int32 before building the editor
    * build the editor and verify it holds that value exactly
    * edit it further and verify the model follows exactly, with no truncation
    """
    beyond_int32 = 2**40
    model.images_count = beyond_int32
    field = IntField("images_count")
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, UnboundedSpinBox)
    qtbot.addWidget(editor)
    assert editor.value == beyond_int32

    editor.setValue(beyond_int32 + 1)

    assert model.images_count == beyond_int32 + 1
