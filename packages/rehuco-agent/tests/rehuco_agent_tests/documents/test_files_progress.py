"""Tests for what the file browser says about watching (#316, [[field-schema#watch-progress]]): the words a row ends
with, the videos that are gone, and the checkbox that sets *viewed* from a row.

The sums are core's (``test_watch_progress``); what is tested here is the mapping from them to a row.
"""

from pathlib import Path
from typing import Final

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QImage, QPainter, QPalette
from PySide6.QtWidgets import QStyle, QStyleOptionViewItem
from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.file_row import FileRow
from rehuco_agent.documents.files_progress import (
    MISSING_TOOLTIP,
    UNMEASURED_FILE_TOOLTIP,
    UNMEASURED_FOLDER_TOOLTIP,
    UNOPENED_TOOLTIP,
    FilesProgress,
    RowProgress,
    percent,
)
from rehuco_agent.documents.files_row_delegate import PERCENT_SHAPE, FilesRowDelegate
from rehuco_agent.documents.files_rows import KIND_COLUMN, NAME_COLUMN, FilesTableModel, missing_rows
from rehuco_core import FileKind, FileType, ProgressEntry, VideoFacts

ROOT: Final = Path.cwd() / "fake" / "library" / "lessons"
RECORD: Final = ROOT / "info.rehu"


def progress(
    entries: dict[str, ProgressEntry] | None = None,
    measured: dict[str, VideoFacts] | None = None,
    video_keys: tuple[str, ...] | None = ("a.mp4", "01 Basics/b.mp4", "01 Basics/c.mp4"),
) -> FilesProgress:
    """One user's progress over a resource of three videos, two of them in a folder.

    :param entries: the user's entries by key.
    :param measured: the measured lengths by key.
    :param video_keys: the videos on disk, or ``None`` when not known.
    :returns: the snapshot.
    """
    return FilesProgress(ROOT, entries or {}, measured or {}, video_keys)


# region the words


@mark.parametrize(
    ("done", "whole", "expected"),
    [(0, 100, "0%"), (50, 100, "50%"), (99.9, 100, "99%"), (100, 100, "100%"), (130, 100, "100%")],
)
def test_a_share_is_a_whole_percentage_that_is_never_100_before_it_is(done: float, whole: float, expected: str) -> None:
    """A video a moment short of its end reads 99%, and a position past the length reads 100%.

    **Test steps:**

    * format each share
    * verify the percentage
    """
    assert percent(done, whole) == expected


def test_a_video_never_opened_says_nothing() -> None:
    """Nothing is drawn after its name, and the tooltip says it was not opened.

    **Test steps:**

    * ask for a video with no entry
    * verify an empty text and the tooltip that says it was not opened
    """
    assert progress().for_video("a.mp4") == RowProgress(tooltip=UNOPENED_TOOLTIP)


def test_a_viewed_video_reads_100_whatever_its_position() -> None:
    """A rewatch moves the position and leaves the video viewed.

    **Test steps:**

    * ask for a viewed video whose position is 20% in
    * verify 100%
    """
    entries = {"a.mp4": ProgressEntry(20.0, 100.0, True)}

    assert progress(entries).for_video("a.mp4") == RowProgress("100%")


def test_a_partly_watched_video_reads_its_position_over_the_measured_length_first() -> None:
    """The record's measured length wins over the one the player saw.

    **Test steps:**

    * ask for a video at 25 s whose entry says 50 s long and whose measure says 100 s
    * verify 25%
    """
    entries = {"a.mp4": ProgressEntry(25.0, 50.0)}

    assert progress(entries, {"a.mp4": VideoFacts(100.0)}).for_video("a.mp4").text == "25%"


def test_a_video_with_a_position_and_no_length_says_why_it_has_no_percentage() -> None:
    """The share would be a guess, so none is drawn and the tooltip names the way out.

    **Test steps:**

    * ask for a video whose entry has no length and which was never measured
    * verify no text and the unmeasured tooltip
    """
    entries = {"a.mp4": ProgressEntry(25.0)}

    assert progress(entries).for_video("a.mp4") == RowProgress(tooltip=UNMEASURED_FILE_TOOLTIP)


def test_a_missing_video_says_its_file_is_gone() -> None:
    """The row of a deleted video explains itself on hover, and still counts what was watched.

    **Test steps:**

    * ask for a missing, half-watched video
    * verify its percentage and the missing tooltip
    """
    entries = {"gone.mp4": ProgressEntry(50.0, 100.0)}

    assert progress(entries).for_video("gone.mp4", missing=True) == RowProgress("50%", MISSING_TOOLTIP)


