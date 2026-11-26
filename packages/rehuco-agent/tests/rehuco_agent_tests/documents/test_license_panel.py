"""Tests for the License panel (#688, #705, [[assets#licenses]]): the list of a record's licenses, what it shows of the
selected one's text, what each mode hands the document, and when it will not take an edit.

Real records under ``tmp_path``, opened the way a holder does; the panel's own widgets are reached through its
name-mangled members, as the other panel tests do.
"""

# astroid reads the panel's title-bar actions list as signals
# pylint: disable=protected-access,no-member

import datetime
from pathlib import Path
from typing import Final

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QKeySequence
from PySide6.QtWidgets import QLineEdit
from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.license_panel import READ_ONLY_HINT, UNREADABLE_HINT, LicensePanel
from rehuco_agent.documents.license_text_reader import LicenseTextReader
from rehuco_agent.documents.licenses_list_editor import LicensesListEditor
from rehuco_agent.documents.licenses_table_model import LICENSE_COLUMN, PRESET_URLS, URL_COLUMN
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.settings.description_editor_settings import shared_description_editor_settings
from rehuco_agent.settings.markdown_rendering_settings import shared_markdown_rendering_settings
from rehuco_core import (
    AssetLicense,
    LicenseTerms,
    LicenseTermsSet,
    LockReason,
    LockReasonKind,
    RehuDocument,
    license_terms_path,
    write_license_terms,
)

from .test_rehu_document_model_conflict import opened

pytestmark = mark.usefixtures("real_path_stat")

READ: Final = datetime.date(2026, 11, 18)
URL: Final = "https://example.com/eula"
TERMS: Final = LicenseTerms("Standard License", URL, READ, "# Terms\n\nUse **freely**.\n")
ID: Final = "fab-standard"
"""The license a record below is held under first."""
OTHER: Final = "fab-uefn-reference-only"
"""A second license some records below are held under too."""
OTHER_TERMS: Final = LicenseTerms("Reference only", URL, READ, "Reference only.")


def make_model(
    tmp_path: Path, terms: LicenseTerms | None = TERMS, licenses: tuple[AssetLicense, ...] = (AssetLicense(ID, URL),)
) -> RehuDocumentModel:
    """A document over an asset held under ``licenses``, with a ``.rehuterms`` beside it when given terms.

    :param tmp_path: the folder.
    :param terms: what the sidecar holds for :data:`ID`; none written for ``None``.
    :param licenses: the licenses the record holds.
    :returns: the model.
    """
    path = tmp_path / "info.rehu"
    document = RehuDocument.new(path)
    document.set_active_type("asset")
    document.title = "Pack"
    document.licenses = list(licenses)
    document.save()
    if terms is not None:
        write_license_terms(path, LicenseTermsSet({ID: terms}))
    return opened(path)


def held(model: RehuDocumentModel, license_id: str = ID) -> LicenseTerms | None:
    """The text a model holds for one license.

    :param model: the model.
    :param license_id: the license.
    :returns: its terms; ``None`` for none.
    """
    texts = model.license_terms
    return None if texts is None else texts.get(license_id)


def show(qtbot: QtBot, model: RehuDocumentModel) -> LicensePanel:
    """A shown panel over a document.

    :param qtbot: pytest-qt fixture.
    :param model: the document.
    :returns: the panel.
    """
    panel = LicensePanel(model)
    qtbot.addWidget(panel)
    panel.resize(400, 400)
    panel.show()
    return panel


def parts(panel: LicensePanel):  # type: ignore[no-untyped-def]
    """The panel's generated UI.

    :param panel: the panel.
    :returns: its widgets.
    """
    return panel._LicensePanel__ui  # type: ignore[attr-defined]


def list_of(panel: LicensePanel) -> LicensesListEditor:
    """The panel's list of licenses.

    :param panel: the panel.
    :returns: the list.
    """
    return panel._LicensePanel__list  # type: ignore[attr-defined]


