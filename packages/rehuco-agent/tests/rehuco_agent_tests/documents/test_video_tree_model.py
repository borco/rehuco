"""Tests for the tutorial's videos as a tree (#572, [[plugins#video-tree]]).

A real document over a real tutorial under ``tmp_path``: what is tested is which rows the tree makes from the videos
and the user's data, and what each cell says; the progress words are the Files rows' own and tested there.
"""

from pathlib import Path
from typing import Any, Final
from unittest.mock import Mock

from PySide6.QtCore import QModelIndex, Qt
from pytest import mark
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.clock_text import clock_text
from rehuco_agent.documents.files_progress import MISSING_TOOLTIP, FilesProgress
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.documents.video_tree_model import (
    FAVORITE_COLUMN,
    KEY_ROLE,
    KIND_ROLE,
    LENGTH_COLUMN,
    MISSING_ROLE,
    NAME_COLUMN,
    PROGRESS_COLUMN,
    SECONDS_ROLE,
    TOOLTIP_COLUMNS,
    TOOLTIP_LINES,
    NodeKind,
    VideoTreeModel,
)
from rehuco_agent.glyphs import FAVORITE_GLYPH

from .video_tree_support import KEYS, fixture_model  # noqa: F401  # pylint: disable=unused-import

pytestmark = mark.usefixtures("real_path_stat")

BOOKMARK: Final = "- [1:05](rehuco-video:a.mp4#t=65) the first trick"


def tree_of(model: RehuDocumentModel) -> VideoTreeModel:
    """A tree over the document with the tutorial's videos listed.

    :param model: the document.
    :returns: the tree.
    """
    tree = VideoTreeModel(model, model)
    tree.set_videos(KEYS)
    return tree


def rows(tree: VideoTreeModel, parent: QModelIndex | None = None, depth: int = 0) -> list[str]:
    """The tree flattened to indented names.

    :param tree: the tree.
    :param parent: where to start, the top by default.
    :param depth: how deep ``parent`` is.
    :returns: one entry per row, two spaces per level.
    """
    parent = parent if parent is not None else QModelIndex()
    found = []
    for row in range(tree.rowCount(parent)):
        index = tree.index(row, NAME_COLUMN, parent)
        found.append("  " * depth + str(index.data()))
        found.extend(rows(tree, index, depth + 1))
    return found


def cell(tree: VideoTreeModel, key: str, column: int, role: int = Qt.ItemDataRole.DisplayRole) -> Any:  # noqa: ANN401
    """What a cell of a video's row holds.

    :param tree: the tree.
    :param key: the video's content key.
    :param column: the column.
    :param role: the role.
    :returns: the data.
    """
    return tree.index_of_video(key).siblingAtColumn(column).data(role)


def test_the_tree_is_folders_and_videos_in_natural_order_without_extensions(model: RehuDocumentModel) -> None:
    """**Test steps:**

    * list the tutorial's four videos
    * verify the folders hold their videos and the names have no extension
    """
    assert rows(tree_of(model)) == ["01 Basics", "  b", "  c", "02 More", "  d", "a"]


def test_nothing_is_listed_until_the_videos_are_known(model: RehuDocumentModel) -> None:
    """**Test steps:**

    * make the tree without telling it the videos
    * verify it is empty, and that it fills once they are given and empties again for ``None``
    """
    tree = VideoTreeModel(model, model)
    assert not rows(tree)

    tree.set_videos(KEYS)
    assert tree.rowCount() == 3

    tree.set_videos(None)
    assert tree.rowCount() == 0


def test_a_video_with_only_data_is_listed_in_its_folder_as_missing(model: RehuDocumentModel) -> None:
    """**Test steps:**

    * record progress for a video of a folder that is not on disk
    * verify it is listed in that folder, in order, marked missing and italic, saying why on hover
    * verify a note line under a missing video does not make the video present
    """
    model.record_progress("01 Basics/bb.mp4", 10.0, 100.0)
    tree = tree_of(model)

    assert rows(tree) == ["01 Basics", "  b", "  bb", "  c", "02 More", "  d", "a"]
    assert cell(tree, "01 Basics/bb.mp4", NAME_COLUMN, MISSING_ROLE) is True
    assert cell(tree, "01 Basics/b.mp4", NAME_COLUMN, MISSING_ROLE) is False
    assert cell(tree, "01 Basics/bb.mp4", NAME_COLUMN, Qt.ItemDataRole.FontRole).italic() is True
    assert MISSING_TOOLTIP in str(cell(tree, "01 Basics/bb.mp4", NAME_COLUMN, Qt.ItemDataRole.ToolTipRole))


