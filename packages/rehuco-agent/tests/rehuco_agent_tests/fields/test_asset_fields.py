"""Tests for the fields an asset adds to the editor (#678): optional text and link, a closed choice, text with known
values, a map of text to text, a size, and a date that keeps a time. Each binds an asset's own field, empty meaning
absent."""

from datetime import UTC, datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QLineEdit
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields.widgets import (
    DateEdit,
    EditableChoiceComboBox,
    LineEdit,
    SingleChoiceComboBox,
    SizeEdit,
    StringMapValueEditor,
)
from rehuco_core import ASSET_KINDS, ASSET_LICENSES

from rehuco_agent_tests.fields.field_testers import (
    ChoiceFieldTester,
    DateFieldTester,
    OptionalTextFieldTester,
    OptionalUrlFieldTester,
    SizeFieldTester,
    StringMapFieldTester,
    TextChoiceFieldTester,
)

# region Optional text


def test_optional_text_shows_and_tracks_the_text_and_empty_is_blank(
    qtbot: QtBot, asset_model: RehuDocumentModel
) -> None:
    """The viewer shows the text and follows the model; an absent value is blank, never ``"None"``.

    **Test steps:**

    * build an ``advertised_version`` viewer over an asset with none
    * verify it is blank, set a version, and verify the label shows it
    """
    field = OptionalTextFieldTester("advertised_version")
    viewer = field.make_viewer(asset_model.bind(field)).viewer
    assert isinstance(viewer, QLabel)
    qtbot.addWidget(viewer)

    assert viewer.text() == ""

    asset_model.advertised_version = "1.2"
    assert viewer.text() == "1.2"


def test_optional_text_editor_writes_text_and_clears_to_absent(qtbot: QtBot, asset_model: RehuDocumentModel) -> None:
    """Typing writes the text, and emptying the line removes the key rather than storing ``""``.

    **Test steps:**

    * build the ``current_version`` editor over an asset with a version
    * verify it is seeded, retype it and clear it
    * verify the model holds the text and then nothing, and the block no longer has the key
    """
    asset_model.current_version = "1.1"
    field = OptionalTextFieldTester("current_version")
    editor = field.make_editor(asset_model.bind(field)).editor
    assert isinstance(editor, LineEdit)
    qtbot.addWidget(editor)
    assert editor.text() == "1.1"

    editor.setText("1.3")
    assert asset_model.current_version == "1.3"

    editor.setText("")
    assert asset_model.current_version is None
    assert "current_version" not in asset_model.document.active_block

    asset_model.current_version = "2.0"
    assert editor.text() == "2.0"


def test_optional_text_never_refuses_what_is_typed(qtbot: QtBot, asset_model: RehuDocumentModel) -> None:
    """A range typed by hand that is no range is kept as typed: the field restricts nothing (#678).

    **Test steps:**

    * build the ``advertised_triangles`` editor and type a text that is no range
    * verify the model holds it as it was typed
    """
    field = OptionalTextFieldTester("advertised_triangles")
    editor = field.make_editor(asset_model.bind(field)).editor
    assert isinstance(editor, LineEdit)
    qtbot.addWidget(editor)

    editor.setText("about 12k")

    assert asset_model.advertised_triangles == "about 12k"


# endregion

# region Optional link


def test_optional_url_links_what_is_stored_and_edits_as_text(qtbot: QtBot, asset_model: RehuDocumentModel) -> None:
    """The viewer is a link to the stored URL, blank when there is none, and the editor clears to absent.

    **Test steps:**

    * build the ``license_url`` viewer and editor over an asset with none
    * verify the link is blank, store a URL and verify it links there
    * clear the editor and verify the key is gone
    """
    field = OptionalUrlFieldTester("license_url", "License URL")
    viewer = field.make_viewer(asset_model.bind(field)).viewer
    editor = field.make_editor(asset_model.bind(field)).editor
    assert isinstance(viewer, QLabel)
    assert isinstance(editor, LineEdit)
    qtbot.addWidget(viewer)
    qtbot.addWidget(editor)
    assert viewer.text() == ""

    editor.setText("https://fab.com/eula")

    assert asset_model.license_url == "https://fab.com/eula"
    assert "https://fab.com/eula" in viewer.text()
    editor.setText("")
    assert "license_url" not in asset_model.document.active_block
    assert viewer.text() == ""


