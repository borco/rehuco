"""Tests for LearningPathsField: the identity-resolved viewer, and the cross-scope table beside it."""

from typing import Any

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
from pytest import fixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields.widgets import ExpandToggleButton, LearningPathsEditor

from fields.field_testers import LearningPathsFieldTester as LearningPathsField

# The viewer-row scaffolding is the same here as in the sibling membership field's tests -- one field per
# file, and the two rows genuinely are built and shown the same way ([[plugins#field-toolkit]]).
# pylint: disable=duplicate-code


@fixture
def container(qtbot: QtBot) -> QWidget:
    """A shown host for a viewer row -- a fixture rather than a local, because ``qtbot`` holds only a
    weak reference and a collected container takes its children's C++ objects with it."""
    widget = QWidget()
    QVBoxLayout(widget)
    qtbot.addWidget(widget)
    return widget


def shown_row(container: QWidget, field: LearningPathsField, model: RehuDocumentModel) -> tuple[QWidget, QLabel]:
    """Build the field's viewer row into ``container`` and put it on screen, so its visibility is
    answerable.

    :param container: the host widget to lay the row out in.
    :param field: the field to build.
    :param model: the model to bind against.
    :returns: the row's ``(label, viewer)`` pair.
    """
    bundle = field.make_viewer(model.bind(field))
    assert bundle.label is not None
    assert isinstance(bundle.viewer, QLabel)
    layout = container.layout()
    assert layout is not None
    layout.addWidget(bundle.label)
    layout.addWidget(bundle.viewer)
    container.show()
    return bundle.label, bundle.viewer


def test_learning_paths_viewer_resolves_for_its_own_identity(container: QWidget, model: RehuDocumentModel) -> None:
    """The viewer answers *what am I in*: this identity's own paths, its subscriptions, and the reserved
    ``public`` scope -- never another identity's private one ([[field-schema#learning-path-ownership]]).

    **Test steps:**

    * seed one owned path, a subscription to a published one, and another identity's private path
    * verify only the first two render, index-ordered
    """
    model.learning_paths = {
        "admin": [{"title": "My Order", "index": 7, "ref": 2}, {"ref": 1}],
        "public": [{"title": "Shared", "index": 3, "ref": 1}],
        "foo": [{"title": "Private", "index": 1, "ref": 3}],
    }
    field = LearningPathsField("learning_paths", username="admin")

    _, viewer = shown_row(container, field, model)

    assert viewer.text() == "Shared [3], My Order [7]"


def test_learning_paths_viewer_omits_an_unplaced_index(container: QWidget, model: RehuDocumentModel) -> None:
    """Index ``0`` means *no order chosen yet*, which is what a legacy import writes (#188), so it renders
    as no position at all.

    **Test steps:**

    * seed two owned paths at index ``0``
    * verify each renders as its bare title, alphabetically
    """
    model.learning_paths = {
        "admin": [{"title": "Weekend Warmups", "index": 0, "ref": 1}, {"title": "Anatomy", "index": 0, "ref": 2}]
    }
    field = LearningPathsField("learning_paths", username="admin")

    _, viewer = shown_row(container, field, model)

    assert viewer.text() == "Anatomy, Weekend Warmups"


def test_learning_paths_viewer_hides_the_whole_row_when_the_identity_is_in_none(
    container: QWidget, model: RehuDocumentModel
) -> None:
    """An identity in no path gets no row, even where the file carries somebody else's -- the row follows
    what *this* identity sees, not what the file holds.

    **Test steps:**

    * seed only another identity's private path
    * verify both cells are hidden
    """
    model.learning_paths = {"foo": [{"title": "Private", "index": 1, "ref": 1}]}
    field = LearningPathsField("learning_paths", username="admin")

    label, viewer = shown_row(container, field, model)

    assert label.isVisible() is False
    assert viewer.isVisible() is False


def test_learning_paths_viewer_tracks_the_model(container: QWidget, model: RehuDocumentModel) -> None:
    """The viewer re-renders when the model's value changes -- including an edit made in the table beside it.

    **Test steps:**

    * build the viewer over an empty value
    * give this identity a path
    * verify the row is revealed and carries it
    """
    field = LearningPathsField("learning_paths", username="admin")
    label, viewer = shown_row(container, field, model)

    model.learning_paths = {"admin": [{"title": "Mine", "index": 2, "ref": 1}]}

    assert label.isVisible() is True
    assert viewer.text() == "Mine [2]"