def rows_of(panel: LicensePanel) -> list[list[str]]:
    """What the list's rows show, cell by cell.

    :param panel: the panel.
    :returns: each row's cells.
    """
    model = list_of(panel).licenses
    return [[model.index(row, column).data() for column in range(model.columnCount())] for row in range(model.count)]


def editor_of(panel: LicensePanel):  # type: ignore[no-untyped-def]
    """The panel's Markdown editor.

    :param panel: the panel.
    :returns: the editor.
    """
    return panel._LicensePanel__editor  # type: ignore[attr-defined]


@fixture(name="reads", autouse=True)
def fixture_reads(mocker: MockerFixture) -> list[tuple[str, str]]:
    """No text is read from the web: each read asked for is recorded instead.

    :param mocker: pytest-mock fixture.
    :returns: the reads asked for, as ``(license id, url)``.
    """
    asked: list[tuple[str, str]] = []
    mocker.patch.object(LicenseTextReader, "read", lambda _self, license_id, url: asked.append((license_id, url)))
    return asked


def reader_of(panel: LicensePanel) -> LicenseTextReader:
    """The reader of preset texts the panel's list holds.

    :param panel: the panel.
    :returns: the reader.
    """
    return list_of(panel)._LicensesListEditor__reader  # type: ignore[attr-defined]


@fixture(name="panel")
def fixture_panel(qtbot: QtBot, tmp_path: Path) -> LicensePanel:
    """A shown panel over a record with a license text.

    :param qtbot: pytest-qt fixture.
    :param tmp_path: the folder.
    :returns: the panel.
    """
    return show(qtbot, make_model(tmp_path))


# region reading


def test_the_terms_are_read_as_rendered_markdown_under_their_title_and_where_they_came_from(
    panel: LicensePanel,
) -> None:
    """The title, a line naming the day and the address as a link, and the terms rendered.

    **Test steps:**

    * open the panel over a record with a license text
    * verify the title, the line with its link and day, the rendered text without its Markdown marks, and that the
      viewer, not the editor, is on show
    """
    ui = parts(panel)

    assert ui.title_label.text() == "Standard License"
    assert ui.info_label.text() == f'Read 2026-11-18 from <a href="{URL}">{URL}</a>.'
    assert "Use freely." in ui.text_view.toPlainText()
    assert "**" not in ui.text_view.toPlainText()
    assert ui.text_stack.currentIndex() == 0
    assert not panel.editing


def test_an_address_that_is_no_web_page_is_text_and_not_a_link(qtbot: QtBot, tmp_path: Path) -> None:
    """The text is outside input, so only a web address is a link.

    **Test steps:**

    * open a record whose terms name a file address
    * verify the line shows it as text, with no anchor
    """
    model = make_model(tmp_path, LicenseTerms("Odd", "file:///c:/windows", READ, "Text"))

    panel = show(qtbot, model)

    assert parts(panel).info_label.text() == "Read 2026-11-18 from file:///c:/windows."


def test_terms_written_for_the_item_say_so(qtbot: QtBot, tmp_path: Path) -> None:
    """No address is terms of the item's own, which nothing refreshes.

    **Test steps:**

    * open a record whose terms have no url
    * verify the line says they were written for the item, on their day
    """
    panel = show(qtbot, make_model(tmp_path, LicenseTerms("Mine", None, READ, "Text")))

    assert parts(panel).info_label.text() == "Written for this item, 2026-11-18."


def test_a_license_with_no_text_shows_nothing_more_than_its_row(qtbot: QtBot, tmp_path: Path) -> None:
    """The empty view says there is no text: no line says so again (#705).

    **Test steps:**

    * open a record holding a license with no text
    * verify the line under the title is hidden and empty, the title is empty, the viewer shows nothing, and the text
      can be written
    """
    panel = show(qtbot, make_model(tmp_path, None))

    ui = parts(panel)
    assert ui.info_label.text() == ""
    assert ui.info_label.isHidden()
    assert ui.title_label.text() == ""
    assert ui.text_view.toPlainText() == ""
    assert ui.edit_action.isEnabled()


