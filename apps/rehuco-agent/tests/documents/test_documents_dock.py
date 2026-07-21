"""Tests for DocumentsDock: one dock per open `.rehu`, focus-and-reuse by path."""

# the dock owns a broad surface (open/reuse-by-path, dock titles, focus tracking, close guards,
# close_all/close_missing, folder/archive companions); its test suite is correspondingly long --
# one cohesive module reads better than an arbitrary split, so the module-length cap is lifted
# here rather than fragmenting it.
# pylint: disable=too-many-lines

import json
from pathlib import Path
from typing import Any, Final

import PySide6QtAds as QtAds
from borco_pyside.qtads import tab_label
from PySide6.QtWidgets import QDialog, QMessageBox
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents import documents_dock
from rehuco_agent.documents.documents_dock import DIRTY_DOCK_MARKER, LOCKED_DOCK_MARKER, DocumentsDock
from rehuco_agent.settings.identity_settings import IdentitySettings
from rehuco_core import CURRENT_FORMAT_VERSION, LockReasonKind, RehuDocument

FAKE_PATH: Final = Path.cwd() / "fake" / "tutorials" / "sculpting" / "info.rehu"
"""``open_document`` asserts an absolute path; built from ``Path.cwd()`` so it's absolute on every
platform (unlike a hardcoded ``/fake/...``, which isn't absolute on Windows without a drive)."""
FAKE_LABEL: Final = f"{FAKE_PATH.parent.name}/"
"""``FAKE_PATH``'s expected dock-title label: an ``info.rehu``'s parent directory name, trailing-slashed."""
OTHER_PATH: Final = Path.cwd() / "fake" / "tutorials" / "painting" / "info.rehu"
THIRD_PATH: Final = Path.cwd() / "fake" / "tutorials" / "drawing" / "info.rehu"
FAKE_ARCHIVE_PATH: Final = Path.cwd() / "fake" / "tutorials" / "sculpting.zip"
"""An archive whose ``.rehu`` companion (#43) is ``FAKE_ARCHIVE_PATH.with_suffix(".rehu")``."""
FAKE_ARCHIVE_INFO_PATH: Final = FAKE_ARCHIVE_PATH.with_suffix(".rehu")

TUTORIAL: Final = {
    "format_version": 1,
    "type": "Tutorial",
    "sources": [{"title": "Foo", "publisher": "Bar", "url": "https://example.com", "primary": True}],
}

TC_TUTORIAL: Final = """
type: Tutorial
title: Legacy Title
publisher: Legacy Publisher
url: https://legacy.example/foo
"""
"""A legacy tc4 ``.tc`` (YAML) fixture, shaped like Phase 1's ``TUTORIAL_TC``
([[acquisition-tooling#tc-to-rehu]]) -- opens through :func:`rehuco_core.load_tc` instead of
``RehuDocument.load``."""


def load_document(mocker: MockerFixture, data: dict[str, Any] | None = None) -> None:
    """Mock the filesystem so ``RehuDocument.load`` serves ``data`` (defaults to :data:`TUTORIAL`).

    :param mocker: pytest-mock fixture.
    :param data: document JSON to serve; defaults to :data:`TUTORIAL`.
    """
    mocker.patch.object(Path, "read_text", return_value=json.dumps(data if data is not None else TUTORIAL))


def dock_for(dock: DocumentsDock, widget: object) -> QtAds.CDockWidget:
    """Return the ``CDockWidget`` wrapping ``widget`` (reaches into the private map by design --
    :class:`DocumentsDock` doesn't expose docks, only :meth:`open_document`'s widget).

    :param dock: the documents dock to search.
    :param widget: the document widget to find the wrapping dock for.
    :returns: the matching ``CDockWidget``.
    """
    docks = dock._DocumentsDock__document_docks  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    return next(d for d, w in docks.items() if w is widget)


