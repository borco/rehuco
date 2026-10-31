"""Tests for the tree sub-dock's view (#572, [[plugins#video-tree]]).

A real tutorial under ``tmp_path``, listed by the real lister: what is tested is when the view reads, what a
double-click reports, what a row offers, and what survives a redraw.
"""

from pathlib import Path
from typing import Final
from unittest.mock import Mock

from PySide6.QtCore import QModelIndex, QPoint
from PySide6.QtWidgets import QTreeView
from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents import video_tree_view
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.documents.video_tree_model import KEY_ROLE, NAME_COLUMN
from rehuco_agent.documents.video_tree_view import VideoTreeView
from rehuco_agent.resource_events import ResourceEvents
from rehuco_core import RehuDocument
from rehuco_core.access import ResourceKey

from .video_tree_support import fixture_model  # noqa: F401  # pylint: disable=unused-import

pytestmark = mark.usefixtures("real_path_stat")

TIMEOUT: Final = 5000

BOOKMARK: Final = "- [1:05](rehuco-video:01%20Basics/c.mp4#t=65) the trick"


@fixture(name="events")
def fixture_events(qtbot: QtBot) -> ResourceEvents:
    """The app's change feed, as a window would own it.

    :param qtbot: pytest-qt fixture.
    :returns: the feed.
    """
    del qtbot
    return ResourceEvents()


@fixture(name="view")
def fixture_view(qtbot: QtBot, model: RehuDocumentModel, events: ResourceEvents) -> VideoTreeView:
    """A shown tree over the tutorial, its first listing landed.

    :param qtbot: pytest-qt fixture.
    :param model: the document.
    :param events: the change feed.
    :returns: the view.
    """
    view = VideoTreeView(model, resource_events=events)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitUntil(lambda: view.tree.rowCount() > 0, timeout=TIMEOUT)
    return view


def tree_of(view: VideoTreeView) -> QTreeView:
    """The widget's tree.

    :param view: the view.
    :returns: its `QTreeView`.
    """
    found = view.findChild(QTreeView, "tree_view")
    assert isinstance(found, QTreeView)
    return found


def index_named(view: VideoTreeView, *names: str) -> QModelIndex:
    """A row, found by the names down to it.

    :param view: the view.
    :param names: the names from the top.
    :returns: the row's index.
    """
    index = QModelIndex()
    for name in names:
        rows = range(view.tree.rowCount(index))
        index = next(
            view.tree.index(row, NAME_COLUMN, index) for row in rows if view.tree.index(row, 0, index).data() == name
        )
    return index


def double_click(view: VideoTreeView, index: QModelIndex) -> None:
    """Double-click a row.

    :param view: the view.
    :param index: the row.
    """
    tree_of(view).doubleClicked.emit(index)


def test_a_hidden_view_reads_nothing_until_it_is_shown(
    qtbot: QtBot, model: RehuDocumentModel, mocker: MockerFixture
) -> None:
    """**Test steps:**

    * ask a view that was never shown to refresh, with the lister's start watched
    * verify nothing was listed and the tree is empty
    * show it and verify the listing is caught up
    """
    view = VideoTreeView(model)
    qtbot.addWidget(view)
    start = mocker.spy(view._VideoTreeView__lister, "start")  # type: ignore[attr-defined]  # pylint: disable=protected-access

    view.refresh()
    assert start.call_count == 0 and view.tree.rowCount() == 0

    view.show()
    qtbot.waitUntil(lambda: view.tree.rowCount() == 3, timeout=TIMEOUT)
    assert start.call_count == 1


def test_the_tree_is_listed_and_everything_is_open(view: VideoTreeView) -> None:
    """**Test steps:**

    * list the tutorial
    * verify every folder is expanded
    """
    tree = tree_of(view)

    assert tree.isExpanded(index_named(view, "01 Basics"))
    assert tree.isExpanded(index_named(view, "02 More"))
    assert tree.isRowHidden(0, QModelIndex()) is False