def test_a_sidecar_that_cannot_be_read_is_named_and_blocks_editing(qtbot: QtBot, tmp_path: Path) -> None:
    """The reason is shown with the way out, and nothing can be typed over a file that cannot be read.

    **Test steps:**

    * open a record whose sidecar has no header
    * verify the line names the file and says how to fix it, and *Edit* and the editor are disabled
    """
    model = make_model(tmp_path, None)
    license_terms_path(model.path).write_text("no header", encoding="utf-8")  # type: ignore[arg-type]
    model.revert()
    qtbot.waitUntil(lambda: model.reading is None)

    panel = show(qtbot, model)

    ui = parts(panel)
    assert "info.rehuterms:" in ui.info_label.text()
    assert ui.info_label.text().endswith(UNREADABLE_HINT.strip())
    assert not ui.edit_action.isEnabled()
    assert not editor_of(panel).isEnabled()


def test_a_locked_document_shows_the_terms_and_cannot_edit_them(qtbot: QtBot, tmp_path: Path) -> None:
    """**Test steps:**

    * open a document that is locked and holds license text
    * verify the terms show, with the line saying they cannot be edited, and *Edit* is disabled
    """
    model = make_model(tmp_path)
    model.lock_reasons = [LockReason(LockReasonKind.INVALID_FIELD, "a field is wrong")]

    panel = show(qtbot, model)

    ui = parts(panel)
    assert ui.info_label.text().endswith(READ_ONLY_HINT.strip())
    assert "Use freely." in ui.text_view.toPlainText()
    assert not ui.edit_action.isEnabled()


def test_a_document_with_no_file_of_its_own_cannot_edit_its_terms_either(qtbot: QtBot) -> None:
    """**Test steps:**

    * open a document bound to no path, holding license text
    * verify the terms show and *Edit* is disabled
    """
    model = RehuDocumentModel.create_new(None)
    model.resource_type = "asset"
    model.licenses = [AssetLicense(ID)]
    model.license_terms = LicenseTermsSet({ID: TERMS})

    panel = show(qtbot, model)

    assert "Use freely." in parts(panel).text_view.toPlainText()
    assert not parts(panel).edit_action.isEnabled()


# endregion

# region the list of licenses


def test_the_list_shows_each_license_and_the_first_is_selected(qtbot: QtBot, tmp_path: Path) -> None:
    """One row per license, its id and the address of its terms, in the record's order, at the top of the panel; the
    first is the one shown, under its text's title.

    **Test steps:**

    * open a record holding two licenses, a text saved for the first only
    * verify the list is the panel's first widget, the rows, that the first is selected, and the text shown is its
    """
    panel = show(qtbot, make_model(tmp_path, licenses=(AssetLicense(ID, URL), AssetLicense(OTHER))))

    model = list_of(panel).licenses
    assert parts(panel).main_layout.itemAt(0).widget() is list_of(panel)
    assert rows_of(panel) == [[ID, URL], [OTHER, ""]]
    headers = [model.headerData(column, Qt.Orientation.Horizontal) for column in range(model.columnCount())]
    assert headers == ["License", "URL"]
    assert panel.selected == ID
    assert parts(panel).title_label.text() == "Standard License"


def test_selecting_a_license_shows_its_text(qtbot: QtBot, tmp_path: Path) -> None:
    """**Test steps:**

    * open a record holding two licenses, each with its text, and select the second row
    * verify the title, the line and the viewer are the second's, and typing edits the second's text alone
    """
    model = make_model(tmp_path, licenses=(AssetLicense(ID, URL), AssetLicense(OTHER, URL)))
    write_license_terms(model.path, LicenseTermsSet({ID: TERMS, OTHER: OTHER_TERMS}))  # type: ignore[arg-type]
    model.revert()
    qtbot.waitUntil(lambda: model.reading is None)
    panel = show(qtbot, model)
    ui = parts(panel)

    list_of(panel).set_current_index(1)

    assert panel.selected == OTHER
    assert ui.title_label.text() == "Reference only"
    assert ui.text_view.toPlainText() == "Reference only."
    ui.edit_action.setChecked(True)
    editor_of(panel).setText("Typed")
    assert held(model) == TERMS
    typed = held(model, OTHER)
    assert typed is not None and typed.text == "Typed"