# endregion

# region Closed choice


def test_choice_offers_none_then_each_choice_and_writes_the_pick(qtbot: QtBot, asset_model: RehuDocumentModel) -> None:
    """The editor's first entry is empty, then one per choice in order; picking writes the choice, and the empty entry
    removes the key.

    **Test steps:**

    * build the ``kind`` editor over an asset with none
    * verify the entries and that the empty one is shown
    * pick ``texture`` and then the empty entry
    * verify the model holds the kind and then none, with no key left
    """
    field = ChoiceFieldTester("kind", choices=ASSET_KINDS)
    editor = field.make_editor(asset_model.bind(field)).editor
    assert isinstance(editor, SingleChoiceComboBox)
    qtbot.addWidget(editor)

    assert [editor.itemData(index) for index in range(editor.count())] == ["", *ASSET_KINDS]
    assert editor.currentIndex() == 0

    editor.setCurrentIndex(editor.findData("texture"))
    assert asset_model.kind == "texture"

    editor.setCurrentIndex(0)
    assert asset_model.kind is None
    assert "kind" not in asset_model.document.active_block


def test_choice_follows_the_model_and_a_stray_value_shows_blank(qtbot: QtBot, asset_model: RehuDocumentModel) -> None:
    """A change from elsewhere selects its entry; a stored value no choice names leaves the entry empty, as the viewer
    shows it.

    **Test steps:**

    * build the ``kind`` viewer and editor over an asset whose kind is one no choice names
    * verify the editor is on the empty entry
    * set ``model`` from elsewhere and verify the editor and the viewer follow
    """
    asset_model.kind = "spaceship"
    field = ChoiceFieldTester("kind", choices=ASSET_KINDS)
    viewer = field.make_viewer(asset_model.bind(field)).viewer
    editor = field.make_editor(asset_model.bind(field)).editor
    assert isinstance(viewer, QLabel)
    assert isinstance(editor, SingleChoiceComboBox)
    qtbot.addWidget(viewer)
    qtbot.addWidget(editor)
    assert editor.currentIndex() == 0

    asset_model.kind = "model"

    assert editor.currentData() == "model"
    assert viewer.text() == "model"
    asset_model.kind = None
    assert viewer.text() == ""
    assert editor.currentIndex() == 0


# endregion

# region Text with known values


def test_text_choice_offers_the_known_values_and_takes_any_text(qtbot: QtBot, asset_model: RehuDocumentModel) -> None:
    """The combo lists the known values and starts blank for an absent value; a typed text is written as it is, and
    clearing it removes the key.

    **Test steps:**

    * build the ``license`` editor over an asset with none
    * verify it offers the known licenses, blank
    * type a license no list names, then clear the line
    * verify the model holds that text and then nothing
    """
    field = TextChoiceFieldTester("license", choices=ASSET_LICENSES)
    viewer = field.make_viewer(asset_model.bind(field)).viewer
    editor = field.make_editor(asset_model.bind(field)).editor
    assert isinstance(viewer, QLabel)
    assert isinstance(editor, EditableChoiceComboBox)
    qtbot.addWidget(viewer)
    qtbot.addWidget(editor)
    assert [editor.itemText(index) for index in range(editor.count())] == list(ASSET_LICENSES)
    assert editor.currentText() == ""

    editor.setEditText("daz-interactive")
    assert asset_model.license == "daz-interactive"
    assert viewer.text() == "daz-interactive"

    editor.setEditText("")
    assert asset_model.license is None
    assert "license" not in asset_model.document.active_block


def test_text_choice_follows_the_model(qtbot: QtBot, asset_model: RehuDocumentModel) -> None:
    """A license set from elsewhere shows in the line.

    **Test steps:**

    * build the editor, then set the license on the model
    * verify the editor shows it, and is blank again once the license is cleared
    """
    field = TextChoiceFieldTester("license", choices=ASSET_LICENSES)
    editor = field.make_editor(asset_model.bind(field)).editor
    assert isinstance(editor, EditableChoiceComboBox)
    qtbot.addWidget(editor)

    asset_model.license = "cc-by-4.0"
    assert editor.currentText() == "cc-by-4.0"

    asset_model.license = None
    assert editor.currentText() == ""