def test_a_tree_for_a_document_that_records_no_progress_stays_empty(qtbot: QtBot, events: ResourceEvents) -> None:
    """**Test steps:**

    * show a view over a collection
    * verify nothing is listed
    """
    model = RehuDocumentModel(RehuDocument({"type": "Collection", "sources": []}))
    view = VideoTreeView(model, resource_events=events)
    qtbot.addWidget(view)
    view.show()

    events.changed.emit((ResourceKey(Path(Path.cwd().anchor) / "elsewhere" / "x.mp4"),))

    assert view.tree.rowCount() == 0


def test_a_video_double_click_reports_it_with_no_position(view: VideoTreeView, qtbot: QtBot) -> None:
    """**Test steps:**

    * double-click a video
    * verify its key was reported with no time
    """
    with qtbot.waitSignal(view.video_activated) as signal:
        double_click(view, index_named(view, "01 Basics", "b"))

    assert signal.args == ["01 Basics/b.mp4", None]


def test_a_bookmark_double_click_reports_its_video_and_time(
    view: VideoTreeView, model: RehuDocumentModel, qtbot: QtBot
) -> None:
    """**Test steps:**

    * write a bookmark under one video, linking another
    * double-click the bookmark and verify the link's video and time are reported
    """
    model.record_notes(video_notes={"a.mp4": BOOKMARK})

    with qtbot.waitSignal(view.video_activated) as bookmark:
        double_click(view, index_named(view, "a", "1:05 the trick"))

    assert bookmark.args == ["01 Basics/c.mp4", 65.0]


def test_a_folder_double_click_opens_and_closes_it_and_a_missing_video_reports_nothing(
    view: VideoTreeView, model: RehuDocumentModel, qtbot: QtBot
) -> None:
    """**Test steps:**

    * double-click a folder twice and verify it closes then opens
    * give a video no file and double-click it
    * verify nothing was reported
    """
    tree = tree_of(view)
    folder = index_named(view, "01 Basics")

    double_click(view, folder)
    assert tree.isExpanded(folder) is False
    double_click(view, folder)
    assert tree.isExpanded(folder) is True

    model.record_progress("gone.mp4", 1.0, 10.0)
    view.refresh()
    qtbot.waitUntil(lambda: view.tree.index_of_video("gone.mp4").isValid(), timeout=TIMEOUT)
    with qtbot.assertNotEmitted(view.video_activated):
        double_click(view, view.tree.index_of_video("gone.mp4"))


def test_what_the_reader_closed_stays_closed_and_the_selection_stays_across_a_note_edit(
    view: VideoTreeView, model: RehuDocumentModel, qtbot: QtBot
) -> None:
    """**Test steps:**

    * close a folder and a video's row, and select a video
    * edit a note, which resets the tree
    * verify the closed rows are still closed, the others open, and the selection stayed
    """
    model.record_notes(video_notes={"a.mp4": "- [0:01](rehuco-video:a.mp4#t=1) one"})
    tree = tree_of(view)
    tree.collapse(index_named(view, "01 Basics"))
    tree.collapse(index_named(view, "a"))
    tree.setCurrentIndex(index_named(view, "02 More", "d"))

    with qtbot.waitSignal(view.tree.modelReset):
        model.record_notes(video_notes={"a.mp4": "- [0:01](rehuco-video:a.mp4#t=1) two"})

    assert tree.isExpanded(index_named(view, "01 Basics")) is False
    assert tree.isExpanded(index_named(view, "a")) is False
    assert tree.isExpanded(index_named(view, "02 More")) is True
    assert tree.currentIndex().data(KEY_ROLE) == "02 More/d.mp4"