def test_a_record_with_no_license_has_nothing_to_show_or_type_into(qtbot: QtBot, tmp_path: Path) -> None:
    """**Test steps:**

    * open a record holding no license
    * verify the list is empty, nothing is selected, and the editor takes no typing
    """
    panel = show(qtbot, make_model(tmp_path, None, licenses=()))

    assert list_of(panel).licenses.count == 0
    assert panel.selected is None
    assert not editor_of(panel).isEnabled()


def test_the_selection_follows_the_record_s_licenses(qtbot: QtBot, tmp_path: Path) -> None:
    """A license still held stays selected wherever it moved; one that is gone gives way to the first.

    **Test steps:**

    * select the second of two licenses, then put it first
    * verify it is still the one selected
    * drop it and verify the remaining one is selected
    * drop that too and verify nothing is
    """
    model = make_model(tmp_path, licenses=(AssetLicense(ID, URL), AssetLicense(OTHER)))
    panel = show(qtbot, model)
    list_of(panel).set_current_index(1)

    model.licenses = [AssetLicense(OTHER), AssetLicense(ID, URL)]
    assert panel.selected == OTHER
    model.licenses = [AssetLicense(ID, URL)]
    assert panel.selected == ID
    model.licenses = []
    assert panel.selected is None


def test_the_list_grows_with_its_rows_and_never_scrolls(qtbot: QtBot, tmp_path: Path) -> None:
    """**Test steps:**

    * open a record holding one license, then give it two more
    * verify the list never shows a vertical scroll bar and asks for more height with more rows
    """
    model = make_model(tmp_path)
    panel = show(qtbot, model)
    view = list_of(panel).view
    one = view.sizeHint().height()

    model.licenses = [AssetLicense(ID, URL), AssetLicense(OTHER), AssetLicense("cc-by-4.0")]

    assert view.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert view.sizeHint().height() > one


# endregion

# region editing


@mark.parametrize("editing", [False, True])
def test_the_text_takes_all_the_height_the_list_the_title_and_the_line_leave(
    qtbot: QtBot, tmp_path: Path, editing: bool
) -> None:
    """The list, the title and the line under it keep their own height, and the terms, read or edited, get the rest.

    **Test steps:**

    * show the panel tall, reading and then editing
    * verify the list and the title are no taller than their hints and the text's part fills what is left
    """
    panel = show(qtbot, make_model(tmp_path))
    panel.resize(500, 700)
    panel.set_editing(editing)
    ui = parts(panel)

    qtbot.waitUntil(lambda: ui.text_stack.height() > 500)

    assert ui.title_label.height() <= ui.title_label.sizeHint().height()
    assert list_of(panel).height() <= list_of(panel).sizeHint().height()


def test_edit_makes_the_list_editable_and_swaps_the_viewer_for_the_editor_and_back(panel: LicensePanel) -> None:
    """The title shows above the rendered terms only (#705).

    **Test steps:**

    * verify that reading, the list takes no edit and shows no add or delete, and the title shows
    * toggle *Edit* and verify the list is editable with its add and delete shown, the title is hidden, and the editor
      shows holding the terms' text
    * toggle it back and verify the viewer, the title and the read-only list again
    """
    ui = parts(panel)
    editor = list_of(panel)
    assert not editor.licenses.editable
    assert editor.item_actions.isHidden()
    assert ui.title_label.isVisible()

    ui.edit_action.setChecked(True)

    assert panel.editing
    assert editor.licenses.editable
    assert editor.item_actions.isVisible()
    assert not ui.title_label.isVisible()
    assert ui.text_stack.currentIndex() == 1
    assert editor_of(panel).getText(100).data().decode().startswith("# Terms")

    ui.edit_action.setChecked(False)

    assert ui.text_stack.currentIndex() == 0
    assert ui.title_label.isVisible()
    assert not editor.licenses.editable


