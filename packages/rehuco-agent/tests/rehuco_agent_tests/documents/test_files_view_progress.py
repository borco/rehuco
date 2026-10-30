"""Tests for the file browser showing and recording watch progress (#316, [[field-schema#watch-progress]],
[[plugins#files-subdock]]).

A real tutorial under ``tmp_path``, read and written through real records, listed by the real classifier: what is
being tested is the browser's wiring to the model -- which row says what, what the row actions record -- and each
piece's own rules are tested where it lives.
"""

from pathlib import Path
from typing import Any, Final

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import QTableView
from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents import files_view
from rehuco_agent.documents.files_progress import UNMEASURED_FOLDER_TOOLTIP, RowProgress
from rehuco_agent.documents.files_rows import KIND_COLUMN, NAME_COLUMN, FilesTableModel
from rehuco_agent.documents.files_view import LOADING_SUMMARY, FilesView
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_core import (
    DirectoryClassifier,
    ProgressEntry,
    VideoFacts,
)
from rehuco_core.access import Records, ResourceKey

from rehuco_agent_tests.delete_at_teardown import DeleteAtTeardown
from rehuco_agent_tests.documents.test_rehu_document_model_progress import write_tutorial
from rehuco_agent_tests.record_reads import read_now

pytestmark = mark.usefixtures("real_path_stat")

TIMEOUT: Final = 5000

VIDEOS: Final = ("a.mp4", "01 Basics/b.mp4", "01 Basics/c.mp4")
"""The tutorial's videos: one at the top, two in a folder."""


@fixture(name="model")
def fixture_model(tmp_path: Path, qtbot: QtBot, delete_at_teardown: DeleteAtTeardown) -> RehuDocumentModel:
    """A model over a real tutorial of three videos, opened as an open builds it.

    :param tmp_path: the resource's parent folder.
    :param qtbot: pytest-qt fixture.
    :param delete_at_teardown: deletes the bare model when the test ends.
    :returns: the model.
    """
    del qtbot
    path = write_tutorial(tmp_path / "t", VIDEOS)
    records = Records()
    record = read_now(records, ResourceKey(path))
    return delete_at_teardown(
        RehuDocumentModel(record.document, records=records, version=record.version, signature=record.signature)
    )


@fixture(name="view")
def fixture_view(qtbot: QtBot, model: RehuDocumentModel) -> FilesView:
    """A shown browser over the tutorial's folder, its first read landed.

    :param qtbot: pytest-qt fixture.
    :param model: the document.
    :returns: the view.
    """
    view = FilesView(model)
    qtbot.addWidget(view)
    view.show()
    settle(qtbot, view)
    return view


def settle(qtbot: QtBot, view: FilesView) -> None:
    """Wait for the background listing to land.

    :param qtbot: pytest-qt fixture.
    :param view: the view whose summary stops saying *reading* once it has.
    """
    qtbot.waitUntil(lambda: view.summary != LOADING_SUMMARY, timeout=TIMEOUT)


def names(view: FilesView) -> list[str]:
    """The names, in the order the table draws them.

    :param view: the view to read.
    :returns: the names.
    """
    return [view.proxy.index(row, NAME_COLUMN).data() for row in range(view.proxy.rowCount())]


def progress_of(view: FilesView, name: str) -> Any:
    """What a row ends with.

    :param view: the view to read.
    :param name: the row's name.
    :returns: the row's progress role.
    """
    return view.proxy.index(names(view).index(name), NAME_COLUMN).data(FilesTableModel.PROGRESS_ROLE)


def go_into(qtbot: QtBot, view: FilesView, name: str) -> None:
    """Walk into a folder row, as a double-click does.

    :param qtbot: pytest-qt fixture.
    :param view: the view.
    :param name: the folder's name.
    """
    view.activate(names(view).index(name))
    settle(qtbot, view)


# region what the rows say