def test_learning_paths_editor_carries_every_scope(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The editor binds every scope's records, which is more than the viewer shows -- another identity's
    private paths are exactly what it exists to be able to act on (#235).

    **Test steps:**

    * seed one owned path and one private to another identity
    * build the editor
    * verify both scopes are in its value
    """
    model.learning_paths = {
        "admin": [{"title": "Mine", "index": 1, "ref": 1}],
        "foo": [{"title": "Theirs", "index": 2, "ref": 2}],
    }
    field = LearningPathsField("learning_paths", username="admin")

    bundle = field.make_editor(model.bind(field))
    assert isinstance(bundle.editor, LearningPathsEditor)
    qtbot.addWidget(bundle.editor)

    assert set(bundle.editor.value) == {"admin", "foo"}


def test_learning_paths_editor_row_carries_the_all_scopes_toggle(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The view switch sits in the row's ``misc`` column, where the ``authors`` field puts its own mode
    toggle -- a view choice belongs beside the row it re-renders, not inside the table.

    **Test steps:**

    * build the editor bundle
    * verify the misc slot carries a toggle, unchecked (the identity's own view)
    * check it and verify the editor switched to every scope
    """
    field = LearningPathsField("learning_paths", username="admin")

    bundle = field.make_editor(model.bind(field))
    assert isinstance(bundle.editor, LearningPathsEditor)
    assert isinstance(bundle.misc, ExpandToggleButton)
    qtbot.addWidget(bundle.editor)
    qtbot.addWidget(bundle.misc)

    assert bundle.misc.isChecked() is False
    bundle.misc.defaultAction().setChecked(True)

    assert bundle.editor.all_scopes is True


def test_learning_paths_toggle_follows_a_restored_view(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A view restored from the saved session state arrives *after* the toggle was built, so the toggle is
    kept in step with the editor rather than merely seeded from it.

    **Test steps:**

    * build the editor bundle
    * restore the all-scopes view on the editor, as the session restore does
    * verify the toggle shows it, and that showing it did not re-apply the change
    """
    field = LearningPathsField("learning_paths", username="admin")
    bundle = field.make_editor(model.bind(field))
    assert isinstance(bundle.editor, LearningPathsEditor)
    assert isinstance(bundle.misc, ExpandToggleButton)
    qtbot.addWidget(bundle.editor)
    qtbot.addWidget(bundle.misc)

    bundle.editor.restore_state(b"\x01")

    assert bundle.misc.isChecked() is True
    assert bundle.editor.all_scopes is True


def test_learning_paths_editor_writes_an_edit_back_to_the_model(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """An edit in the table reaches the model, keyed by scope, which is what makes the viewer re-render.

    **Test steps:**

    * build the editor over one owned path
    * retype its title
    * verify the model's value carries it, ``ref`` intact
    """
    model.learning_paths = {"admin": [{"title": "Old", "index": 1, "ref": 4}]}
    field = LearningPathsField("learning_paths", username="admin")
    bundle = field.make_editor(model.bind(field))
    assert isinstance(bundle.editor, LearningPathsEditor)
    qtbot.addWidget(bundle.editor)

    bundle.editor.model.setData(bundle.editor.model.index(0, 0), "New")

    assert model.learning_paths == {"admin": [{"title": "New", "index": 1, "ref": 4}]}


def test_learning_paths_editor_is_seeded_without_reporting_an_edit(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Seeding is not an edit, the same echo guard the collections table keeps.

    **Test steps:**

    * build the editor and record what it reports
    * push a new value through the model, as a revert would
    * verify the table shows it and reported nothing
    """
    field = LearningPathsField("learning_paths", username="admin")
    bundle = field.make_editor(model.bind(field))
    assert isinstance(bundle.editor, LearningPathsEditor)
    qtbot.addWidget(bundle.editor)
    reported: list[Any] = []
    bundle.editor.value_changed.connect(reported.append)

    model.learning_paths = {"admin": [{"title": "Reverted", "ref": 1}]}

    assert bundle.editor.value == {"admin": [{"title": "Reverted", "ref": 1}]}
    assert not reported