def test_typing_in_the_editor_edits_the_document_and_the_viewer_catches_up_on_leaving(
    panel: LicensePanel,
) -> None:
    """The text goes through at once, as the document's own detail, while the viewer waits for the editing to end.

    **Test steps:**

    * edit, and replace the editor's text
    * verify the document holds it and is dirty, and the viewer still shows the old text
    * leave edit and verify the viewer renders the new text
    """
    ui = parts(panel)
    model = panel._LicensePanel__model  # type: ignore[attr-defined]
    ui.edit_action.setChecked(True)

    editor_of(panel).setText("New **terms**")

    typed = held(model)
    assert typed is not None and typed.text == "New **terms**"
    assert model.dirty
    assert "Use freely." in ui.text_view.toPlainText()
    ui.edit_action.setChecked(False)
    assert ui.text_view.toPlainText() == "New terms"


def test_text_typed_into_a_license_with_none_is_titled_by_its_id(qtbot: QtBot, tmp_path: Path) -> None:
    """The terms the document makes are shown back under the title it chose.

    **Test steps:**

    * open a record with none, edit, type a text, and leave editing
    * verify the document made terms with no url, titled by the license's id, the title above the terms shows it, and
      the line below says they were written for the item
    """
    model = make_model(tmp_path, None)
    panel = show(qtbot, model)
    ui = parts(panel)
    ui.edit_action.setChecked(True)

    editor_of(panel).setText("Mine")

    ui.edit_action.setChecked(False)

    made = held(model)
    assert made is not None and made.url is None and made.title == ID
    assert ui.title_label.text() == ID
    assert ui.info_label.text().startswith("Written for this item")


def test_a_revert_puts_the_files_text_back_in_the_editors_without_an_edit(panel: LicensePanel, qtbot: QtBot) -> None:
    """What the document takes back from the file is shown in the editors without being typed again.

    **Test steps:**

    * edit the text in the editor and revert the document
    * verify the editor holds the file's text again, the document its terms, and it is clean
    """
    ui = parts(panel)
    model = panel._LicensePanel__model  # type: ignore[attr-defined]
    ui.edit_action.setChecked(True)
    editor_of(panel).setText("Typed")

    model.revert()
    qtbot.waitUntil(lambda: model.reading is None and not model.dirty)

    assert editor_of(panel).getText(100).data().decode().startswith("# Terms")
    assert held(model) == TERMS
    assert not model.dirty


def test_the_document_becoming_unwritable_ends_the_editing(panel: LicensePanel) -> None:
    """**Test steps:**

    * edit, then give the document a sidecar that cannot be read, as a revert would
    * verify the editors are left and disabled
    """
    ui = parts(panel)
    model = panel._LicensePanel__model  # type: ignore[attr-defined]
    ui.edit_action.setChecked(True)

    model.license_unreadable = "info.rehuterms: broken."

    assert not panel.editing
    assert not ui.edit_action.isEnabled()
    assert not editor_of(panel).isEnabled()


# endregion

# region the key, the links, the state and the settings


def test_f2_is_the_edit_actions_key(panel: LicensePanel) -> None:
    """**Test steps:**

    * verify the *Edit* action carries F2, and is the title bar's one action
    """
    action = panel.title_bar_actions[0]

    assert action.shortcut() == QKeySequence("F2")
    assert panel.title_bar_actions == [parts(panel).edit_action]


@mark.parametrize(("href", "opened"), [("https://example.com/", True), ("file:///c:/windows", False), ("x", False)])
def test_only_a_web_page_link_is_opened(panel: LicensePanel, mocker: MockerFixture, href: str, opened: bool) -> None:
    """The text is outside input: a link in the terms, or the line's own, opens a web page and nothing else.

    **Test steps:**

    * activate a link in the line and one in the rendered terms
    * verify each reached the desktop services only for a web page
    """
    spy = mocker.patch.object(QDesktopServices, "openUrl")

    parts(panel).info_label.linkActivated.emit(href)
    parts(panel).text_view.anchorClicked.emit(QUrl(href))

    assert spy.call_count == (2 if opened else 0)