def test_a_video_with_a_note_and_no_progress_is_listed_missing_too(model: RehuDocumentModel) -> None:
    """**Test steps:**

    * write a bookmark for a video that is not on disk
    * verify the video is listed, missing, with its bookmark beneath it
    """
    model.record_notes(video_notes={"gone.mp4": "- [0:01](rehuco-video:gone.mp4#t=1) kept"})
    tree = tree_of(model)

    assert rows(tree) == ["01 Basics", "  b", "  c", "02 More", "  d", "a", "gone", "  0:01 kept"]
    assert cell(tree, "gone.mp4", NAME_COLUMN, MISSING_ROLE) is True


def test_a_videos_bookmarks_are_its_children_sorted_by_time(model: RehuDocumentModel) -> None:
    """The notes may be in any order -- the user edits them -- so the tree sorts them; a line with no time is not a row.

    **Test steps:**

    * write a note of a later bookmark, a plain line, a blank line and an earlier bookmark
    * verify a child per bookmark, earliest first, each reading its time and text, and none for the plain line
    * verify a bookmark row answers its link's video and time
    """
    model.record_notes(video_notes={"a.mp4": f"- [0:09](rehuco-video:a.mp4#t=9) later\nplain\n\n{BOOKMARK}"})
    tree = tree_of(model)

    assert rows(tree)[-3:] == ["a", "  0:09 later", "  1:05 the first trick"]
    video = tree.index_of_video("a.mp4")
    first = tree.index(0, NAME_COLUMN, video)
    assert (first.data(KIND_ROLE), first.data(KEY_ROLE), first.data(SECONDS_ROLE)) == (NodeKind.NOTE, "a.mp4", 9.0)
    assert tree.rowCount(first) == 0
    assert tree.index(0, PROGRESS_COLUMN, video).data() == ""


def test_a_note_line_for_a_video_not_in_the_tutorial_reads_missing(model: RehuDocumentModel) -> None:
    """**Test steps:**

    * write a bookmark whose link names a video the tutorial does not have
    * verify the line is a missing target, so nothing plays from it
    """
    model.record_notes(video_notes={"a.mp4": "- [0:01](rehuco-video:nowhere.mp4#t=1) x"})
    tree = tree_of(model)

    line = tree.index(0, NAME_COLUMN, tree.index_of_video("a.mp4"))
    assert line.data(MISSING_ROLE) is True


def test_a_long_note_line_has_a_capped_tooltip(model: RehuDocumentModel) -> None:
    """**Test steps:**

    * write a note line far longer than the tooltip allows
    * verify its tooltip is cut to the allowed lines of the allowed width, ending in an ellipsis
    * verify a short line is shown whole
    """
    model.record_notes(video_notes={"a.mp4": "- [0:01](rehuco-video:a.mp4#t=1) " + "word " * 1000})
    tree = tree_of(model)

    tooltip = str(tree.index(0, NAME_COLUMN, tree.index_of_video("a.mp4")).data(Qt.ItemDataRole.ToolTipRole))
    lines = tooltip.split("\n")
    assert len(lines) == TOOLTIP_LINES
    assert lines[-1].endswith("…")
    assert all(len(line) <= TOOLTIP_COLUMNS + 1 for line in lines)
    assert VideoTreeModel.tooltip_text("short one") == "short one"


