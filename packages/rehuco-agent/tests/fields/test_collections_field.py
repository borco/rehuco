"""Tests for CollectionsField: the ``Title [index]`` viewer, the hide-when-empty row, and the table."""

from typing import Any

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
from pytest import fixture, raises
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields.widgets import CollectionsEditor

from fields.field_testers import CollectionsFieldTester as CollectionsField
from fields.field_testers import IndexedListFieldTester

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


def shown_row(container: QWidget, field: CollectionsField, model: RehuDocumentModel) -> tuple[QWidget, QLabel]:
    """Build the field's viewer row into ``container`` and put it on screen, so its visibility is
    answerable.

    A parentless widget is hidden whether or not anything decided so; only a row that has been laid out
    and shown can say whether the field revealed or collapsed it.

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


def editor_of(field: CollectionsField, model: RehuDocumentModel, qtbot: QtBot) -> CollectionsEditor:
    """Build the field's editor and keep it alive for the test.

    :param field: the field to build.
    :param model: the model to bind against.
    :param qtbot: the bot to register the widget with.
    :returns: the editor widget.
    """
    bundle = field.make_editor(model.bind(field))
    assert isinstance(bundle.editor, CollectionsEditor)
    qtbot.addWidget(bundle.editor)
    return bundle.editor


def test_collections_viewer_renders_each_entry_with_its_index(container: QWidget, model: RehuDocumentModel) -> None:
    """Each membership renders as ``Title [index]``, sorted by index then title even though the records
    are stored in whatever order they were written ([[field-schema#sources]]).

    **Test steps:**

    * seed the model's ``collections`` with two placed memberships, stored out of order
    * build the viewer
    * verify both render with their index, index-ordered and comma-joined
    """
    model.collections = [{"title": "Sculpting Advanced", "index": 4}, {"title": "Sculpting Basics", "index": 1}]
    field = CollectionsField("collections")

    _, viewer = shown_row(container, field, model)

    assert viewer.text() == "Sculpting Basics [1], Sculpting Advanced [4]"
    assert viewer.wordWrap() is True


def test_collections_viewer_omits_an_unplaced_index(container: QWidget, model: RehuDocumentModel) -> None:
    """Index ``0`` means *no position chosen* ([[field-schema#sources]], #188), so it renders as no
    position at all rather than as a placement nobody made.

    **Test steps:**

    * seed two memberships at index ``0``, as a legacy import writes them
    * verify each renders as its bare title
    """
    model.collections = [{"title": "Anatomy Deep Dive", "index": 0}, {"title": "Weekend Warmups"}]
    field = CollectionsField("collections")

    _, viewer = shown_row(container, field, model)

    assert viewer.text() == "Anatomy Deep Dive, Weekend Warmups"


def test_collections_viewer_mixes_placed_and_unplaced_entries(container: QWidget, model: RehuDocumentModel) -> None:
    """A placed entry keeps its index beside an unplaced one -- the rule is per entry, not per list.

    **Test steps:**

    * seed one membership at index ``0`` and one at a real position
    * verify only the placed one shows a number
    """
    model.collections = [{"title": "Imported", "index": 0}, {"title": "My Order", "index": 7}]
    field = CollectionsField("collections")

    _, viewer = shown_row(container, field, model)

    assert viewer.text() == "Imported, My Order [7]"


def test_collections_viewer_tracks_the_model(container: QWidget, model: RehuDocumentModel) -> None:
    """The viewer re-renders when the model's value changes (a revert, a type switch, an edit).

    **Test steps:**

    * build the viewer over a seeded value
    * replace the model's value
    * verify the label follows
    """
    model.collections = [{"title": "First", "index": 1}]
    field = CollectionsField("collections")
    _, viewer = shown_row(container, field, model)

    model.collections = [{"title": "Second", "index": 2}]

    assert viewer.text() == "Second [2]"


def test_collections_viewer_hides_the_whole_row_when_empty(container: QWidget, model: RehuDocumentModel) -> None:
    """A resource belonging to nothing gets no row at all, rather than a permanently blank one.

    **Test steps:**

    * build the viewer over an empty value
    * verify both the label and the value are hidden
    """
    field = CollectionsField("collections")

    label, viewer = shown_row(container, field, model)

    assert model.collections == []
    assert label.isVisible() is False
    assert viewer.isVisible() is False


def test_collections_viewer_reveals_the_row_when_a_value_arrives(container: QWidget, model: RehuDocumentModel) -> None:
    """The collapsed row comes back live once there is something to show.

    **Test steps:**

    * build the viewer over an empty value, so the row starts collapsed
    * set a membership on the model
    * verify both cells are visible again and carry the value
    """
    field = CollectionsField("collections")
    label, viewer = shown_row(container, field, model)

    model.collections = [{"title": "First", "index": 1}]

    assert label.isVisible() is True
    assert viewer.isVisible() is True
    assert viewer.text() == "First [1]"


def test_collections_viewer_collapses_the_row_when_the_value_goes_away(
    container: QWidget, model: RehuDocumentModel
) -> None:
    """A value that empties takes its row with it, the mirror of the reveal above.

    **Test steps:**

    * build the viewer over a seeded value
    * clear the model's value
    * verify both cells are hidden
    """
    model.collections = [{"title": "First", "index": 1}]
    field = CollectionsField("collections")
    label, viewer = shown_row(container, field, model)

    model.collections = []

    assert label.isVisible() is False
    assert viewer.isVisible() is False


def test_collections_viewer_ignores_a_record_it_cannot_show(container: QWidget, model: RehuDocumentModel) -> None:
    """A record with no usable title has nothing to show, so it is skipped rather than rendered blank
    ([[data-model#write-integrity]]) -- and a list of nothing but such records still collapses the row.

    **Test steps:**

    * seed one titleless record beside a real one
    * verify only the real one renders
    """
    model.collections = [{"index": 2}, {"title": "Real", "index": 1}]
    field = CollectionsField("collections")

    _, viewer = shown_row(container, field, model)

    assert viewer.text() == "Real [1]"


def test_collections_editor_shows_the_stored_records(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The editor binds the records themselves, in stored order -- unlike the viewer, which sorts.

    **Test steps:**

    * seed two memberships stored out of index order
    * build the editor
    * verify its rows are the stored records, in stored order
    """
    model.collections = [{"title": "Second", "index": 2}, {"title": "First", "index": 1}]
    field = CollectionsField("collections")

    editor = editor_of(field, model, qtbot)

    assert editor.value == [{"title": "Second", "index": 2}, {"title": "First", "index": 1}]


def test_collections_editor_writes_an_edit_back_to_the_model(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """An edit in the table reaches the model, which is what makes the viewer beside it re-render.

    **Test steps:**

    * build the editor over one membership
    * retype its title through the model layer the table edits
    * verify the model's value carries the new title
    """
    model.collections = [{"title": "Old", "index": 1, "url": "https://example.com"}]
    field = CollectionsField("collections")
    editor = editor_of(field, model, qtbot)

    editor.model.setData(editor.model.index(0, 0), "New")

    assert model.collections == [{"title": "New", "index": 1, "url": "https://example.com"}]


def test_collections_editor_is_seeded_without_reporting_an_edit(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Seeding is not an edit: the model's own value echoing back into the table must not report one, or
    every open would count as a change (the echo guard, [[plugins#field-toolkit]]).

    **Test steps:**

    * build the editor and record what it reports
    * push a new value through the model, as a revert would
    * verify the table shows it and reported nothing
    """
    field = CollectionsField("collections")
    editor = editor_of(field, model, qtbot)
    reported: list[Any] = []
    editor.value_changed.connect(reported.append)

    model.collections = [{"title": "Reverted", "index": 3}]

    assert editor.value == [{"title": "Reverted", "index": 3}]
    assert not reported


def test_the_shared_viewer_has_no_projection_of_its_own() -> None:
    """Turning a field's stored records into the entries a viewer shows is exactly where the two record
    lists differ, so the base has no answer -- rendering the result is all that is shared.

    **Test steps:**

    * ask the base for the entries of a value
    * verify it refuses
    """
    field = IndexedListFieldTester("collections")

    with raises(NotImplementedError):
        field.entries([])