def test_the_editing_state_is_saved_and_restored_and_a_bad_blob_changes_nothing(qtbot: QtBot, tmp_path: Path) -> None:
    """**Test steps:**

    * edit in one panel and save its state
    * restore it into a panel over another record and verify it edits
    * restore junk and a blob without the key, and verify nothing changed
    """
    first = show(qtbot, make_model(tmp_path))
    parts(first).edit_action.setChecked(True)
    state = first.save_state()
    other = tmp_path / "other"
    other.mkdir()
    second = show(qtbot, make_model(other))

    second.restore_state(b"\xa1")
    second.restore_state(b"\xa0")
    assert not second.editing
    second.restore_state(state)

    assert second.editing


def test_a_document_that_cannot_be_edited_is_not_restored_into_editing(qtbot: QtBot, tmp_path: Path) -> None:
    """**Test steps:**

    * restore an editing state into a panel over a document with an unreadable sidecar
    * verify the panel shows the viewer
    """
    model = make_model(tmp_path, None)
    model.license_unreadable = "info.rehuterms: broken."
    panel = show(qtbot, model)

    panel.restore_state(b"\xa1\x67editing\xf5")

    assert not panel.editing


def test_the_settings_of_the_description_are_followed(panel: LicensePanel) -> None:
    """The terms are rendered and edited as the description is, and follow a saved change at once.

    **Test steps:**

    * change the description editor's line numbers, then its rendering's engine, and announce both
    * verify the editor follows the first and the viewer renders with the second
    """
    editing = shared_description_editor_settings()
    editing.show_line_numbers = False
    rendering = shared_markdown_rendering_settings()
    rendering.engine = "mistletoe"

    assert editor_of(panel).line_numbers is False
    assert "Use freely." in parts(panel).text_view.toPlainText()


def test_a_detached_panel_follows_nothing(panel: LicensePanel) -> None:
    """**Test steps:**

    * detach the panel and give the document other terms
    * verify the panel still shows the old ones, and a setting changed meanwhile reaches no editor
    """
    model = panel._LicensePanel__model  # type: ignore[attr-defined]
    panel.detach()

    model.license_terms = LicenseTermsSet({ID: LicenseTerms("Other", None, READ, "Other")})
    shared_description_editor_settings().show_line_numbers = False

    assert parts(panel).title_label.text() == "Standard License"
    assert editor_of(panel).line_numbers is True


# endregion


def test_text_reaching_the_editors_with_no_license_selected_writes_nothing(qtbot: QtBot, tmp_path: Path) -> None:
    """With no license there is nothing a text could belong to (#705).

    **Test steps:**

    * open a record holding no license, and put a text in the editor as typing would
    * verify the document holds no text and is clean
    """
    model = make_model(tmp_path, None, licenses=())
    panel = show(qtbot, model)

    editor_of(panel).setText("Typed")

    assert model.license_terms is None
    assert not model.dirty


# region adding, retyping and deleting licenses