def test_the_progress_column_says_what_the_files_rows_say(model: RehuDocumentModel) -> None:
    """**Test steps:**

    * give one video a measured length and a position, another viewed, another neither
    * verify each video and folder reads the same words and tooltip as the shared formatter gives
    """
    model.record_progress("a.mp4", 30.0, 120.0)
    model.record_progress("01 Basics/b.mp4", 120.0, 120.0, viewed=True)
    tree = tree_of(model)
    path = model.path
    assert path is not None
    progress = FilesProgress(
        path.parent, model.progress_entries(), model.measured_videos(), KEYS, model.video_data_keys()
    )

    for key in KEYS:
        expected = progress.for_video(key)
        assert cell(tree, key, PROGRESS_COLUMN) == expected.text
        assert cell(tree, key, PROGRESS_COLUMN, Qt.ItemDataRole.ToolTipRole) == expected.tooltip
    folder = tree.index(0, PROGRESS_COLUMN)
    expected_folder = progress.for_folder(path.parent / "01 Basics")
    assert expected_folder is not None
    assert (folder.data(), folder.data(Qt.ItemDataRole.ToolTipRole)) == (expected_folder.text, expected_folder.tooltip)
    assert cell(tree, "a.mp4", PROGRESS_COLUMN) == "25%"
    assert cell(tree, "01 Basics/b.mp4", PROGRESS_COLUMN) == "100%"


def test_the_length_column_reads_a_clock_and_is_empty_when_unknown(model: RehuDocumentModel) -> None:
    """**Test steps:**

    * record progress with a length for one video
    * verify its length reads as a clock, and a video with no length and a folder read nothing
    """
    model.record_progress("a.mp4", 1.0, 3725.0)
    tree = tree_of(model)

    assert cell(tree, "a.mp4", LENGTH_COLUMN) == clock_text(3_725_000) == "1:02:05"
    assert cell(tree, "01 Basics/b.mp4", LENGTH_COLUMN) == ""
    assert tree.index(0, LENGTH_COLUMN).data() == ""


def test_a_starred_video_shows_a_star(model: RehuDocumentModel) -> None:
    """**Test steps:**

    * star one video
    * verify its favorite cell reads the star glyph, in the icon font, and another's reads nothing
    """
    model.record_notes(favorites={"a.mp4": True})
    tree = tree_of(model)

    assert cell(tree, "a.mp4", FAVORITE_COLUMN) == FAVORITE_GLYPH.codepoint
    assert cell(tree, "a.mp4", FAVORITE_COLUMN, Qt.ItemDataRole.FontRole).family() == FAVORITE_GLYPH.family
    assert cell(tree, "01 Basics/b.mp4", FAVORITE_COLUMN) == ""
    assert tree.index(0, FAVORITE_COLUMN).data() == ""


def test_the_player_video_is_bold_and_the_mark_moves(model: RehuDocumentModel, qtbot: QtBot) -> None:
    """**Test steps:**

    * mark a video current and verify it is bold, with a change reported for its row
    * mark another and verify the first is plain again
    * clear the mark and verify none is bold
    """
    tree = tree_of(model)

    def bold(key: str) -> bool:
        return cell(tree, key, NAME_COLUMN, Qt.ItemDataRole.FontRole).bold()

    with qtbot.waitSignal(tree.dataChanged):
        tree.set_current("a.mp4")
    assert (bold("a.mp4"), bold("01 Basics/b.mp4"), tree.current_key) == (True, False, "a.mp4")

    tree.set_current("01 Basics/b.mp4")
    assert (bold("a.mp4"), bold("01 Basics/b.mp4")) == (False, True)

    tree.set_current(None)
    assert not any(bold(key) for key in KEYS)


def test_a_change_of_progress_redraws_in_place_without_a_reset(model: RehuDocumentModel, qtbot: QtBot) -> None:
    """The player writes progress every few seconds: that must not collapse what the reader has open.

    **Test steps:**

    * record progress for a video already listed
    * verify the rows' data changed, no reset happened, and the new words show
    """
    tree = tree_of(model)
    resets = []
    tree.modelReset.connect(lambda: resets.append(1))

    with qtbot.waitSignal(tree.dataChanged):
        model.record_progress("a.mp4", 30.0, 120.0)

    assert not resets
    assert cell(tree, "a.mp4", PROGRESS_COLUMN) == "25%"