def test_a_reader_opening_a_row_again_forgets_it_was_closed(
    view: VideoTreeView, model: RehuDocumentModel, qtbot: QtBot
) -> None:
    """**Test steps:**

    * close and reopen a folder, then edit a note
    * verify the folder is open after the reset
    """
    tree = tree_of(view)
    tree.collapse(index_named(view, "01 Basics"))
    tree.expand(index_named(view, "01 Basics"))

    with qtbot.waitSignal(view.tree.modelReset):
        model.record_notes(video_notes={"a.mp4": "- [0:01](rehuco-video:a.mp4#t=1) x"})

    assert tree.isExpanded(index_named(view, "01 Basics")) is True


def test_setting_the_current_video_opens_the_way_to_it_and_scrolls(view: VideoTreeView, mocker: MockerFixture) -> None:
    """**Test steps:**

    * close a folder, then mark a video inside it current
    * verify the folder opened and the view was scrolled to the video
    """
    tree = tree_of(view)
    tree.collapse(index_named(view, "01 Basics"))
    scroll = mocker.spy(tree, "scrollTo")

    view.set_current("01 Basics/c.mp4")

    assert tree.isExpanded(index_named(view, "01 Basics")) is True
    assert scroll.call_args.args[0].data(KEY_ROLE) == "01 Basics/c.mp4"  # pylint: disable=no-member
    view.set_current("nowhere.mp4")
    view.set_current(None)


def test_the_row_actions_follow_the_selection(view: VideoTreeView, model: RehuDocumentModel) -> None:
    """**Test steps:**

    * select a folder and verify no action shows
    * select a video and verify Favorite and Viewed show
    * select a note line and verify the actions are its video's
    * select a missing video and verify Forget shows too
    """
    model.record_progress("gone.mp4", 1.0, 10.0)
    model.record_notes(video_notes={"a.mp4": "- [0:01](rehuco-video:a.mp4#t=1) one"})
    view.refresh()
    tree = tree_of(view)
    actions = view.row_actions

    tree.setCurrentIndex(index_named(view, "01 Basics"))
    assert actions.any_visible is False

    tree.setCurrentIndex(index_named(view, "a"))
    assert (actions.favorite_action.isVisible(), actions.forget_action.isVisible()) == (True, False)

    model.record_notes(favorites={"a.mp4": True})
    tree.setCurrentIndex(index_named(view, "a", "0:01 one"))
    assert actions.favorite_action.isChecked() is True

    tree.setCurrentIndex(view.tree.index_of_video("gone.mp4"))
    assert actions.forget_action.isVisible() is True
    assert view.title_bar_actions == list(actions.actions)


def test_the_context_menu_lists_the_visible_actions_and_nothing_for_a_folder(
    view: VideoTreeView, mocker: MockerFixture
) -> None:
    """**Test steps:**

    * right-click below the last row and a folder, with the menu patched, and verify no menu opened
    * right-click a video and verify its actions were listed
    """
    shown: list[list[str]] = []

    class ListingMenu:  # pylint: disable=invalid-name,missing-function-docstring
        """A menu that is never shown: it notes the actions it was given."""

        def __init__(self, _parent: object) -> None:
            self.actions: list[str] = []

        def addActions(self, actions: list) -> None:  # noqa: N802  (Qt API name)
            self.actions = [action.text() for action in actions]

        def exec(self, _at: object) -> None:
            shown.append(self.actions)

        def deleteLater(self) -> None:  # noqa: N802  (Qt API name)
            pass

    mocker.patch.object(video_tree_view, "QMenu", ListingMenu)
    tree = tree_of(view)

    def right_click(index: QModelIndex) -> None:
        tree.customContextMenuRequested.emit(tree.visualRect(index).center())

    tree.customContextMenuRequested.emit(QPoint(1, 100_000))
    right_click(index_named(view, "01 Basics"))
    assert not shown

    right_click(index_named(view, "a"))
    assert shown == [["Favorite", "Viewed"]]