# endregion

# region A map of text to text


def test_string_map_shows_one_line_per_entry_and_edits_the_table(qtbot: QtBot, asset_model: RehuDocumentModel) -> None:
    """The viewer lists ``key: value`` lines, and the editor is a table with the titles given, writing the map its rows
    make.

    **Test steps:**

    * build the ``compatibility`` viewer and editor over an asset working with two programs
    * verify the lines, the table's rows and its headers
    * add an entry through the model and verify the viewer and the table follow
    * edit a cell and verify the model holds the new version
    """
    asset_model.compatibility = {"unreal": "5.1-5.6", "blender": ">=4"}
    field = StringMapFieldTester("compatibility", key_title="Works with", value_title="Versions")
    viewer = field.make_viewer(asset_model.bind(field)).viewer
    editor = field.make_editor(asset_model.bind(field)).editor
    assert isinstance(viewer, QLabel)
    assert isinstance(editor, StringMapValueEditor)
    qtbot.addWidget(viewer)
    qtbot.addWidget(editor)
    assert viewer.text() == "unreal: 5.1-5.6\nblender: >=4"
    assert editor.value == {"unreal": "5.1-5.6", "blender": ">=4"}
    headers = [editor.model.headerData(column, Qt.Orientation.Horizontal) for column in (0, 1)]
    assert headers == ["Works with", "Versions"]

    asset_model.compatibility = {"unreal": "5.1-5.6", "blender": ">=4", "maya": "2024"}
    assert viewer.text().splitlines()[-1] == "maya: 2024"
    assert editor.value["maya"] == "2024"

    editor.model.setData(editor.model.index(1, 1), ">=4.2")
    assert asset_model.compatibility["blender"] == ">=4.2"


def test_string_map_keeps_a_row_still_waiting_for_its_key(qtbot: QtBot, asset_model: RehuDocumentModel) -> None:
    """A new row has no key yet, so it is no part of the map: the edit that adds it is not echoed back as a table to
    show, which would drop it while it is being filled.

    **Test steps:**

    * build the editor over an asset with one entry and insert a blank row
    * verify the model holds the one entry and the table still has two rows
    * give the row its key and verify the model holds both
    """
    asset_model.compatibility = {"unreal": "5.1"}
    field = StringMapFieldTester("compatibility")
    editor = field.make_editor(asset_model.bind(field)).editor
    assert isinstance(editor, StringMapValueEditor)
    qtbot.addWidget(editor)

    row = editor.model.insert(-1)  # type: ignore[attr-defined]  # the string map model

    assert asset_model.compatibility == {"unreal": "5.1"}
    assert editor.model.rowCount() == 2
    editor.model.setData(editor.model.index(row, 0), "blender")
    editor.model.setData(editor.model.index(row, 1), "4.2")
    assert asset_model.compatibility == {"unreal": "5.1", "blender": "4.2"}


def test_string_map_viewer_is_blank_for_an_empty_map(qtbot: QtBot, asset_model: RehuDocumentModel) -> None:
    """No entries read as no text.

    **Test steps:**

    * build the viewer over an asset with no compatibility
    * verify it is blank
    """
    field = StringMapFieldTester("compatibility")
    viewer = field.make_viewer(asset_model.bind(field)).viewer
    assert isinstance(viewer, QLabel)
    qtbot.addWidget(viewer)

    assert viewer.text() == ""


# endregion

# region A size


def test_size_shows_a_human_reading_with_the_exact_bytes_and_edits_whole_bytes(
    qtbot: QtBot, asset_model: RehuDocumentModel
) -> None:
    """The viewer reads the size as the other sizes are read, its tooltip the exact bytes; the editor holds the bytes,
    its readout beside them, and clearing it is unknown rather than zero.

    **Test steps:**

    * build the ``advertised_size`` viewer and editor over an asset with none
    * verify the viewer is blank with no tooltip
    * type a size in bytes into the editor
    * verify the model holds it and the viewer reads ``1.5K`` with the bytes as its tooltip
    * clear the editor and verify the model holds none
    """
    field = SizeFieldTester("advertised_size")
    viewer = field.make_viewer(asset_model.bind(field)).viewer
    editor = field.make_editor(asset_model.bind(field)).editor
    assert isinstance(viewer, QLabel)
    assert isinstance(editor, SizeEdit)
    qtbot.addWidget(viewer)
    qtbot.addWidget(editor)
    assert viewer.text() == ""
    assert viewer.toolTip() == ""

    editor.set_value(1536)  # type: ignore[attr-defined]  # the property's synthesized slot

    assert asset_model.advertised_size == 1536
    assert viewer.text() == "1.5K"
    assert viewer.toolTip() == "1,536 bytes"

    editor.set_value(None)  # type: ignore[attr-defined]  # the property's synthesized slot
    assert asset_model.advertised_size is None


