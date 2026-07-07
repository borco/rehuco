"""Tests for DocumentsDock: one dock per open `.rehu`, focus-and-reuse by path."""

import json
from pathlib import Path
from typing import Any, Final

import PySide6QtAds as QtAds
from borco_pyside.qtads import tab_label
from PySide6.QtWidgets import QMessageBox
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.documents_dock import DIRTY_DOCK_MARKER, DocumentsDock

FAKE_PATH: Final = Path.cwd() / "fake" / "tutorials" / "sculpting" / "info.rehu"
"""``open_document`` asserts an absolute path; built from ``Path.cwd()`` so it's absolute on every
platform (unlike a hardcoded ``/fake/...``, which isn't absolute on Windows without a drive)."""
FAKE_LABEL: Final = f"{FAKE_PATH.parent.name}/"
"""``FAKE_PATH``'s expected dock-title label: an ``info.rehu``'s parent directory name, trailing-slashed."""
OTHER_PATH: Final = Path.cwd() / "fake" / "tutorials" / "painting" / "info.rehu"

TUTORIAL: Final = {
    "format_version": 1,
    "type": "Tutorial",
    "sources": [{"title": "Foo", "publisher": "Bar", "url": "https://example.com", "primary": True}],
}


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
    """The dock's tab title gains a trailing marker while the document is dirty, and loses it on save.

    ``FAKE_PATH`` is an ``info.rehu``, so the title is the parent directory's name
    ([[data-model#resource-scoping]]) throughout -- covered on its own in
    :func:`test_dock_title_uses_the_parent_directory_name_for_info_rehu`.

    **Test steps:**

    * open the fake path
    * verify the dock title has no dirty marker while clean
    * dirty the model and verify the title gains a trailing ``*``
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
    assert cdock.windowTitle() == f"{FAKE_LABEL}{DIRTY_DOCK_MARKER}"

    widget.model.dirty = False
    assert cdock.windowTitle() == FAKE_LABEL


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


def test_opening_a_missing_file_shows_an_error_and_no_dock(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A path that cannot be read gets an error dialog instead of a dock (#35).

    **Test steps:**

    * mock the filesystem so reading the path raises ``OSError`` (missing/unreadable file)
    * mock the error dialog (a real modal would block the headless test)
    * open the path
    * verify ``None`` came back, no dock was created, and the dialog named the path
    """
    mocker.patch.object(Path, "read_text", side_effect=OSError("no such file"))
    critical = mocker.patch.object(QMessageBox, "critical")
    dock = DocumentsDock()
    qtbot.addWidget(dock)

    widget = dock.open_document(FAKE_PATH)

    assert widget is None
    assert not dock._DocumentsDock__document_docks  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    critical.assert_called_once()
    assert str(FAKE_PATH) in critical.call_args[0][2]


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


def test_opening_an_invalid_rehu_shows_an_error_and_no_dock(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A file that isn't valid ``.rehu`` JSON gets an error dialog instead of a dock (#35).

    **Test steps:**

    * mock the filesystem to serve malformed JSON (raises ``RehuFormatError`` on load)
    * mock the error dialog (a real modal would block the headless test)
    * open the path
    * verify ``None`` came back, no dock was created, and the dialog named the path
    """
    mocker.patch.object(Path, "read_text", return_value="{not valid json")
    critical = mocker.patch.object(QMessageBox, "critical")
    dock = DocumentsDock()
    qtbot.addWidget(dock)

    widget = dock.open_document(FAKE_PATH)

    assert widget is None
    assert not dock._DocumentsDock__document_docks  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    critical.assert_called_once()
    assert str(FAKE_PATH) in critical.call_args[0][2]


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


def test_dock_object_name_prefers_the_documents_own_id(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A dock's object name is its document's stable id when the document has one.

    Needed for ``restore_state`` to match a saved layout entry back up to the dock recreated for
    the same document on the next launch (``CDockManager`` matches docks up by ``objectName()``).

    **Test steps:**

    * open a document whose data includes an ``id``
    * verify its dock's object name is that id, not its path
    """
    load_document(mocker, {**TUTORIAL, "id": "some-stable-id"})
    dock = DocumentsDock()
    qtbot.addWidget(dock)

    widget = dock.open_document(FAKE_PATH)

    assert widget is not None
    assert dock_for(dock, widget).objectName() == "some-stable-id"


def test_dock_object_name_falls_back_to_the_path_without_an_id(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A dock's object name falls back to its document's path when the document has no id.

    **Test steps:**

    * open a document whose data has no ``id`` (e.g. a not-yet-imported file)
    * verify its dock's object name is its path
    """
    load_document(mocker)
    dock = DocumentsDock()
    qtbot.addWidget(dock)

    widget = dock.open_document(FAKE_PATH)

    assert widget is not None
    assert dock_for(dock, widget).objectName() == str(FAKE_PATH)