def test_a_video_and_its_folder_show_what_was_watched(model: RehuDocumentModel, view: FilesView) -> None:
    """A video's own share, and the duration-weighted share of the videos beneath a folder.

    **Test steps:**

    * measure the three videos at 100, 60 and 40 seconds, play the top one halfway and mark the folder's first viewed
    * verify the top video reads 50%, and the folder 60% -- 60 viewed of 100
    """
    model.record_videos(
        {"a.mp4": VideoFacts(100.0), "01 Basics/b.mp4": VideoFacts(60.0), "01 Basics/c.mp4": VideoFacts(40.0)}
    )
    model.record_progress("a.mp4", 50.0, 100.0)
    model.record_progress("01 Basics/b.mp4", 0.0, 60.0, viewed=True)

    assert progress_of(view, "a.mp4").text == "50%"
    assert progress_of(view, "01 Basics") == RowProgress("60%")


def test_a_folder_holding_an_unmeasured_video_shows_no_percentage_and_says_so(view: FilesView) -> None:
    """Nothing has been measured, so a folder's share would be a guess.

    **Test steps:**

    * read the folder's row
    * verify no text and the tooltip saying some lengths are unknown
    """
    assert progress_of(view, "01 Basics") == RowProgress(tooltip=UNMEASURED_FOLDER_TOOLTIP)


def test_a_change_of_progress_redraws_without_listing_again(
    model: RehuDocumentModel, view: FilesView, mocker: MockerFixture
) -> None:
    """Percentages follow the model's signal, from what was read: the disk is not asked.

    **Test steps:**

    * count the listings, then record a position
    * verify the row shows it and the listing count did not move
    """
    classify = mocker.spy(DirectoryClassifier, "classify")

    model.record_progress("a.mp4", 25.0, 100.0)

    assert progress_of(view, "a.mp4").text == "25%"
    assert classify.call_count == 0


def test_a_document_that_is_not_a_tutorial_shows_no_progress(
    tmp_path: Path, qtbot: QtBot, delete_at_teardown: DeleteAtTeardown
) -> None:
    """Watching is a tutorial's: another type's folder is listed as it always was.

    **Test steps:**

    * open a reference-images record beside a video, and show its folder
    * verify no row has a progress, and no row action shows with the video selected
    """
    path = write_tutorial(tmp_path / "r", ("a.mp4",), resource_type="reference_images")
    records = Records()
    record = read_now(records, ResourceKey(path))
    model = delete_at_teardown(
        RehuDocumentModel(record.document, records=records, version=record.version, signature=record.signature)
    )
    view = FilesView(model)
    qtbot.addWidget(view)
    view.show()
    settle(qtbot, view)

    assert progress_of(view, "a.mp4") is None
    select(view, "a.mp4")
    assert (view.viewed_action.isVisible(), view.forget_action.isVisible()) == (False, False)


# endregion


# region what can be done to the selected row


def select(view: FilesView, name: str) -> None:
    """Select a row by its name.

    :param view: the view.
    :param name: the row's name.
    """
    table = view.findChild(QTableView, "file_view")
    assert isinstance(table, QTableView)
    table.selectRow(names(view).index(name))


def test_viewed_is_offered_for_a_video_and_for_no_other_row(model: RehuDocumentModel, view: FilesView) -> None:
    """The action is shown where it applies and hidden elsewhere, with its separator -- never merely disabled.

    **Test steps:**

    * with nothing selected, verify neither row action nor their separator is visible
    * select a video, and verify *Viewed* is visible and *Forget* is not
    * select a folder and verify nothing is visible
    """
    del model
    assert (view.viewed_action.isVisible(), view.forget_action.isVisible()) == (False, False)

    select(view, "a.mp4")
    assert (view.viewed_action.isVisible(), view.forget_action.isVisible()) == (True, False)

    select(view, "01 Basics")
    assert (view.viewed_action.isVisible(), view.forget_action.isVisible()) == (False, False)


def test_a_document_opened_as_a_placeholder_offers_viewed_once_its_record_is_read(
    tmp_path: Path, qtbot: QtBot, delete_at_teardown: DeleteAtTeardown
) -> None:
    """An ordinary open lists the folder before the record is read, while its type is not known: the listing is read
    again once it is, so the tutorial's videos carry their keys and *Viewed* is offered.

    **Test steps:**

    * open a tutorial as a pending placeholder, show the browser over it and let its first listing land
    * read the record, and let the listing it causes land
    * select a video and verify *Viewed* is visible
    """
    path = write_tutorial(tmp_path / "t", VIDEOS)
    model = delete_at_teardown(RehuDocumentModel.create_pending(path, records=Records()))
    view = FilesView(model)
    qtbot.addWidget(view)
    view.show()
    settle(qtbot, view)

    model.load_pending()
    qtbot.waitUntil(lambda: not model.pending, timeout=TIMEOUT)
    settle(qtbot, view)

    select(view, "a.mp4")
    assert view.viewed_action.isVisible()