def test_a_folder_reads_the_duration_weighted_share_of_every_video_beneath_it() -> None:
    """Watching 90 of a folder's 100 minutes reads 90%, whatever the files' own shares.

    **Test steps:**

    * measure a folder's two videos at 60 and 40 minutes, view the first and leave the second at 30 minutes
    * verify the folder reads 90% -- 60 + 30 of 100
    """
    measured = {"01 Basics/b.mp4": VideoFacts(3600.0), "01 Basics/c.mp4": VideoFacts(2400.0), "a.mp4": VideoFacts(1.0)}
    entries = {"01 Basics/b.mp4": ProgressEntry(0.0, None, True), "01 Basics/c.mp4": ProgressEntry(1800.0)}

    assert progress(entries, measured).for_folder(ROOT / "01 Basics") == RowProgress("90%")


def test_a_folder_with_an_unmeasured_video_shows_no_percentage_and_says_so() -> None:
    """A share of a total that is not known would be a wrong number.

    **Test steps:**

    * measure only one of a folder's two videos
    * verify no text and the tooltip saying some lengths are unknown
    """
    measured = {"01 Basics/b.mp4": VideoFacts(60.0)}

    assert progress({}, measured).for_folder(ROOT / "01 Basics") == RowProgress(tooltip=UNMEASURED_FOLDER_TOOLTIP)


def test_a_folder_says_nothing_when_the_videos_on_disk_are_not_known_or_there_are_none() -> None:
    """A document that is not a tutorial, an unlistable folder and a folder with no video draw nothing.

    **Test steps:**

    * ask for a folder with the videos on disk unknown, and for one holding none, and for one outside the resource
    * verify nothing for each
    """
    assert progress(video_keys=None).for_folder(ROOT / "01 Basics") is None
    assert progress().for_folder(ROOT / "empty") is None
    assert progress().for_folder(ROOT.parent) is None


# endregion


# region the videos that are gone


def test_a_missing_video_is_a_row_in_the_folder_it_was_in() -> None:
    """Only the folder shown lists it, and a key that could not name a file inside the resource is not listed.

    **Test steps:**

    * keep entries for a video gone from the top, one gone from a folder, one still on disk and one with an escaping key
    * ask for the missing rows of each folder
    * verify each is listed in its own folder only, as a missing content video
    """
    entries = {
        "gone.mp4": ProgressEntry(1.0),
        "01 Basics/gone.mp4": ProgressEntry(2.0),
        "a.mp4": ProgressEntry(3.0),
        "../escape.mp4": ProgressEntry(4.0),
    }
    snapshot = progress(entries)

    top = missing_rows(RECORD, ROOT, snapshot)
    basics = missing_rows(RECORD, ROOT / "01 Basics", snapshot)

    assert [row.name for row in top] == ["gone.mp4"]
    assert [row.name for row in basics] == ["gone.mp4"]
    assert (top[0].key, top[0].missing, top[0].kind, top[0].file_type) == (
        "gone.mp4",
        True,
        FileKind.CONTENT,
        FileType.VIDEO,
    )
    assert basics[0].path == ROOT / "01 Basics" / "gone.mp4"


def test_no_video_is_missing_when_the_videos_on_disk_are_not_known() -> None:
    """Without the listing nothing can be called gone.

    **Test steps:**

    * ask with the videos on disk unknown
    * verify no rows
    """
    assert not missing_rows(RECORD, ROOT, progress({"gone.mp4": ProgressEntry(1.0)}, video_keys=None))


# endregion


# region the table


def row(name: str, key: str | None, *, missing: bool = False, directory: bool = False) -> FileRow:
    """One row of the table.

    :param name: its name.
    :param key: its content key, or ``None``.
    :param missing: whether it is a missing video.
    :param directory: whether it is a folder.
    :returns: the row.
    """
    return FileRow(
        name=name,
        path=ROOT / name,
        kind=FileKind.DIRECTORY if directory else FileKind.CONTENT,
        file_type=FileType.DIRECTORY if directory else FileType.VIDEO,
        key=key,
        missing=missing,
    )


@fixture(name="table")
def fixture_table(qtbot: QtBot) -> FilesTableModel:
    """A table of a video, a folder, a missing video and a file that is not a video, over a snapshot.

    :param qtbot: pytest-qt fixture.
    :returns: the table.
    """
    del qtbot
    model = FilesTableModel()
    model.set_rows(
        (
            row("a.mp4", "a.mp4"),
            row("01 Basics", None, directory=True),
            row("gone.mp4", "gone.mp4", missing=True),
            row("notes.txt", None),
        )
    )
    entries = {"a.mp4": ProgressEntry(25.0, 100.0), "gone.mp4": ProgressEntry(0.0, None, True)}
    model.set_progress(progress(entries, {"01 Basics/b.mp4": VideoFacts(10.0), "01 Basics/c.mp4": VideoFacts(10.0)}))
    return model


