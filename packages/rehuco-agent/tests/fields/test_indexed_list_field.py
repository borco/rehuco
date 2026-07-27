"""Tests for IndexedListField: the ``Title [index]`` viewer, the hide-when-empty row, and no editor."""

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
from pytest import fixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_core import CollectionEntry, LearningPathEntry

from fields.field_testers import IndexedListFieldTester as IndexedListField


@fixture
def container(qtbot: QtBot) -> QWidget:
    """A shown host for a viewer row -- a fixture rather than a local, because ``qtbot`` holds only a
    weak reference and a collected container takes its children's C++ objects with it."""
    widget = QWidget()
    QVBoxLayout(widget)
    qtbot.addWidget(widget)
    return widget


def shown_row(container: QWidget, field: IndexedListField, model: RehuDocumentModel) -> tuple[QWidget, QLabel]:
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


def test_indexed_list_viewer_renders_each_entry_with_its_index(container: QWidget, model: RehuDocumentModel) -> None:
    """Each entry renders as ``Title [index]``, comma-joined in the order the model resolved.

    **Test steps:**

    * seed the model's ``collections`` with two placed memberships
    * build the viewer
    * verify both render with their index, comma-joined
    """
    model.collections = [CollectionEntry(1, "Sculpting Basics"), CollectionEntry(4, "Sculpting Advanced")]
    field = IndexedListField("collections")

    _, viewer = shown_row(container, field, model)

    assert viewer.text() == "Sculpting Basics [1], Sculpting Advanced [4]"
    assert viewer.wordWrap() is True


def test_indexed_list_viewer_omits_an_unplaced_index(container: QWidget, model: RehuDocumentModel) -> None:
    """Index ``0`` means *no position chosen* ([[field-schema#sources]], #188), so it renders as no
    position at all rather than as a placement nobody made.

    **Test steps:**

    * seed two learning paths at index ``0``, as a legacy import writes them
    * verify each renders as its bare title
    """
    model.learning_paths = [LearningPathEntry(0, "Anatomy Deep Dive"), LearningPathEntry(0, "Weekend Warmups")]
    field = IndexedListField("learning_paths")

    _, viewer = shown_row(container, field, model)

    assert viewer.text() == "Anatomy Deep Dive, Weekend Warmups"


def test_indexed_list_viewer_mixes_placed_and_unplaced_entries(container: QWidget, model: RehuDocumentModel) -> None:
    """A placed entry keeps its index beside an unplaced one -- the rule is per entry, not per list.

    **Test steps:**

    * seed one path at index ``0`` and one at a real position
    * verify only the placed one shows a number
    """
    model.learning_paths = [LearningPathEntry(0, "Imported"), LearningPathEntry(7, "My Order")]
    field = IndexedListField("learning_paths")

    _, viewer = shown_row(container, field, model)

    assert viewer.text() == "Imported, My Order [7]"


def test_indexed_list_viewer_tracks_the_model(container: QWidget, model: RehuDocumentModel) -> None:
    """The viewer re-renders when the model's value changes (a revert, a type switch).

    **Test steps:**

    * build the viewer over a seeded value
    * replace the model's value
    * verify the label follows
    """
    model.collections = [CollectionEntry(1, "First")]
    field = IndexedListField("collections")
    _, viewer = shown_row(container, field, model)

    model.collections = [CollectionEntry(2, "Second")]

    assert viewer.text() == "Second [2]"


def test_indexed_list_viewer_hides_the_whole_row_when_empty(container: QWidget, model: RehuDocumentModel) -> None:
    """A resource belonging to nothing gets no row at all, rather than a permanently blank one.

    **Test steps:**

    * build the viewer over an empty value
    * verify both the label and the value are hidden
    """
    field = IndexedListField("collections")

    label, viewer = shown_row(container, field, model)

    assert model.collections == []
    assert label.isVisible() is False
    assert viewer.isVisible() is False


def test_indexed_list_viewer_reveals_the_row_when_a_value_arrives(container: QWidget, model: RehuDocumentModel) -> None:
    """The collapsed row comes back live once there is something to show.

    **Test steps:**

    * build the viewer over an empty value, so the row starts collapsed
    * set a membership on the model
    * verify both cells are visible again and carry the value
    """
    field = IndexedListField("collections")
    label, viewer = shown_row(container, field, model)

    model.collections = [CollectionEntry(1, "First")]

    assert label.isVisible() is True
    assert viewer.isVisible() is True
    assert viewer.text() == "First [1]"


def test_indexed_list_viewer_collapses_the_row_when_the_value_goes_away(
    container: QWidget, model: RehuDocumentModel
) -> None:
    """A value that empties takes its row with it, the mirror of the reveal above.

    **Test steps:**

    * build the viewer over a seeded value
    * clear the model's value
    * verify both cells are hidden
    """
    model.collections = [CollectionEntry(1, "First")]
    field = IndexedListField("collections")
    label, viewer = shown_row(container, field, model)

    model.collections = []

    assert label.isVisible() is False
    assert viewer.isVisible() is False


def test_indexed_list_field_contributes_no_editor_row(model: RehuDocumentModel) -> None:
    """Editing these needs a table with per-field columns, which is #97's record-list machinery -- so the
    editor surface gets no row.

    **Test steps:**

    * build the editor bundle
    * verify every slot is empty, which is what makes the assembler drop the row
    """
    field = IndexedListField("collections")

    bundle = field.make_editor(model.bind(field))

    assert bundle.label is None
    assert bundle.editor is None
    assert bundle.misc is None