def test_a_change_beneath_the_tutorials_folder_lists_again_and_one_elsewhere_does_not(
    view: VideoTreeView, model: RehuDocumentModel, events: ResourceEvents, mocker: MockerFixture
) -> None:
    """**Test steps:**

    * announce a changed file and a changed folder beneath the tutorial, and verify each lists again
    * announce ones elsewhere and verify nothing lists
    """
    path = model.path
    assert path is not None
    refresh = mocker.spy(view, "refresh")
    refresh.reset_mock()

    events.changed.emit((ResourceKey(path.parent / "a.mp4"),))
    events.folder_changed.emit(ResourceKey(path.parent / "01 Basics"))
    assert refresh.call_count == 2

    elsewhere = Path(path.anchor) / "elsewhere" / "x.mp4"
    events.changed.emit((ResourceKey(elsewhere),))
    events.folder_changed.emit(ResourceKey(elsewhere.parent))
    assert refresh.call_count == 2


def test_a_detached_view_stops_following_the_document(view: VideoTreeView, model: RehuDocumentModel) -> None:
    """**Test steps:**

    * detach the view and write a note
    * verify the tree did not change
    """
    view.detach()
    before = view.tree.rowCount(view.tree.index_of_video("a.mp4"))

    model.record_notes(video_notes={"a.mp4": "- [0:01](rehuco-video:a.mp4#t=1) one"})

    assert view.tree.rowCount(view.tree.index_of_video("a.mp4")) == before


def test_a_view_shown_again_does_not_list_again_and_a_listing_that_fails_empties_the_tree(
    view: VideoTreeView, mocker: MockerFixture, qtbot: QtBot
) -> None:
    """**Test steps:**

    * hide the view and show it again, and verify nothing was listed again
    * make the listing fail and refresh
    * verify the failure was logged as a warning and the tree is empty
    """
    refresh = mocker.spy(view, "refresh")
    view.hide()
    view.show()
    assert refresh.call_count == 0

    mocker.patch.object(video_tree_view, "tutorial_video_keys", side_effect=OSError("share is away"))
    warning = mocker.patch.object(video_tree_view.LOG, "warning")
    view.refresh()

    qtbot.waitUntil(lambda: warning.call_count == 1, timeout=TIMEOUT)
    assert view.tree.rowCount() == 0


def test_a_rename_touching_the_tutorials_folder_lists_again_and_one_elsewhere_does_not(
    view: VideoTreeView, events: ResourceEvents, mocker: MockerFixture
) -> None:
    """**Test steps:**

    * announce a rename whose plan touches the tutorial's folder and verify the view lists again
    * announce one that does not and verify it did not
    """
    refresh = mocker.spy(view, "refresh")
    touching = Mock()
    touching.to_local.return_value.touches.return_value = True
    elsewhere = Mock()
    elsewhere.to_local.return_value.touches.return_value = False

    events.moved.emit(touching)
    assert refresh.call_count == 1
    events.moved.emit(elsewhere)
    assert refresh.call_count == 1


def test_a_closed_folder_below_the_top_stays_closed_and_a_forgotten_one_and_its_selection_are_let_go(
    view: VideoTreeView, model: RehuDocumentModel, qtbot: QtBot
) -> None:
    """**Test steps:**

    * list a missing video two folders down, select it, then close its folder
    * edit a note and verify that folder is still closed
    * forget the video and verify the tree rebuilt with the folder, the selection and the memory of it gone
    """
    key = "01 Basics/deep/x.mp4"
    model.record_progress(key, 1.0, 10.0)
    view.refresh()
    qtbot.waitUntil(lambda: view.tree.index_of_video(key).isValid(), timeout=TIMEOUT)
    tree = tree_of(view)
    tree.setCurrentIndex(view.tree.index_of_video(key))
    tree.collapse(index_named(view, "01 Basics", "deep"))

    with qtbot.waitSignal(view.tree.modelReset):
        model.record_notes(video_notes={"a.mp4": "- [0:01](rehuco-video:a.mp4#t=1) one"})
    assert tree.isExpanded(index_named(view, "01 Basics", "deep")) is False

    with qtbot.waitSignal(view.tree.modelReset):
        model.forget_progress(key)
    assert not view.tree.index_of_video(key).isValid()
    assert not tree.currentIndex().isValid() or tree.currentIndex().data(KEY_ROLE) != key