def test_size_follows_the_model(qtbot: QtBot, asset_model: RehuDocumentModel) -> None:
    """A size set from elsewhere shows in the editor, a zero as a size.

    **Test steps:**

    * build the editor, then set the size to zero on the model
    * verify the editor holds ``0``
    """
    field = SizeFieldTester("advertised_size")
    editor = field.make_editor(asset_model.bind(field)).editor
    assert isinstance(editor, SizeEdit)
    qtbot.addWidget(editor)

    asset_model.advertised_size = 0

    assert editor.value == 0


# endregion

# region A date that keeps a time

ACQUIRED = "2024-05-03T12:34:56.789123Z"


def test_a_time_viewer_shows_local_time_and_a_date_as_stored(qtbot: QtBot, asset_model: RehuDocumentModel) -> None:
    """With a time kept, the viewer words a stored UTC time in local time, a partial date as stored, and nothing for
    none.

    **Test steps:**

    * build the ``acquired`` viewer over an asset with none, and verify it is blank
    * store a UTC time and verify the label is that moment in local time
    * store a date and verify it shows as stored
    """
    field = DateFieldTester("acquired", with_time=True)
    viewer = field.make_viewer(asset_model.bind(field)).viewer
    assert isinstance(viewer, QLabel)
    qtbot.addWidget(viewer)
    assert viewer.text() == ""

    asset_model.acquired = ACQUIRED
    local = datetime(2024, 5, 3, 12, 34, 56, tzinfo=UTC).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    assert viewer.text() == local

    asset_model.acquired = "2024-05"
    assert viewer.text() == "2024-05"


def test_a_plain_date_viewer_shows_a_time_as_stored(qtbot: QtBot, asset_model: RehuDocumentModel) -> None:
    """Without a time kept, a date field shows whatever is stored as it is.

    **Test steps:**

    * build a ``source_updated`` viewer over an asset holding a UTC time
    * verify the label is the stored text
    """
    asset_model.source_updated = ACQUIRED
    field = DateFieldTester("source_updated")
    viewer = field.make_viewer(asset_model.bind(field)).viewer
    assert isinstance(viewer, QLabel)
    qtbot.addWidget(viewer)

    assert viewer.text() == ACQUIRED


def test_a_time_editor_keeps_the_time_through_a_keystroke(qtbot: QtBot, asset_model: RehuDocumentModel) -> None:
    """Editing a stored time leaves it as it was until the text is a whole time or a date; it is never cut to a date
    by a key struck inside it.

    **Test steps:**

    * seed an asset with a UTC time and build the ``acquired`` editor
    * verify the editor holds it
    * erase a digit of the fraction, which is still a whole time, and verify it is kept to six digits
    * erase the ``Z``, which is no time at all, and verify the model still holds the last whole time
    * cut the text to a date and verify the model holds the date
    """
    asset_model.acquired = ACQUIRED
    field = DateFieldTester("acquired", with_time=True)
    editor = field.make_editor(asset_model.bind(field)).editor
    assert isinstance(editor, DateEdit)
    qtbot.addWidget(editor)
    assert editor.value == ACQUIRED

    line: QLineEdit = editor._DateEdit__line_edit  # type: ignore[attr-defined]  # pylint: disable=protected-access
    line.setText("2024-05-03T12:34:56.78912Z")
    assert asset_model.acquired == "2024-05-03T12:34:56.789120Z"

    line.setText("2024-05-03T12:34:56.78912")
    assert asset_model.acquired == "2024-05-03T12:34:56.789120Z"

    line.setText("2024-05-03")
    assert asset_model.acquired == "2024-05-03"


# endregion