def test_a_license_added_in_the_list_is_the_records_once_it_has_an_id_and_then_takes_a_text(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """A record with none can be given one in the dock (#705): the row added is selected, and its text can be typed
    once it has an id.

    **Test steps:**

    * open a record holding no license, edit, and add a row
    * verify the row is selected, the record still holds no license, and the editor takes no typing
    * give the row an id and a URL
    * verify the record holds the license, the row is the one shown, and a text typed is its
    """
    model = make_model(tmp_path, None, licenses=())
    panel = show(qtbot, model)
    parts(panel).edit_action.setChecked(True)
    editor = list_of(panel)

    editor.item_actions.insert_action.trigger()

    assert editor.current_index == 0
    assert model.licenses == []
    assert not editor_of(panel).isEnabled()
    rows = editor.licenses
    assert rows.setData(rows.index(0, LICENSE_COLUMN), ID)
    assert rows.setData(rows.index(0, URL_COLUMN), URL)
    assert model.licenses == [AssetLicense(ID, URL)]
    assert panel.selected == ID
    assert editor_of(panel).isEnabled()
    editor_of(panel).setText("Mine")
    typed = held(model)
    assert typed is not None and typed.text == "Mine"


def test_picking_another_preset_shows_it_with_the_text_read_for_it(
    panel: LicensePanel, reads: list[tuple[str, str]]
) -> None:
    """**Test steps:**

    * edit, and give the selected license another preset
    * verify it is still the one shown, under the new id, with no text, and the preset's text was asked for
    * hand the panel the text read, and verify the license shows it
    """
    model = panel._LicensePanel__model  # type: ignore[attr-defined]
    parts(panel).edit_action.setChecked(True)
    rows = list_of(panel).licenses
    url = PRESET_URLS["cc-by-4.0"]

    assert rows.setData(rows.index(0, LICENSE_COLUMN), "cc-by-4.0")

    assert panel.selected == "cc-by-4.0"
    assert model.license_terms == LicenseTermsSet()
    assert reads == [("cc-by-4.0", url)]
    read = LicenseTerms("CC BY 4.0", url, READ, "Attribution.")
    reader_of(panel).text_read.emit("cc-by-4.0", url, read)
    assert held(model, "cc-by-4.0") == read
    assert editor_of(panel).getText(100).data().decode() == "Attribution."


def test_a_text_read_for_a_license_replaced_meanwhile_is_not_kept(panel: LicensePanel) -> None:
    """A text read slowly must not land on a license picked again since.

    **Test steps:**

    * hand the panel a text read for a license the record does not hold, and one for its license at another address
    * verify the record's texts are as they were
    """
    model = panel._LicensePanel__model  # type: ignore[attr-defined]
    read = LicenseTerms("Other", "https://example.com/other", READ, "Other.")

    reader_of(panel).text_read.emit("cc-by-4.0", PRESET_URLS["cc-by-4.0"], read)
    reader_of(panel).text_read.emit(ID, "https://example.com/other", read)

    assert model.license_terms == LicenseTermsSet({ID: TERMS})
    assert not model.dirty


def test_deleting_the_selected_license_shows_the_next_one(qtbot: QtBot, tmp_path: Path) -> None:
    """**Test steps:**

    * open a record holding two licenses, edit, and delete the first
    * verify the record holds the second alone, with the first's text gone, and the second is shown
    """
    model = make_model(tmp_path, licenses=(AssetLicense(ID, URL), AssetLicense(OTHER)))
    panel = show(qtbot, model)
    parts(panel).edit_action.setChecked(True)

    list_of(panel).item_actions.delete_action.trigger()

    assert model.licenses == [AssetLicense(OTHER)]
    assert held(model) is None
    assert panel.selected == OTHER


def test_leaving_edit_writes_a_cell_being_typed_into(panel: LicensePanel, qtbot: QtBot) -> None:
    """An id or a URL being typed when the editing ends is kept, not dropped with the cell.

    **Test steps:**

    * edit, open the selected license's URL cell and type into it
    * leave edit and verify the record holds the URL typed and the cell is closed
    """
    model = panel._LicensePanel__model  # type: ignore[attr-defined]
    parts(panel).edit_action.setChecked(True)
    view = list_of(panel).view
    cell = view.model().index(0, URL_COLUMN)
    view.setCurrentIndex(cell)
    view.edit(cell)
    line = view.indexWidget(cell)
    assert isinstance(line, QLineEdit)
    line.selectAll()
    qtbot.keyClicks(line, "https://example.com/other")

    parts(panel).edit_action.setChecked(False)

    assert model.licenses == [AssetLicense(ID, "https://example.com/other")]
    assert view.indexWidget(cell) is None


# endregion