def test_the_progress_role_answers_each_kind_of_row(table: FilesTableModel) -> None:
    """A video and a missing video have a percentage and a box, a folder a share, and anything else nothing.

    **Test steps:**

    * read the progress role of each row
    * verify the video's 25%, the folder's unwatched 0%, the missing video's 100%, and nothing for the text file
    """
    role = FilesTableModel.PROGRESS_ROLE

    assert table.index(0, NAME_COLUMN).data(role).text == "25%"
    assert table.index(1, NAME_COLUMN).data(role) == RowProgress("0%")
    assert table.index(2, NAME_COLUMN).data(role).text == "100%"
    assert table.index(3, NAME_COLUMN).data(role) is None


def test_a_missing_video_reads_missing_in_the_kind_column_and_sorts_by_it(table: FilesTableModel) -> None:
    """Its kind says the file is gone, in the cell and in the key the column sorts on.

    **Test steps:**

    * read the Kind cell of a missing video and a present one, and their sort keys
    * verify the first says *missing* and the keys differ in the label
    """
    missing, present = table.index(2, KIND_COLUMN), table.index(0, KIND_COLUMN)

    assert missing.data() == "missing"
    assert present.data() == "content"
    assert missing.data(FilesTableModel.SORT_ROLE)[1] == "missing"


def test_the_name_tooltip_adds_what_watching_says_to_the_path(table: FilesTableModel) -> None:
    """The path stays on every tooltip, and a missing video says why it is there.

    **Test steps:**

    * read the Name tooltips of a missing video and a plain file
    * verify the first holds the path and the missing sentence, the second only the path
    """
    tooltip = Qt.ItemDataRole.ToolTipRole

    assert table.index(2, NAME_COLUMN).data(tooltip) == f"{ROOT / 'gone.mp4'}\n{MISSING_TOOLTIP}"
    assert table.index(3, NAME_COLUMN).data(tooltip) == str(ROOT / "notes.txt")


def test_a_change_of_progress_redraws_the_names_and_an_equal_one_does_not(qtbot: QtBot, table: FilesTableModel) -> None:
    """Percentages follow the snapshot, and the same snapshot twice is no change.

    **Test steps:**

    * set a different snapshot and verify the Name column is announced as changed
    * set an equal one and verify nothing is announced
    """
    snapshot = progress({"a.mp4": ProgressEntry(50.0, 100.0)})
    with qtbot.waitSignal(table.dataChanged):
        table.set_progress(snapshot)

    with qtbot.assertNotEmitted(table.dataChanged):
        table.set_progress(progress({"a.mp4": ProgressEntry(50.0, 100.0)}))


# endregion


# region the delegate


CELL_WIDTH: Final = 300
CELL_HEIGHT: Final = 24


@fixture(name="delegate")
def fixture_delegate(qapp: object) -> FilesRowDelegate:
    """A delegate; takes ``qapp`` because recolouring an SVG needs a `QGuiApplication`.

    :param qapp: the Qt application fixture.
    :returns: the delegate.
    """
    del qapp
    return FilesRowDelegate()


def option() -> QStyleOptionViewItem:
    """A style option over one cell.

    :returns: the option.
    """
    result = QStyleOptionViewItem()
    result.rect.setRect(0, 0, CELL_WIDTH, CELL_HEIGHT)
    result.palette = QPalette()
    return result


def test_the_percentage_is_drawn_right_aligned_at_the_end_and_the_name_is_elided_short_of_it(
    delegate: FilesRowDelegate, table: FilesTableModel, mocker: MockerFixture
) -> None:
    """The row ends with its percentage, in room reserved for the widest one, and the name never runs under it.

    **Test steps:**

    * paint a video row with a percentage, capturing the text drawn
    * verify the percentage was drawn right-aligned at the end of the cell, and the name's rect stops before it
    """
    image = QImage(CELL_WIDTH, CELL_HEIGHT, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    calls: list[tuple[QRect, Qt.AlignmentFlag, str]] = []
    mocker.patch.object(QPainter, "drawText", side_effect=lambda rect, flags, text: calls.append((rect, flags, text)))
    cell = option()
    cell.state |= QStyle.StateFlag.State_Enabled
    try:
        delegate.paint(painter, cell, table.index(0, NAME_COLUMN))
    finally:
        painter.end()

    by_text = {text: (rect, flags) for rect, flags, text in calls}
    percent_rect, percent_flags = by_text["25%"]
    name_rect, _ = by_text["a.mp4"]
    assert percent_flags & Qt.AlignmentFlag.AlignRight
    assert percent_rect.right() < CELL_WIDTH
    assert name_rect.right() < percent_rect.left()
    assert PERCENT_SHAPE == "100%"


# endregion