def test_a_change_in_the_rows_resets_the_model(model: RehuDocumentModel, qtbot: QtBot) -> None:
    """**Test steps:**

    * write a note, then change it, then clear it
    * verify each change of the lines is a reset with the new rows
    """
    tree = tree_of(model)

    with qtbot.waitSignal(tree.modelReset):
        model.record_notes(video_notes={"a.mp4": "- [0:01](rehuco-video:a.mp4#t=1) one"})
    assert rows(tree)[-2:] == ["a", "  0:01 one"]

    with qtbot.waitSignal(tree.modelReset):
        model.record_notes(
            video_notes={"a.mp4": "- [0:02](rehuco-video:a.mp4#t=2) two\n- [0:03](rehuco-video:a.mp4#t=3) three"}
        )
    assert rows(tree)[-3:] == ["a", "  0:02 two", "  0:03 three"]

    with qtbot.waitSignal(tree.modelReset):
        model.record_notes(video_notes={"a.mp4": ""})
    assert rows(tree)[-1] == "a"


def test_forgetting_a_missing_video_removes_its_row(model: RehuDocumentModel, qtbot: QtBot) -> None:
    """**Test steps:**

    * list a missing video, then forget it
    * verify the row is gone
    """
    model.record_progress("gone.mp4", 1.0, 10.0)
    tree = tree_of(model)
    assert "gone" in rows(tree)

    with qtbot.waitSignal(tree.modelReset):
        model.forget_progress("gone.mp4")

    assert "gone" not in rows(tree)


@mark.parametrize("key", ["a.mp4", "01 Basics/b.mp4"])
def test_a_video_is_found_by_its_key_and_a_stranger_is_not(model: RehuDocumentModel, key: str) -> None:
    """**Test steps:**

    * look up a listed video, and one that is not
    * verify the first has an index, parented as the folders say, and the second none
    """
    tree = tree_of(model)

    index = tree.index_of_video(key)
    assert index.isValid() and index.data(KEY_ROLE) == key
    assert not tree.index_of_video("nowhere.mp4").isValid()


def test_the_model_answers_the_basics_of_an_item_model(model: RehuDocumentModel) -> None:
    """**Test steps:**

    * ask for a header, a cell out of range, a data role it has no answer for, and a cell's alignment
    * verify the headers, no index, no data, and right alignment for the numbers
    """
    tree = tree_of(model)

    assert tree.headerData(NAME_COLUMN, Qt.Orientation.Horizontal) == "Name"
    assert tree.headerData(0, Qt.Orientation.Vertical) is None
    assert not tree.index(99, 0).isValid()
    assert tree.index(0, 0).data(Qt.ItemDataRole.CheckStateRole) is None
    assert tree.data(QModelIndex()) is None
    assert cell(tree, "a.mp4", FAVORITE_COLUMN, Qt.ItemDataRole.ToolTipRole) == ""
    assert tree.rowCount(tree.index(0, PROGRESS_COLUMN)) == 0
    assert tree.parent(tree.index(0, 0)) == QModelIndex()
    assert tree.parent(tree.index(0, 0, tree.index(0, 0))).row() == 0
    assert tree.index(0, PROGRESS_COLUMN).data(Qt.ItemDataRole.TextAlignmentRole) & Qt.AlignmentFlag.AlignRight


def test_a_detached_tree_stops_following_the_document(model: RehuDocumentModel, qtbot: QtBot) -> None:
    """**Test steps:**

    * detach the tree and record progress
    * verify the tree reported nothing
    """
    tree = tree_of(model)
    tree.detach()

    with qtbot.assertNotEmitted(tree.dataChanged):
        model.record_progress("a.mp4", 30.0, 120.0)


def test_a_standalone_records_video_reads_as_the_records_name(tmp_path: Path, qtbot: QtBot) -> None:
    """A standalone record keys its one video by its extension alone, so the name comes from the file the key names.

    **Test steps:**

    * make a tree over a standalone record whose video key is ``.mp4``
    * verify the row reads the record's name with no extension
    """
    del qtbot
    model = Mock(spec=RehuDocumentModel)
    model.path = tmp_path / "My Tutorial.rehu"
    model.video_data_keys.return_value = set()
    model.video_notes_of.return_value = ""
    model.is_favorite.return_value = False
    model.progress_entries.return_value = {}
    model.measured_videos.return_value = {}
    tree = VideoTreeModel(model)

    tree.set_videos((".mp4",))

    assert rows(tree) == ["My Tutorial"]
    assert tree.index_of_video(".mp4").data(KEY_ROLE) == ".mp4"