def test_the_ticks_follow_a_redraw_in_place(view: VideoTreeView, model: RehuDocumentModel) -> None:
    """The player marks a video viewed as it ends and the Files dock stars one, both redraws in place: the selected
    row's actions must say so, or a click would undo what just happened.

    **Test steps:**

    * select a video and verify Viewed and Favorite are unticked
    * record it viewed and star it through the model, as the player and the Files dock do
    * verify both are ticked
    """
    tree_of(view).setCurrentIndex(index_named(view, "a"))
    actions = view.row_actions
    assert (actions.viewed_action.isChecked(), actions.favorite_action.isChecked()) == (False, False)

    model.record_progress("a.mp4", 100.0, 100.0, viewed=True)
    model.record_notes(favorites={"a.mp4": True})

    assert (actions.viewed_action.isChecked(), actions.favorite_action.isChecked()) == (True, True)


def test_a_selected_bookmark_stays_with_its_own_video_across_a_rebuild(
    view: VideoTreeView, model: RehuDocumentModel, qtbot: QtBot
) -> None:
    """**Test steps:**

    * select a bookmark under one video whose link names another, then edit a note
    * verify the selection comes back on the bookmark's own video, not the linked one
    """
    model.record_notes(video_notes={"a.mp4": BOOKMARK})
    tree_of(view).setCurrentIndex(index_named(view, "a", "1:05 the trick"))

    with qtbot.waitSignal(view.tree.modelReset):
        model.record_notes(video_notes={"02 More/d.mp4": "- [0:01](rehuco-video:02%20More/d.mp4#t=1) x"})

    assert tree_of(view).currentIndex().data(KEY_ROLE) == "a.mp4"


def test_a_rebuild_keeps_the_readers_place_rather_than_the_players(
    view: VideoTreeView, model: RehuDocumentModel, qtbot: QtBot, mocker: MockerFixture
) -> None:
    """**Test steps:**

    * mark a video in a folder current, then close that folder
    * edit a note, which rebuilds the tree
    * verify the folder stays closed and nothing was scrolled to
    """
    view.set_current("01 Basics/c.mp4")
    tree = tree_of(view)
    tree.collapse(index_named(view, "01 Basics"))
    scroll = mocker.spy(tree, "scrollTo")

    with qtbot.waitSignal(view.tree.modelReset):
        model.record_notes(video_notes={"a.mp4": "- [0:01](rehuco-video:a.mp4#t=1) x"})

    assert tree.isExpanded(index_named(view, "01 Basics")) is False
    assert scroll.call_count == 0


def test_a_click_reports_the_video_of_a_row_or_of_a_line_of_its_notes_and_a_folder_none(
    view: VideoTreeView, model: RehuDocumentModel, qtbot: QtBot
) -> None:
    """**Test steps:**

    * write a bookmark under one video
    * click the video and the bookmark and verify each reported its own video -- the bookmark's the video whose notes
      hold it, not the one its link names
    * click a folder and verify nothing was reported
    """
    model.record_notes(video_notes={"a.mp4": BOOKMARK})
    tree = tree_of(view)

    with qtbot.waitSignal(view.video_clicked) as video:
        tree.clicked.emit(index_named(view, "01 Basics", "b"))
    with qtbot.waitSignal(view.video_clicked) as note:
        tree.clicked.emit(index_named(view, "a", "1:05 the trick"))
    with qtbot.assertNotEmitted(view.video_clicked):
        tree.clicked.emit(index_named(view, "01 Basics"))

    assert video.args == ["01 Basics/b.mp4"]
    assert note.args == ["a.mp4"]