def test_the_viewed_action_is_ticked_as_the_video_is_and_records_what_is_toggled(
    model: RehuDocumentModel, view: FilesView
) -> None:
    """The toolbar and menu action shows the video's flag, and toggling it records that at the resume point.

    **Test steps:**

    * play a video to 30 seconds and select it, and verify the action is not ticked
    * trigger it, and verify the entry is viewed at the same position and the action is ticked
    * trigger it again, and verify the entry is not viewed
    """
    model.record_progress("a.mp4", 30.0, 100.0)
    select(view, "a.mp4")
    assert view.viewed_action.isChecked() is False

    view.viewed_action.trigger()
    assert model.progress_of("a.mp4") == ProgressEntry(30.0, 100.0, True, 0)
    assert view.viewed_action.isChecked() is True

    view.viewed_action.trigger()
    entry = model.progress_of("a.mp4")
    assert entry is not None and (entry.position, entry.viewed) == (30.0, False)


def test_the_favorite_action_is_ticked_as_the_video_is_and_records_what_is_toggled(
    model: RehuDocumentModel, view: FilesView
) -> None:
    """The toolbar and menu action shows whether the video is starred, and toggling it records that.

    **Test steps:**

    * select a video never starred and verify the action is shown and not ticked
    * trigger it, and verify the model reports a favorite and the action is ticked
    * trigger it again, and verify the star is gone
    """
    select(view, "a.mp4")
    assert view.favorite_action.isVisible() is True
    assert view.favorite_action.isChecked() is False

    view.favorite_action.trigger()
    assert model.is_favorite("a.mp4") is True
    assert view.favorite_action.isChecked() is True

    view.favorite_action.trigger()
    assert model.is_favorite("a.mp4") is False


def test_a_video_never_opened_is_marked_viewed_from_its_start(model: RehuDocumentModel, view: FilesView) -> None:
    """A video watched elsewhere can be marked without being played.

    **Test steps:**

    * select a video never opened and trigger *Viewed*
    * verify an entry at position zero, viewed
    """
    select(view, "a.mp4")

    view.viewed_action.trigger()

    entry = model.progress_of("a.mp4")
    assert entry is not None and (entry.position, entry.viewed) == (0.0, True)


def test_the_context_menu_offers_what_the_toolbar_shows_and_nothing_for_a_row_with_no_actions(
    qtbot: QtBot, model: RehuDocumentModel, view: FilesView, mocker: MockerFixture
) -> None:
    """Right-clicking selects the row under the cursor and lists its visible actions; a row with none opens no menu.

    **Test steps:**

    * right-click below the last row and verify no menu opened
    * right-click a video, with the menu's exec patched to capture its actions, and verify only *Favorite* and
      *Viewed* are listed
    * make the video's progress missing, right-click its row, and verify *Favorite*, *Viewed* and *Forget* are listed
    * right-click a folder and verify no menu was opened
    """
    shown: list[list[str]] = []

    class ListingMenu:  # pylint: disable=invalid-name,missing-function-docstring
        """A menu that is never shown: it notes the actions it was given."""

        def __init__(self, _parent: object) -> None:
            self.actions: list[str] = []

        def addActions(self, actions: list[QAction]) -> None:  # noqa: N802  (Qt API name)
            self.actions = [action.text() for action in actions]

        def exec(self, _at: object) -> None:
            shown.append(self.actions)

        def deleteLater(self) -> None:  # noqa: N802  (Qt API name)
            pass

    mocker.patch.object(files_view, "QMenu", ListingMenu)
    table = view.findChild(QTableView, "file_view")
    assert isinstance(table, QTableView)

    def right_click(name: str) -> None:
        index = view.proxy.index(names(view).index(name), NAME_COLUMN)
        table.customContextMenuRequested.emit(table.visualRect(index).center())

    table.customContextMenuRequested.emit(QPoint(1, 100_000))
    assert not shown
    right_click("a.mp4")
    model.record_progress("gone.mp4", 10.0, 100.0)
    right_click("gone.mp4")
    count = len(shown)
    right_click("01 Basics")

    assert shown == [["Favorite", "Viewed"], ["Favorite", "Viewed", "Forget"]]
    assert len(shown) == count
    del qtbot


