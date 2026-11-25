"""Tests for the License panel (#688, [[assets#licenses]]): what it shows of a record's license text, what each mode
hands the document, and when it will not take an edit.

Real records under ``tmp_path``, opened the way a holder does; the panel's own widgets are reached through its
name-mangled members, as the other panel tests do.
"""

# astroid reads the panel's title-bar actions list as signals
# pylint: disable=protected-access,no-member

import datetime
from pathlib import Path
from typing import Final

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QKeySequence
from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.license_panel import (
    NO_TERMS_TEXT,
    READ_ONLY_HINT,
    UNREADABLE_HINT,
    WRITE_HINT,
    LicensePanel,
)
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.settings.description_editor_settings import shared_description_editor_settings
from rehuco_agent.settings.markdown_rendering_settings import shared_markdown_rendering_settings
from rehuco_core import LicenseTerms, LockReason, LockReasonKind, license_terms_path, write_license_terms

from .test_rehu_document_model_conflict import opened, write_record

pytestmark = mark.usefixtures("real_path_stat")

READ: Final = datetime.date(2026, 11, 18)
URL: Final = "https://example.com/eula"
TERMS: Final = LicenseTerms("Standard License", URL, READ, "# Terms\n\nUse **freely**.\n")


def make_model(tmp_path: Path, terms: LicenseTerms | None = TERMS) -> RehuDocumentModel:
    """A document over a record, with a ``.rehuterms`` beside it when given terms.

    :param tmp_path: the folder.
    :param terms: what the sidecar holds; none written for ``None``.
    :returns: the model.
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Pack")
    if terms is not None:
        write_license_terms(path, terms)
    return opened(path)


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


def editor_of(panel: LicensePanel):  # type: ignore[no-untyped-def]
    """The panel's Markdown editor.

    :param panel: the panel.
    :returns: the editor.
    """
    return panel._LicensePanel__editor  # type: ignore[attr-defined]


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
    assert (ui.title_stack.currentIndex(), ui.text_stack.currentIndex()) == (0, 0)
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


def test_a_record_with_none_says_so_and_offers_writing_them(qtbot: QtBot, tmp_path: Path) -> None:
    """**Test steps:**

    * open a record with no license text
    * verify the line says none is saved and offers writing them, the title is empty and the viewer shows nothing
    * edit and verify the line offers it no more, then leave and verify it does again
    """
    panel = show(qtbot, make_model(tmp_path, None))

    ui = parts(panel)
    assert ui.info_label.text() == NO_TERMS_TEXT + WRITE_HINT
    assert ui.title_label.text() == ""
    assert ui.text_view.toPlainText() == ""
    assert ui.edit_action.isEnabled()

    ui.edit_action.setChecked(True)
    assert ui.info_label.text() == NO_TERMS_TEXT
    ui.edit_action.setChecked(False)
    assert ui.info_label.text() == NO_TERMS_TEXT + WRITE_HINT


def test_a_sidecar_that_cannot_be_read_is_named_and_blocks_editing(qtbot: QtBot, tmp_path: Path) -> None:
    """The reason is shown with the way out, and nothing can be typed over a file that cannot be read.

    **Test steps:**

    * open a record whose sidecar has no header
    * verify the line names the file and says how to fix it, and *Edit* and both editors are disabled
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
    assert not ui.title_edit.isEnabled()
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
    model.license_terms = TERMS

    panel = show(qtbot, model)

    assert "Use freely." in parts(panel).text_view.toPlainText()
    assert not parts(panel).edit_action.isEnabled()


# endregion

# region editing


@mark.parametrize("editing", [False, True])
def test_the_text_takes_all_the_height_the_title_and_the_line_leave(
    qtbot: QtBot, tmp_path: Path, editing: bool
) -> None:
    """The title and the line under it keep their own height, and the terms, read or edited, get the rest.

    **Test steps:**

    * show the panel tall over a record with no text, reading and then editing
    * verify the title is no taller than its hint and the text's part fills what is left
    """
    panel = show(qtbot, make_model(tmp_path, None))
    panel.resize(500, 700)
    panel.set_editing(editing)
    ui = parts(panel)

    qtbot.waitUntil(lambda: ui.text_stack.height() > 500)

    assert ui.title_stack.height() <= ui.title_stack.sizeHint().height()


def test_edit_swaps_the_viewer_for_a_title_line_and_the_editor_and_back(panel: LicensePanel) -> None:
    """**Test steps:**

    * toggle *Edit* and verify both stacks show the editors, holding the terms' title and text
    * toggle it back and verify the viewer shows again
    """
    ui = parts(panel)
    ui.edit_action.setChecked(True)

    assert panel.editing
    assert (ui.title_stack.currentIndex(), ui.text_stack.currentIndex()) == (1, 1)
    assert ui.title_edit.text() == "Standard License"
    assert editor_of(panel).getText(100).data().decode().startswith("# Terms")

    ui.edit_action.setChecked(False)

    assert (ui.title_stack.currentIndex(), ui.text_stack.currentIndex()) == (0, 0)


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

    assert model.license_terms is not None and model.license_terms.text == "New **terms**"
    assert model.dirty
    assert "Use freely." in ui.text_view.toPlainText()
    ui.edit_action.setChecked(False)
    assert ui.text_view.toPlainText() == "New terms"


def test_typing_a_title_edits_the_document(panel: LicensePanel, qtbot: QtBot) -> None:
    """**Test steps:**

    * edit, select the title and type another
    * verify the document holds it and the url and day it had
    """
    ui = parts(panel)
    model = panel._LicensePanel__model  # type: ignore[attr-defined]
    ui.edit_action.setChecked(True)
    ui.title_edit.selectAll()

    qtbot.keyClicks(ui.title_edit, "Mine")

    assert model.license_terms == LicenseTerms("Mine", URL, READ, TERMS.text)


def test_text_typed_into_a_record_with_none_gives_the_title_line_its_default(qtbot: QtBot, tmp_path: Path) -> None:
    """The terms the document makes are shown back: the title it chose appears in the line it was not typed in.

    **Test steps:**

    * open a record with none, edit, and type a text
    * verify the document made terms with no url, the title line shows their title, and the line below says they
      were written for the item
    """
    model = make_model(tmp_path, None)
    model.license = "fab-standard"
    panel = show(qtbot, model)
    ui = parts(panel)
    ui.edit_action.setChecked(True)

    editor_of(panel).setText("Mine")

    assert model.license_terms is not None and model.license_terms.url is None
    assert ui.title_edit.text() == "fab-standard"
    assert ui.info_label.text().startswith("Written for this item")


def test_a_revert_puts_the_files_text_back_in_the_editors_without_an_edit(panel: LicensePanel, qtbot: QtBot) -> None:
    """What the document takes back from the file is shown in the editors without being typed again.

    **Test steps:**

    * edit the text in the editor and revert the document
    * verify the editor and the title line hold the file's again and the document is clean
    """
    ui = parts(panel)
    model = panel._LicensePanel__model  # type: ignore[attr-defined]
    ui.edit_action.setChecked(True)
    editor_of(panel).setText("Typed")

    model.revert()
    qtbot.waitUntil(lambda: model.reading is None and not model.dirty)

    assert editor_of(panel).getText(100).data().decode().startswith("# Terms")
    assert ui.title_edit.text() == "Standard License"
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

    model.license_terms = LicenseTerms("Other", None, READ, "Other")
    shared_description_editor_settings().show_line_numbers = False

    assert parts(panel).title_label.text() == "Standard License"
    assert editor_of(panel).line_numbers is True


# endregion