def test_opening_a_path_adds_one_dock(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Opening a path creates exactly one document dock.

    **Test steps:**

    * mock the filesystem to serve the tutorial fixture
    * open the fake path
    * verify the internal dock map holds exactly one entry
    """
    load_document(mocker)
    dock = DocumentsDock()
    qtbot.addWidget(dock)

    dock.open_document(FAKE_PATH)

    assert len(dock._DocumentsDock__document_docks) == 1  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def test_reopening_the_same_path_focuses_the_existing_dock(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Opening an already-open path reuses and focuses its dock rather than adding a second one.

    **Test steps:**

    * open the fake path twice
    * verify only one dock exists and the same widget is returned both times
    """
    load_document(mocker)
    dock = DocumentsDock()
    qtbot.addWidget(dock)

    first = dock.open_document(FAKE_PATH)
    second = dock.open_document(FAKE_PATH)

    assert first is second
    assert len(dock._DocumentsDock__document_docks) == 1  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def test_opening_a_different_path_adds_a_second_dock(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Opening a distinct path adds a second dock alongside the first.

    **Test steps:**

    * open two distinct fake paths
    * verify two docks now exist, holding two distinct widgets
    """
    load_document(mocker)
    dock = DocumentsDock()
    qtbot.addWidget(dock)

    first = dock.open_document(FAKE_PATH)
    second = dock.open_document(OTHER_PATH)

    assert first is not second
    assert len(dock._DocumentsDock__document_docks) == 2  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def test_dock_title_reflects_the_dirty_flag(mocker: MockerFixture, qtbot: QtBot) -> None:
    """The dock's tab title gains a leading marker while the document is dirty, and loses it on save.

    ``FAKE_PATH`` is an ``info.rehu``, so the title is the parent directory's name
    ([[data-model#resource-scoping]]) throughout -- covered on its own in
    :func:`test_dock_title_uses_the_parent_directory_name_for_info_rehu`.

    **Test steps:**

    * open the fake path
    * verify the dock title has no dirty marker while clean
    * dirty the model and verify the title gains a leading marker
    * clear dirty (as ``save()`` does) and verify the marker is gone again
    """
    load_document(mocker)
    dock = DocumentsDock()
    qtbot.addWidget(dock)

    widget = dock.open_document(FAKE_PATH)
    assert widget is not None
    cdock = dock_for(dock, widget)
    assert cdock.windowTitle() == FAKE_LABEL

    widget.model.title = "Changed"
    assert cdock.windowTitle() == f"{DIRTY_DOCK_MARKER}{FAKE_LABEL}"

    widget.model.dirty = False
    assert cdock.windowTitle() == FAKE_LABEL


def test_dock_title_gains_a_lock_marker_that_takes_precedence_over_dirty(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A locked document's dock tab gets the lock marker instead of the dirty one, even if -- not
    reachable through the UI, since a locked document's editors are disabled, but resolved explicitly
    rather than assumed away -- it were somehow dirty too (A3, [[data-model#schema-version]]).

    **Test steps:**

    * open a document whose ``format_version`` is newer than this build understands
    * verify the dock title gains the lock marker
    * force ``dirty`` true directly on the model and verify the title still shows the lock marker,
      not the dirty one
    """
    load_document(mocker, {**TUTORIAL, "format_version": CURRENT_FORMAT_VERSION + 1})
    dock = DocumentsDock()
    qtbot.addWidget(dock)

    widget = dock.open_document(FAKE_PATH)
    assert widget is not None
    cdock = dock_for(dock, widget)
    assert cdock.windowTitle() == f"{LOCKED_DOCK_MARKER}{FAKE_LABEL}"

    widget.model.dirty = True
    assert cdock.windowTitle() == f"{LOCKED_DOCK_MARKER}{FAKE_LABEL}"


def test_dock_tab_tooltip_always_shows_the_full_path(mocker: MockerFixture, qtbot: QtBot) -> None:
    """The dock's tab tooltip is always the full path, regardless of the ``info.rehu`` title special-case.

    **Test steps:**

    * open the (``info.rehu``) fake path
    * verify the tab tooltip is the full path, not the parent-directory title
    """
    load_document(mocker)
    dock = DocumentsDock()
    qtbot.addWidget(dock)

    widget = dock.open_document(FAKE_PATH)
    assert widget is not None
    cdock = dock_for(dock, widget)

    assert cdock.tabWidget().toolTip() == str(FAKE_PATH)


def test_document_focus_changed_emits_the_widget_when_opening_a_document(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Opening a document emits ``document_focus_changed`` with its widget.

    **Test steps:**

    * connect a spy to ``document_focus_changed``
    * open the fake path
    * verify the spy received that document's widget
    """
    load_document(mocker)
    dock = DocumentsDock()
    qtbot.addWidget(dock)
    with qtbot.waitSignal(dock.document_focus_changed, timeout=1000) as blocker:
        widget = dock.open_document(FAKE_PATH)

    assert blocker.args == [widget]


def test_document_focus_changed_emits_none_when_the_last_dock_closes(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Closing the only open document emits ``document_focus_changed`` with ``None``.

    **Test steps:**

    * open the fake path
    * connect a spy to ``document_focus_changed``
    * close its dock
    * verify the spy received ``None``
    """
    load_document(mocker)
    dock = DocumentsDock()
    qtbot.addWidget(dock)
    widget = dock.open_document(FAKE_PATH)
    assert widget is not None
    cdock = dock_for(dock, widget)

    with qtbot.waitSignal(dock.document_focus_changed, timeout=1000) as blocker:
        cdock.requestCloseDockWidget()

    assert blocker.args == [None]


def test_closing_a_dock_removes_it(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Requesting to close a document's dock removes it from the dock map.

    **Test steps:**

    * open the fake path
    * request the dock's close (the ``CustomCloseHandling`` flow a tab's close button drives)
    * verify the dock map is empty again
    """
    load_document(mocker)
    dock = DocumentsDock()
    qtbot.addWidget(dock)

    widget = dock.open_document(FAKE_PATH)
    cdock = dock_for(dock, widget)

    cdock.requestCloseDockWidget()

    assert not dock._DocumentsDock__document_docks  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def test_closing_a_dirty_dock_prompts_and_discards_on_discard(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Closing a dirty dock prompts, and Discard closes it without saving.

    **Test steps:**

    * open the fake path and dirty its model
    * mock the confirmation dialog to answer Discard
    * request the dock's close
    * verify the dock is gone and the model was not saved
    """
    load_document(mocker)
    dock = DocumentsDock()
    qtbot.addWidget(dock)
    widget = dock.open_document(FAKE_PATH)
    assert widget is not None
    widget.model.title = "Changed"
    cdock = dock_for(dock, widget)
    warning = mocker.patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Discard)
    save = mocker.patch.object(widget.model, "save")

    cdock.requestCloseDockWidget()

    warning.assert_called_once()
    save.assert_not_called()
    assert not dock._DocumentsDock__document_docks  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def test_closing_a_dirty_dock_saves_on_save(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Closing a dirty dock and answering Save saves the document before closing it.

    **Test steps:**

    * open the fake path and dirty its model
    * mock the confirmation dialog to answer Save
    * request the dock's close
    * verify the model was saved and the dock is gone
    """
    load_document(mocker)
    dock = DocumentsDock()
    qtbot.addWidget(dock)
    widget = dock.open_document(FAKE_PATH)
    assert widget is not None
    widget.model.title = "Changed"
    cdock = dock_for(dock, widget)
    mocker.patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Save)
    save = mocker.patch.object(widget.model, "save")

    cdock.requestCloseDockWidget()

    save.assert_called_once()
    assert not dock._DocumentsDock__document_docks  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def test_closing_a_dirty_dock_cancel_leaves_it_open(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Closing a dirty dock and answering Cancel leaves the dock untouched.

    **Test steps:**

    * open the fake path and dirty its model
    * mock the confirmation dialog to answer Cancel
    * request the dock's close
    * verify the dock is still present and the model was not saved
    """
    load_document(mocker)
    dock = DocumentsDock()
    qtbot.addWidget(dock)
    widget = dock.open_document(FAKE_PATH)
    assert widget is not None
    widget.model.title = "Changed"
    cdock = dock_for(dock, widget)
    mocker.patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Cancel)
    save = mocker.patch.object(widget.model, "save")

    cdock.requestCloseDockWidget()

    save.assert_not_called()
    assert len(dock._DocumentsDock__document_docks) == 1  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def test_closing_a_clean_dock_does_not_prompt(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Closing a clean (non-dirty) dock closes it immediately, with no confirmation prompt.

    **Test steps:**

    * open the fake path (clean)
    * mock the confirmation dialog to detect any (unwanted) call
    * request the dock's close
    * verify the dialog was never shown and the dock is gone
    """
    load_document(mocker)
    dock = DocumentsDock()
    qtbot.addWidget(dock)
    widget = dock.open_document(FAKE_PATH)
    assert widget is not None
    cdock = dock_for(dock, widget)
    warning = mocker.patch.object(QMessageBox, "warning")

    cdock.requestCloseDockWidget()

    warning.assert_not_called()
    assert not dock._DocumentsDock__document_docks  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def test_close_all_closes_every_clean_dock_without_a_dialog(mocker: MockerFixture, qtbot: QtBot) -> None:
    """``close_all`` closes every open, clean document without showing the batch confirmation
    dialog (#96).

    **Test steps:**

    * open two clean documents
    * call ``close_all``
    * verify the dialog was never constructed and every dock is gone
    """
    load_document(mocker)
    dock = DocumentsDock()
    qtbot.addWidget(dock)
    dock.open_document(FAKE_PATH)
    dock.open_document(OTHER_PATH)
    dialog_class = mocker.patch("rehuco_agent.documents.documents_dock.UnsavedChangesDialog")

    dock.close_all()

    dialog_class.assert_not_called()
    assert not dock._DocumentsDock__document_docks  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def test_close_all_closes_clean_docks_first_then_shows_one_batch_dialog_for_the_dirty_ones(
    mocker: MockerFixture, qtbot: QtBot
) -> None:
    """``close_all`` closes every clean document immediately -- before the batch dialog even
    appears -- and confirms only the dirty ones through it, mirroring ``MainWindow.closeEvent``;
    cancelling the dialog leaves the (still open) dirty documents alone, but the already-closed
    clean one stays closed regardless (#96).

    **Test steps:**

    * open three documents, dirtying the first and third but leaving the second clean
    * mock the batch dialog to report Cancelled
    * call ``close_all``
    * verify the dialog was built with only the dirty models, never asked for selections, the
      clean document closed anyway, and both dirty documents are still open
    """
    load_document(mocker)
    dock = DocumentsDock()
    qtbot.addWidget(dock)
    first = dock.open_document(FAKE_PATH)
    second = dock.open_document(OTHER_PATH)
    third = dock.open_document(THIRD_PATH)
    assert first is not None and second is not None and third is not None
    first.model.title = "Changed"
    third.model.title = "Changed"
    dialog = mocker.MagicMock()
    dialog.exec.return_value = QDialog.DialogCode.Rejected
    dialog_class = mocker.patch("rehuco_agent.documents.documents_dock.UnsavedChangesDialog", return_value=dialog)

    dock.close_all()

    dialog_class.assert_called_once_with([first.model, third.model], dock)
    dialog.selected_models.assert_not_called()
    remaining = dock._DocumentsDock__document_docks  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    assert list(remaining.values()) == [first, third]


def test_close_all_saves_checked_documents_then_closes_every_open_document(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Accepting the batch dialog saves only the checked (selected) documents, then closes every
    open document regardless -- an unchecked dirty document's edits are discarded along with the
    close, same as the whole-app close guard (#96).

    **Test steps:**

    * open three documents, dirtying the first and third
    * mock the batch dialog to report Accepted, selecting only the first
    * call ``close_all``
    * verify only the first was saved, and every dock (checked or not) is gone
    """
    load_document(mocker)
    dock = DocumentsDock()
    qtbot.addWidget(dock)
    first = dock.open_document(FAKE_PATH)
    second = dock.open_document(OTHER_PATH)
    third = dock.open_document(THIRD_PATH)
    assert first is not None and second is not None and third is not None
    first.model.title = "Changed"
    third.model.title = "Changed"
    save_first = mocker.patch.object(first.model, "save")
    save_third = mocker.patch.object(third.model, "save")
    dialog = mocker.MagicMock()
    dialog.exec.return_value = QDialog.DialogCode.Accepted
    dialog.selected_models.return_value = [first.model]
    dialog_class = mocker.patch("rehuco_agent.documents.documents_dock.UnsavedChangesDialog", return_value=dialog)

    dock.close_all()

    dialog_class.assert_called_once_with([first.model, third.model], dock)
    save_first.assert_called_once_with()
    save_third.assert_not_called()
    assert not dock._DocumentsDock__document_docks  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def test_close_missing_closes_only_missing_docks(mocker: MockerFixture, qtbot: QtBot) -> None:
    """``close_missing`` closes only ``MISSING`` docks, never ``INVALID_FILE`` ones, and never prompts
    (#93, #96).

    **Test steps:**

    * open a ``MISSING`` dock and an ``INVALID_FILE`` dock
    * call ``close_missing``
    * verify no prompt was shown and only the ``MISSING`` dock closed
    """
    mocker.patch.object(Path, "read_text", side_effect=FileNotFoundError("no such file"))
    dock = DocumentsDock()
    qtbot.addWidget(dock)
    missing_widget = dock.open_document(FAKE_PATH)

    mocker.patch.object(Path, "read_text", return_value="{not valid json")
    invalid_widget = dock.open_document(OTHER_PATH)
    assert missing_widget is not None and invalid_widget is not None
    warning = mocker.patch.object(QMessageBox, "warning")

    dock.close_missing()

    warning.assert_not_called()
    remaining = dock._DocumentsDock__document_docks  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    assert list(remaining.values()) == [invalid_widget]


def test_close_missing_is_a_no_op_when_nothing_is_missing(mocker: MockerFixture, qtbot: QtBot) -> None:
    """``close_missing`` leaves every dock open when none is locked with the ``MISSING`` reason (#96).

    **Test steps:**

    * open a clean document
    * call ``close_missing``
    * verify the dock is still present
    """
    load_document(mocker)
    dock = DocumentsDock()
    qtbot.addWidget(dock)
    widget = dock.open_document(FAKE_PATH)
    assert widget is not None

    dock.close_missing()

    remaining = dock._DocumentsDock__document_docks  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    assert list(remaining.values()) == [widget]


def test_has_missing_documents_reflects_whether_any_open_dock_is_missing(mocker: MockerFixture, qtbot: QtBot) -> None:
    """``has_missing_documents`` reports whether any open dock is locked with the ``MISSING`` reason,
    driving the ``View`` menu's "Close Missing Files" enabled state (#96).

    **Test steps:**

    * build an empty dock and verify it reports no missing documents
    * open a ``MISSING`` dock
    * verify it now reports a missing document
    """
    dock = DocumentsDock()
    qtbot.addWidget(dock)
    assert dock.has_missing_documents() is False

    mocker.patch.object(Path, "read_text", side_effect=FileNotFoundError("no such file"))
    dock.open_document(FAKE_PATH)

    assert dock.has_missing_documents() is True


def test_close_requested_ignores_a_non_dock_sender(qtbot: QtBot) -> None:
    """The close handler's ``sender()`` guard does nothing for an unexpected/absent sender.

    Calls the private slot directly rather than via a real ``closeRequested`` emission: outside of
    live signal dispatch, ``QObject.sender()`` returns ``None``, which is exactly the "not a
    CDockWidget" case the guard exists for.

    **Test steps:**

    * call the private close-request handler directly on a dock with no open documents
    * verify it returns without raising and leaves the (empty) dock map untouched
    """
    dock = DocumentsDock()
    qtbot.addWidget(dock)

    dock._DocumentsDock__on_close_dock_widget_requested()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    assert not dock._DocumentsDock__document_docks  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def test_open_document_tracks_a_dock_with_no_area(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Opening a path whose dock currently has no containing area still tracks it as current, just
    without indexing into that (nonexistent) area.

    Registers a stand-in dock directly in the private map, since a real dock added via the normal
    flow always has an area -- this null case can't be reached through the public API alone.

    **Test steps:**

    * register a stand-in dock (reporting no area) for a path, directly in the private map
    * open that same path
    * verify the stand-in's widget was returned and it's tracked as the focused document
    """
    dock = DocumentsDock()
    qtbot.addWidget(dock)

    fake_cdock = mocker.MagicMock()
    fake_cdock.dockAreaWidget.return_value = None
    fake_widget = mocker.MagicMock()
    fake_widget.model.path = FAKE_PATH
    docks = dock._DocumentsDock__document_docks  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    docks[fake_cdock] = fake_widget

    result = dock.open_document(FAKE_PATH)

    assert result is fake_widget
    assert dock.focused_document_path() == FAKE_PATH


def test_closing_a_non_current_dock_leaves_the_current_dock_unchanged(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Closing a dock that isn't the tracked current one doesn't clear the current-dock bookkeeping.

    **Test steps:**

    * open two documents (the second, opened last, is the current one)
    * close the first (non-current) document's dock
    * verify the focused document is still the second one
    """
    load_document(mocker)
    dock = DocumentsDock()
    qtbot.addWidget(dock)
    first_widget = dock.open_document(FAKE_PATH)
    first_cdock = dock_for(dock, first_widget)
    dock.open_document(OTHER_PATH)
    assert dock.focused_document_path() == OTHER_PATH

    first_cdock.requestCloseDockWidget()

    assert dock.focused_document_path() == OTHER_PATH


def test_opening_a_missing_file_opens_an_empty_locked_dock(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A path whose file is gone opens as an empty, locked dock -- never a dialog, never ``None``
    ([[data-model#write-integrity]]); the ``MISSING`` kind is kept distinct so a "close vanished files"
    sweep never touches a dock the user is mid-repair on.

    **Test steps:**

    * mock the filesystem so reading the path raises ``FileNotFoundError`` (the file is gone)
    * mock the error dialog to prove it is *not* used
    * open the path
    * verify a dock came back, locked with the ``MISSING`` reason, bound to the path, clean, no dialog
    """
    mocker.patch.object(Path, "read_text", side_effect=FileNotFoundError("no such file"))
    critical = mocker.patch.object(QMessageBox, "critical")
    dock = DocumentsDock()
    qtbot.addWidget(dock)

    widget = dock.open_document(FAKE_PATH)

    assert widget is not None
    assert widget.model.locked is True
    assert [reason.kind for reason in widget.model.lock_reasons] == [LockReasonKind.MISSING]
    assert widget.model.path == FAKE_PATH
    assert widget.model.dirty is False
    assert len(dock._DocumentsDock__document_docks) == 1  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    critical.assert_not_called()


def test_focused_document_path_reports_the_focused_documents_path(mocker: MockerFixture, qtbot: QtBot) -> None:
    """The focused document's path is reported once a dock is the current one.

    **Test steps:**

    * open a document (which tracks it as current)
    * verify ``focused_document_path`` returns its path
    """
    load_document(mocker)
    dock = DocumentsDock()
    qtbot.addWidget(dock)
    widget = dock.open_document(FAKE_PATH)
    assert widget is not None

    assert dock.focused_document_path() == FAKE_PATH


def test_focused_document_path_is_none_with_no_focused_dock(qtbot: QtBot) -> None:
    """With no dock focused (e.g. nothing open yet), ``focused_document_path`` reports ``None``.

    **Test steps:**

    * build an empty dock
    * verify ``focused_document_path`` returns ``None``
    """
    dock = DocumentsDock()
    qtbot.addWidget(dock)

    assert dock.focused_document_path() is None


def test_focus_document_makes_the_given_widgets_dock_current(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Focusing a document's widget makes its dock the current one (#61).

    Registers two stand-in docks directly in the private map (as
    :func:`test_open_document_tracks_a_dock_with_no_area` does), rather than opening real documents
    -- :meth:`focus_document` only needs to find and activate the right dock, not exercise document
    loading.

    **Test steps:**

    * register two stand-in docks, and focus the second one
    * focus the first widget instead
    * verify it is now the focused document
    """
    dock = DocumentsDock()
    qtbot.addWidget(dock)
    docks = dock._DocumentsDock__document_docks  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    first_cdock, first_widget = mocker.MagicMock(), mocker.MagicMock()
    first_widget.model.path = FAKE_PATH
    second_cdock, second_widget = mocker.MagicMock(), mocker.MagicMock()
    second_widget.model.path = OTHER_PATH
    docks[first_cdock] = first_widget
    docks[second_cdock] = second_widget
    dock.focus_document(second_widget)
    assert dock.focused_document_path() == OTHER_PATH

    dock.focus_document(first_widget)

    assert dock.focused_document_path() == FAKE_PATH


def test_focus_document_works_for_a_document_with_no_path(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Focusing a document's widget works even with no path yet, unlike
    :meth:`DocumentsDock.open_document`, which needs a path to look a dock up by (a genuinely
    path-less "New Document" dock, pending A5, could otherwise never be focused this way).

    **Test steps:**

    * register two stand-in docks, one with no path, and focus the one with a path
    * focus the path-less widget instead
    * verify it is now the focused document (reported as ``None``, its own path)
    """
    dock = DocumentsDock()
    qtbot.addWidget(dock)
    docks = dock._DocumentsDock__document_docks  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    other_cdock, other_widget = mocker.MagicMock(), mocker.MagicMock()
    other_widget.model.path = OTHER_PATH
    fake_cdock, fake_widget = mocker.MagicMock(), mocker.MagicMock()
    fake_widget.model.path = None
    docks[other_cdock] = other_widget
    docks[fake_cdock] = fake_widget
    dock.focus_document(other_widget)
    assert dock.focused_document_path() == OTHER_PATH

    dock.focus_document(fake_widget)

    assert dock.focused_document_path() is None


def test_double_clicking_a_tab_label_does_not_raise(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Double-clicking a document's tab label doesn't raise -- wired to a placeholder for now,
    pending the future preview-tab-mode feature the double-click is meant to drive.

    **Test steps:**

    * open the fake path
    * emit its tab label's `doubleClicked` signal
    * verify nothing raises
    """
    load_document(mocker)
    dock = DocumentsDock()
    qtbot.addWidget(dock)
    widget = dock.open_document(FAKE_PATH)
    cdock = dock_for(dock, widget)

    tab_label(cdock).doubleClicked.emit()


def test_opening_an_invalid_rehu_opens_an_empty_locked_dock(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A file that isn't valid ``.rehu`` JSON opens as an empty, locked dock -- never a dialog, never
    ``None`` ([[data-model#write-integrity]]); the ``INVALID_FILE`` reason carries the parser's text so
    the user can hand-fix the file and revert in place.

    **Test steps:**

    * mock the filesystem to serve malformed JSON (``RehuDocument.load`` raises ``RehuFormatError``)
    * mock the error dialog to prove it is *not* used
    * open the path
    * verify a dock came back, locked with the ``INVALID_FILE`` reason and a non-empty message, no dialog
    """
    mocker.patch.object(Path, "read_text", return_value="{not valid json")
    critical = mocker.patch.object(QMessageBox, "critical")
    dock = DocumentsDock()
    qtbot.addWidget(dock)

    widget = dock.open_document(FAKE_PATH)

    assert widget is not None
    assert widget.model.locked is True
    assert [reason.kind for reason in widget.model.lock_reasons] == [LockReasonKind.INVALID_FILE]
    assert all(reason.message for reason in widget.model.lock_reasons)
    assert widget.model.dirty is False
    assert dock_for(dock, widget).windowTitle().startswith(LOCKED_DOCK_MARKER)
    critical.assert_not_called()


def test_restore_state_retracks_current_tab_after_area_recreation(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Tab switches keep updating the current dock even after ``restore_state`` recreates areas.

    ``CDockManager.restoreState()`` rebuilds every affected ``CDockAreaWidget`` from scratch,
    orphaning any ``currentChanged`` connection made before the call -- confirmed empirically to
    otherwise leave :meth:`DocumentsDock.focused_document_path` stuck on whatever was current
    before restore, never picking up a tab switch made afterwards (the reported regression: the
    focused document was no longer updated in the saved session after a restart).

    **Test steps:**

    * open two documents (tabbed together, sharing one area) and save the outer layout
    * restore that same layout, rebuilding the tabbed area
    * switch to the first document's tab on the (possibly new) area object
    * verify the current dock -- and so ``focused_document_path`` -- picked up the switch
    """
    load_document(mocker)
    dock = DocumentsDock()
    qtbot.addWidget(dock)
    widget1 = dock.open_document(FAKE_PATH)
    widget2 = dock.open_document(OTHER_PATH)
    assert widget1 is not None and widget2 is not None
    state = dock.save_state()

    assert dock.restore_state(state)

    cdock1 = dock_for(dock, widget1)
    area = cdock1.dockAreaWidget()
    assert area is not None
    area.setCurrentIndex(area.index(cdock1))

    assert dock.focused_document_path() == FAKE_PATH


def test_restore_state_returns_false_for_empty_state(qtbot: QtBot) -> None:
    """An empty (never-saved) state is rejected without touching the current layout.

    **Test steps:**

    * restore an empty byte string on a dock with nothing open
    * verify it reports failure
    """
    dock = DocumentsDock()
    qtbot.addWidget(dock)

    assert dock.restore_state(b"") is False


def test_dock_object_name_is_the_document_path_regardless_of_id(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A dock's object name is its document's path, whether or not the document has an ``id`` --
    deliberately not the id itself, since a ``.tc``-backed document has none until a live conversion
    mints one partway through an already-open dock's lifetime ([[acquisition-tooling#tc-to-rehu]]).

    **Test steps:**

    * open a document whose data includes an ``id``
    * verify its dock's object name is the path, not the id
    """
    load_document(mocker, {**TUTORIAL, "id": "some-stable-id"})
    dock = DocumentsDock()
    qtbot.addWidget(dock)

    widget = dock.open_document(FAKE_PATH)

    assert widget is not None
    assert dock_for(dock, widget).objectName() == str(FAKE_PATH)


def test_dock_object_name_falls_back_to_the_path_without_an_id(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A dock's object name is the path when the document has no id too (e.g. a not-yet-imported file).

    **Test steps:**

    * open a document whose data has no ``id``
    * verify its dock's object name is the path
    """
    load_document(mocker)
    dock = DocumentsDock()
    qtbot.addWidget(dock)

    widget = dock.open_document(FAKE_PATH)

    assert widget is not None
    assert dock_for(dock, widget).objectName() == str(FAKE_PATH)


def test_dock_object_name_resyncs_across_a_tc_to_rehu_conversion(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A live ``.tc`` -> ``.rehu`` conversion ([[acquisition-tooling#tc-to-rehu]]) resyncs the
    already-open dock's object name to the converted path, via :attr:`RehuDocumentModel.path_changed`
    -- not by the identifier being transition-immune by construction.

    **Test steps:**

    * open a ``.tc`` document and note its dock's initial object name
    * convert it in place
    * verify the dock's object name is now the ``.rehu`` path
    """
    mocker.patch.object(Path, "read_text", return_value=TC_TUTORIAL)
    dock = DocumentsDock()
    qtbot.addWidget(dock)
    tc_path = FAKE_PATH.with_suffix(".tc")
    widget = dock.open_document(tc_path)
    assert widget is not None
    assert dock_for(dock, widget).objectName() == str(tc_path)

    load_document(mocker)
    rehu_document = RehuDocument.load(FAKE_PATH)
    mocker.patch("rehuco_agent.documents.rehu_document_model.convert_tc", return_value=rehu_document)
    widget.model.convert(keep_backups=False)

    assert dock_for(dock, widget).objectName() == str(FAKE_PATH)


def test_open_folder_with_existing_info_rehu_opens_it(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Opening a folder whose ``info.rehu`` already exists behaves exactly like ``open_document``.

    **Test steps:**

    * mock the filesystem so ``info.rehu`` both exists and serves the tutorial fixture
    * open the folder (not the ``info.rehu`` path itself)
    * verify the resulting document's path is ``folder/info.rehu`` and it is not dirty
    """
    load_document(mocker)
    mocker.patch.object(Path, "exists", return_value=True)
    dock = DocumentsDock()
    qtbot.addWidget(dock)

    widget = dock.open_folder(FAKE_PATH.parent)

    assert widget is not None
    assert widget.model.path == FAKE_PATH
    assert widget.model.dirty is False


def test_open_folder_with_a_corrupted_info_rehu_opens_an_empty_locked_dock(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A folder whose ``info.rehu`` exists but is corrupted opens the same empty, locked dock as a bad
    ``.rehu`` file ([[data-model#write-integrity]]) -- the exists-branch never silently falls through to
    "start a new document", and never shows a dialog.

    **Test steps:**

    * mock the filesystem so ``info.rehu`` exists but its content isn't valid JSON
    * mock the error dialog to prove it is *not* used
    * open the folder
    * verify a locked ``INVALID_FILE`` dock came back, bound to the ``info.rehu`` path, no dialog
    """
    mocker.patch.object(Path, "exists", return_value=True)
    mocker.patch.object(Path, "read_text", return_value="{not valid json")
    critical = mocker.patch.object(QMessageBox, "critical")
    dock = DocumentsDock()
    qtbot.addWidget(dock)

    widget = dock.open_folder(FAKE_PATH.parent)

    assert widget is not None
    assert [reason.kind for reason in widget.model.lock_reasons] == [LockReasonKind.INVALID_FILE]
    assert widget.model.path == FAKE_PATH
    critical.assert_not_called()


def test_open_folder_without_info_rehu_starts_a_new_dirty_document(qtbot: QtBot) -> None:
    """Opening a folder with no ``info.rehu`` yet starts a new, already-dirty document bound to it.

    Nothing is read from or written to disk -- the fake folder never actually exists, so
    ``info_path.exists()`` is genuinely ``False`` here, no mocking needed (#43).

    **Test steps:**

    * open a folder that has no ``info.rehu``
    * verify the new document's path is ``folder/info.rehu``, it seeded empty, and it is dirty
    """
    dock = DocumentsDock()
    qtbot.addWidget(dock)

    widget = dock.open_folder(FAKE_PATH.parent)

    assert widget is not None
    assert widget.model.path == FAKE_PATH
    assert widget.model.title == ""
    assert widget.model.dirty is True


def test_open_folder_reopening_the_new_unsaved_document_focuses_it(qtbot: QtBot) -> None:
    """Reopening the same missing-``info.rehu`` folder focuses the still-unsaved dock, not a second one.

    **Test steps:**

    * open a folder with no ``info.rehu`` twice
    * verify the same widget comes back both times and only one dock exists
    """
    dock = DocumentsDock()
    qtbot.addWidget(dock)

    first = dock.open_folder(FAKE_PATH.parent)
    second = dock.open_folder(FAKE_PATH.parent)

    assert first is second
    assert len(dock._DocumentsDock__document_docks) == 1  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def test_open_archive_with_existing_rehu_companion_opens_it(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Opening an archive whose ``.rehu`` companion already exists behaves exactly like ``open_document``.

    **Test steps:**

    * mock the filesystem so the companion both exists and serves the tutorial fixture
    * open the archive (not the companion path itself)
    * verify the resulting document's path is the companion and it is not dirty
    """
    load_document(mocker)
    mocker.patch.object(Path, "exists", return_value=True)
    dock = DocumentsDock()
    qtbot.addWidget(dock)

    widget = dock.open_archive(FAKE_ARCHIVE_PATH)

    assert widget is not None
    assert widget.model.path == FAKE_ARCHIVE_INFO_PATH
    assert widget.model.dirty is False


def test_open_archive_with_a_corrupted_rehu_companion_opens_an_empty_locked_dock(
    mocker: MockerFixture, qtbot: QtBot
) -> None:
    """An archive whose ``.rehu`` companion exists but is corrupted opens the same empty, locked dock as a
    bad ``.rehu`` file ([[data-model#write-integrity]]) -- the exists-branch never silently falls through
    to "start a new document", and never shows a dialog.

    **Test steps:**

    * mock the filesystem so the companion exists but its content isn't valid JSON
    * mock the error dialog to prove it is *not* used
    * open the archive
    * verify a locked ``INVALID_FILE`` dock came back, bound to the companion path, no dialog
    """
    mocker.patch.object(Path, "exists", return_value=True)
    mocker.patch.object(Path, "read_text", return_value="{not valid json")
    critical = mocker.patch.object(QMessageBox, "critical")
    dock = DocumentsDock()
    qtbot.addWidget(dock)

    widget = dock.open_archive(FAKE_ARCHIVE_PATH)

    assert widget is not None
    assert [reason.kind for reason in widget.model.lock_reasons] == [LockReasonKind.INVALID_FILE]
    assert widget.model.path == FAKE_ARCHIVE_INFO_PATH
    critical.assert_not_called()


def test_open_archive_without_a_rehu_companion_starts_a_new_dirty_document(qtbot: QtBot) -> None:
    """Opening an archive with no ``.rehu`` companion yet starts a new, already-dirty document bound to it.

    Nothing is read from or written to disk -- the fake archive never actually exists, so
    ``info_path.exists()`` is genuinely ``False`` here, no mocking needed (#43).

    **Test steps:**

    * open an archive that has no ``.rehu`` companion
    * verify the new document's path is the companion, it seeded empty, and it is dirty
    """
    dock = DocumentsDock()
    qtbot.addWidget(dock)

    widget = dock.open_archive(FAKE_ARCHIVE_PATH)

    assert widget is not None
    assert widget.model.path == FAKE_ARCHIVE_INFO_PATH
    assert widget.model.title == ""
    assert widget.model.dirty is True


def test_open_archive_reopening_the_new_unsaved_document_focuses_it(qtbot: QtBot) -> None:
    """Reopening the same missing-companion archive focuses the still-unsaved dock, not a second one.

    **Test steps:**

    * open an archive with no ``.rehu`` companion twice
    * verify the same widget comes back both times and only one dock exists
    """
    dock = DocumentsDock()
    qtbot.addWidget(dock)

    first = dock.open_archive(FAKE_ARCHIVE_PATH)
    second = dock.open_archive(FAKE_ARCHIVE_PATH)

    assert first is second
    assert len(dock._DocumentsDock__document_docks) == 1  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def only_tc_exists(path: Path) -> bool:
    """``Path.exists`` stand-in: only a ``.tc`` path reports as present.

    Used with ``autospec=True`` so the mock actually receives ``self`` per call -- a plain
    (non-autospec) ``mocker.patch.object(Path, "exists", ...)`` never does, which is why every other
    test in this file uses a single blanket ``return_value`` instead.

    :param path: the ``Path`` instance ``.exists()`` was called on.
    :returns: whether ``path``'s suffix is ``.tc``.
    """
    return path.suffix == ".tc"


def test_open_folder_falls_back_to_a_tc_companion_when_info_rehu_is_missing(
    mocker: MockerFixture, qtbot: QtBot
) -> None:
    """Opening a folder with no ``info.rehu`` but a legacy ``info.tc`` opens the ``.tc`` instead
    (A3.1 Phase 2, [[acquisition-tooling#tc-to-rehu]]), locked and read-only.

    **Test steps:**

    * mock the filesystem so only ``info.tc`` exists, serving a tc4 YAML fixture
    * open the folder (not the ``info.tc`` path itself)
    * verify the resulting document's path is ``folder/info.tc``, it is locked, not dirty, and its
      fields came from the ``.tc`` mapping
    """
    mocker.patch.object(Path, "exists", autospec=True, side_effect=only_tc_exists)
    mocker.patch.object(Path, "read_text", return_value=TC_TUTORIAL)
    dock = DocumentsDock()
    qtbot.addWidget(dock)

    widget = dock.open_folder(FAKE_PATH.parent)

    assert widget is not None
    assert widget.model.path == FAKE_PATH.with_suffix(".tc")
    assert widget.model.locked is True
    assert widget.model.dirty is False
    assert widget.model.title == "Legacy Title"


def test_open_archive_falls_back_to_a_tc_companion_when_rehu_is_missing(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Opening an archive with no ``.rehu`` companion but a legacy ``.tc`` one opens the ``.tc``
    instead (A3.1 Phase 2, [[acquisition-tooling#tc-to-rehu]]), locked and read-only.

    **Test steps:**

    * mock the filesystem so only the ``.tc`` companion exists, serving a tc4 YAML fixture
    * open the archive (not the companion path itself)
    * verify the resulting document's path is the ``.tc`` companion, it is locked, and not dirty
    """
    mocker.patch.object(Path, "exists", autospec=True, side_effect=only_tc_exists)
    mocker.patch.object(Path, "read_text", return_value=TC_TUTORIAL)
    dock = DocumentsDock()
    qtbot.addWidget(dock)

    widget = dock.open_archive(FAKE_ARCHIVE_PATH)

    assert widget is not None
    assert widget.model.path == FAKE_ARCHIVE_INFO_PATH.with_suffix(".tc")
    assert widget.model.locked is True
    assert widget.model.dirty is False


def test_open_document_with_a_tc_path_loads_it_as_legacy(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Opening a ``.tc`` path directly (a registered double-click or shell verb, A3.1 Phase 2,
    [[acquisition-tooling#tc-to-rehu]]) routes through ``load_tc``, not ``RehuDocument.load``.

    **Test steps:**

    * mock the filesystem to serve a tc4 YAML fixture
    * open a ``.tc`` path directly via ``open_document``
    * verify the resulting document is locked and its fields came from the ``.tc`` mapping
    """
    mocker.patch.object(Path, "read_text", return_value=TC_TUTORIAL)
    dock = DocumentsDock()
    qtbot.addWidget(dock)

    widget = dock.open_document(FAKE_PATH.with_suffix(".tc"))

    assert widget is not None
    assert widget.model.locked is True
    assert widget.model.title == "Legacy Title"


def test_open_folder_with_a_corrupted_tc_fallback_opens_an_empty_locked_dock(
    mocker: MockerFixture, qtbot: QtBot
) -> None:
    """A folder whose ``info.tc`` fallback exists but is corrupted opens the same empty, locked dock as a
    bad ``.rehu`` file ([[data-model#write-integrity]]) -- the ``.tc`` fallback never silently falls
    through to "start a new document", and never shows a dialog. Its failure routes through the same
    ``locked_stub_for_error`` seam as a ``.rehu`` failure.

    **Test steps:**

    * mock the filesystem so only ``info.tc`` exists, with content that isn't valid YAML
    * mock the error dialog to prove it is *not* used
    * open the folder
    * verify a locked ``INVALID_FILE`` dock came back, bound to the ``info.tc`` path, no dialog
    """
    mocker.patch.object(Path, "exists", autospec=True, side_effect=only_tc_exists)
    mocker.patch.object(Path, "read_text", return_value="tags: [unterminated")
    critical = mocker.patch.object(QMessageBox, "critical")
    dock = DocumentsDock()
    qtbot.addWidget(dock)

    widget = dock.open_folder(FAKE_PATH.parent)

    assert widget is not None
    assert [reason.kind for reason in widget.model.lock_reasons] == [LockReasonKind.INVALID_FILE]
    assert widget.model.path == FAKE_PATH.with_suffix(".tc")
    critical.assert_not_called()


def configure_identity(mocker: MockerFixture, *, current: str = "admin", unknown: str = "unknown") -> None:
    """Stand in for the configured identity settings the dock reads at open time (#109).

    Both usernames are set to distinct values in each test that cares, so an assertion proves the dock
    routed the *right* one: the **current** user for a ``.rehu``/new document (where this UI's edits land),
    the **unknown** user for a ``.tc`` import (whose per-user state was set elsewhere).

    :param mocker: pytest-mock fixture.
    :param current: the current username ``shared_identity_settings()`` should report.
    :param unknown: the unknown username ``shared_identity_settings()`` should report.
    """
    mocker.patch.object(
        documents_dock,
        "shared_identity_settings",
        return_value=IdentitySettings(current_username=current, unknown_username=unknown),
    )


def test_open_document_threads_the_current_username(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Opening a ``.rehu`` hands the **current** identity to ``RehuDocument.load`` -- this UI's edits land
    under it -- not the unknown one ([[field-schema#per-user-shared]], #109).

    **Test steps:**

    * configure current ``alice`` / unknown ``strangers`` and open a ``.rehu``
    * verify the resulting document carries the current username, not the unknown one
    """
    configure_identity(mocker, current="alice", unknown="strangers")
    load_document(mocker)
    dock = DocumentsDock()
    qtbot.addWidget(dock)

    widget = dock.open_document(FAKE_PATH)

    assert widget.model.document.username == "alice"


def test_open_document_with_a_tc_path_threads_the_unknown_username(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Opening a legacy ``.tc`` hands the **unknown** identity to ``load_tc`` -- the imported per-user flags
    were not set by this install, so they file under it, not the current user (#109).

    See [[field-schema#per-user-shared]].

    **Test steps:**

    * configure current ``alice`` / unknown ``strangers`` and open a ``.tc``
    * verify the mapped document carries the unknown username, and its block's ``users`` map is keyed by it
    """
    configure_identity(mocker, current="alice", unknown="strangers")
    mocker.patch.object(Path, "read_text", return_value=TC_TUTORIAL)
    dock = DocumentsDock()
    qtbot.addWidget(dock)

    widget = dock.open_document(FAKE_PATH.with_suffix(".tc"))

    assert widget.model.document.username == "strangers"
    assert list(widget.model.document.data["tutorial"]["users"]) == ["strangers"]


def test_a_failed_rehu_open_threads_the_current_username_into_the_locked_stub(
    mocker: MockerFixture, qtbot: QtBot
) -> None:
    """A failed ``.rehu`` load's empty locked stub carries the **current** identity, so hand-fixing the
    file and reverting retries under the same username the open was asked for (#109).

    **Test steps:**

    * configure current ``alice`` / unknown ``strangers`` and open a ``.rehu`` whose read fails
    * verify the locked stub's document carries the current username
    """
    configure_identity(mocker, current="alice", unknown="strangers")
    mocker.patch.object(Path, "read_text", side_effect=OSError("unreadable"))
    dock = DocumentsDock()
    qtbot.addWidget(dock)

    widget = dock.open_document(FAKE_PATH)

    assert widget.model.locked is True
    assert widget.model.document.username == "alice"


def test_a_failed_tc_open_threads_the_unknown_username_into_the_locked_stub(
    mocker: MockerFixture, qtbot: QtBot
) -> None:
    """A failed ``.tc`` load's empty locked stub carries the **unknown** identity, matching the branch a
    successful ``.tc`` import would have used (#109).

    **Test steps:**

    * configure current ``alice`` / unknown ``strangers`` and open a ``.tc`` whose read fails
    * verify the locked stub's document carries the unknown username
    """
    configure_identity(mocker, current="alice", unknown="strangers")
    mocker.patch.object(Path, "read_text", side_effect=OSError("unreadable"))
    dock = DocumentsDock()
    qtbot.addWidget(dock)

    widget = dock.open_document(FAKE_PATH.with_suffix(".tc"))

    assert widget.model.locked is True
    assert widget.model.document.username == "strangers"


def test_a_new_document_threads_the_current_username(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A folder with no ``info.rehu``/``info.tc`` starts its new document under the **current** identity,
    so its eventual per-user writes are filed correctly (#109).

    **Test steps:**

    * configure current ``alice`` / unknown ``strangers`` and open a folder where neither companion exists
    * verify the new, dirty document carries the current username
    """
    configure_identity(mocker, current="alice", unknown="strangers")
    mocker.patch.object(Path, "exists", return_value=False)
    dock = DocumentsDock()
    qtbot.addWidget(dock)

    widget = dock.open_folder(FAKE_PATH.parent)

    assert widget.model.dirty is True
    assert widget.model.document.username == "alice"