# endregion


# region the videos that are gone


def test_a_missing_video_is_listed_in_its_folder_and_forgotten_by_hand(
    model: RehuDocumentModel, view: FilesView, mocker: MockerFixture
) -> None:
    """A deleted video keeps its progress and its row until the reader forgets it; the row opens nothing.

    **Test steps:**

    * keep progress for a video that is not on disk, and look at the top folder
    * verify it is listed as *missing*, double-clicking it plays and opens nothing, *Forget* hidden until selected
    * select it and forget it
    * verify the row and the entry are gone, and *Forget* is hidden again
    """
    opened = mocker.patch.object(QDesktopServices, "openUrl")
    played: list[object] = []
    view.video_activated.connect(lambda *args: played.append(args))
    model.record_progress("gone.mp4", 10.0, 100.0)
    assert "gone.mp4" in names(view)
    row = names(view).index("gone.mp4")
    assert view.proxy.index(row, KIND_COLUMN).data() == "missing"
    assert view.forget_action.isVisible() is False

    view.activate(row)
    assert opened.call_count == 0
    assert not played

    table = view.findChild(QTableView, "file_view")
    assert table is not None
    table.selectRow(row)
    assert view.forget_action.isVisible() is True

    view.forget_action.trigger()

    assert "gone.mp4" not in names(view)
    assert model.progress_of("gone.mp4") is None
    assert view.forget_action.isVisible() is False


def test_a_deleted_video_with_only_a_note_is_listed_as_missing_and_forgotten_by_hand(
    model: RehuDocumentModel, view: FilesView
) -> None:
    """Deleting a video once watched and keeping its notes is the ordinary workflow ([[field-schema#video-notes]]):
    a note or a favorite keeps the row as a progress entry does, and Forget takes them together.

    **Test steps:**

    * note and star a video that is not on disk, with no progress on it, and look at the top folder
    * verify it is listed as *missing*
    * select it and forget it
    * verify the row, the note and the favorite are gone
    """
    model.record_notes(video_notes={"gone.mp4": "kept"}, favorites={"gone.mp4": True})

    assert "gone.mp4" in names(view)
    row = names(view).index("gone.mp4")
    assert view.proxy.index(row, KIND_COLUMN).data() == "missing"

    table = view.findChild(QTableView, "file_view")
    assert table is not None
    table.selectRow(row)
    view.forget_action.trigger()

    assert "gone.mp4" not in names(view)
    assert (model.video_notes_of("gone.mp4"), model.is_favorite("gone.mp4")) == ("", False)


# endregion


# region listing the files


def test_listing_the_files_asks_for_renamed_videos_to_take_their_progress(
    qtbot: QtBot, model: RehuDocumentModel, view: FilesView, mocker: MockerFixture
) -> None:
    """A refresh is when a rename is noticed ([[field-schema#watch-progress]]).

    **Test steps:**

    * spy on the model's move of renamed progress and refresh the view
    * verify it was asked once
    """
    moved = mocker.spy(model, "reattach_renamed_progress")

    view.refresh()
    settle(qtbot, view)

    assert moved.call_count == 1


def test_a_folder_is_walked_into_with_its_own_progress(qtbot: QtBot, model: RehuDocumentModel, view: FilesView) -> None:
    """The videos inside a folder carry their own percentages, as the folder row carries the sum.

    **Test steps:**

    * play a video inside a folder and walk into it
    * verify its row reads the share
    """
    model.record_progress("01 Basics/b.mp4", 30.0, 60.0)

    go_into(qtbot, view, "01 Basics")

    assert progress_of(view, "b.mp4").text == "50%"
    assert Qt.ItemFlag.ItemIsEnabled & view.proxy.flags(view.proxy.index(0, NAME_COLUMN))


# endregion
