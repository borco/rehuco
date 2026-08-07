"""Tests for the checksum table's rows, its sorting and its summary (#244).

The read under test is the real one over a real record and a real enumeration: what this module is
about is that the rows come from **both** sources and that a file the record does not cover is
distinguishable from one it covers with nothing recorded, which cannot be asserted against a mocked
reader.
"""

import json
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from threading import Event
from types import SimpleNamespace
from typing import Any, Final

import shiboken6
from PySide6.QtCore import QModelIndex, QObject, Qt
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.checksum_rows import (
    DATE_COLUMN,
    PATH_COLUMN,
    STATUS_COLUMN,
    ChecksumRow,
    ChecksumRows,
    ChecksumRowsLoader,
    ChecksumSortProxy,
    ChecksumTableModel,
    read_checksum_rows,
    tally_rows,
    tally_text,
)


# the listing fakes below are `test_excluded_files_settings`' and the core walks' near-verbatim --
# kept as a separate copy rather than shared, this codebase's fake-filesystem convention
# pylint: disable=duplicate-code
class FakeDirEntry:
    """A stand-in for :class:`os.DirEntry`, which cannot be constructed outside a real directory read."""

    def __init__(self, name: str, *, directory: bool = False) -> None:
        self.name: Final = name
        self.__directory: Final = directory

    def is_dir(self, *, follow_symlinks: bool = True) -> bool:
        """Whether the test declared this entry a directory."""
        del follow_symlinks
        return self.__directory

    def is_file(self, *, follow_symlinks: bool = True) -> bool:
        """Whether the test declared this entry a regular file."""
        del follow_symlinks
        return not self.__directory


class FakeScandir:
    """What :func:`os.scandir` returns: an iterator that is also a context manager."""

    def __init__(self, entries: list[FakeDirEntry]) -> None:
        self.__entries: Final = entries

    def __enter__(self) -> Any:
        return iter(self.__entries)

    def __exit__(self, *_exception: object) -> None:
        return None


# pylint: enable=duplicate-code

DIRECTORY: Final = Path("/fake/library/sculpting")
INFO_PATH: Final = DIRECTORY / "info.rehu"
RECORD_PATH: Final = DIRECTORY / "info.checksum"

VIDEO: Final = "lesson1.mp4"
ARCHIVE: Final = "extras/pack.zip"

PATTERNS: Final = ("Thumbs.db",)

SETTLE: Final = 5.0
"""How long a test waits for the loader's pool thread to reach a state, in seconds.

Far above anything the read needs and far below a suite that looks hung, so a wait that runs out is a
genuine failure rather than a slow runner -- the same meaning `tests/concurrency.py` gives it core-side."""

STAMP: Final = "2026-08-05T12:00:00Z"


# pylint: disable=duplicate-code
class FakeDisk:
    """The four filesystem faces a row read touches, from one dictionary.

    :param files: the resource's files, keyed by name relative to the ``.rehu``, POSIX-separated.
    """

    def __init__(self, files: dict[str, bytes]) -> None:
        self.files: Final[dict[Path, bytes]] = {
            DIRECTORY / PurePosixPath(name): payload for name, payload in files.items()
        }
        self.offline: Final[set[Path]] = set()
        """Directories whose listing refuses -- an away mount."""

    def scandir(self, directory: Path | str) -> FakeScandir:
        """List one directory, derived from the current file set.

        :param directory: the directory to read.
        :returns: its entries.
        :raises PermissionError: the directory is offline.
        :raises FileNotFoundError: nothing lives at or under ``directory``.
        """
        directory = Path(directory)
        if directory in self.offline:
            raise PermissionError(str(directory))
        entries: list[FakeDirEntry] = []
        subdirectories: set[str] = set()
        for path in self.files:
            if path.parent == directory:
                entries.append(FakeDirEntry(path.name))
            elif directory in path.parents:
                subdirectories.add(path.relative_to(directory).parts[0])
        if not entries and not subdirectories and directory != DIRECTORY:
            raise FileNotFoundError(str(directory))
        entries.extend(FakeDirEntry(name, directory=True) for name in sorted(subdirectories))
        return FakeScandir(entries)

    def read_text(self, path: Path) -> str:
        """Read a file as UTF-8 text -- how the record is loaded.

        :param path: the file to read.
        :returns: its decoded contents.
        :raises FileNotFoundError: nothing lives at ``path``.
        """
        payload = self.files.get(Path(path))
        if payload is None:
            raise FileNotFoundError(str(path))
        return payload.decode("utf-8")

    def stat(self, path: Path) -> SimpleNamespace:
        """Answer a file's size.

        :param path: the file to measure.
        :returns: an object carrying ``st_size``.
        """
        return SimpleNamespace(st_size=len(self.files.get(Path(path), b"")))

    def put(self, path: Path, payload: bytes) -> None:
        """Add or replace one file.

        :param path: the file.
        :param payload: its bytes.
        """
        self.files.update({path: payload})

    def put_record(self, entries: list[dict[str, Any]]) -> None:
        """Put a record on the disk.

        :param entries: the raw entries to write.
        """
        self.put(RECORD_PATH, (json.dumps({"version": 1, "files": entries}) + "\n").encode("utf-8"))


# pylint: enable=duplicate-code


@fixture(name="disk")
def fixture_disk(mocker: MockerFixture) -> FakeDisk:
    """A resource holding a video, an archive in a subfolder, and its own bookkeeping.

    :param mocker: pytest-mock fixture.
    :returns: the disk under the code's feet.
    """
    disk = FakeDisk(
        {
            "info.rehu": b'{"format_version": 2}',
            "info00.jpg": b"a screenshot",
            "Thumbs.db": b"junk",
            VIDEO: b"video",
            ARCHIVE: b"archive",
        }
    )
    mocker.patch("rehuco_core.rehu_content_files.os.scandir", side_effect=disk.scandir)
    mocker.patch.object(Path, "read_text", autospec=True, side_effect=lambda self, **_kwargs: disk.read_text(self))
    mocker.patch.object(Path, "stat", autospec=True, side_effect=lambda self, **_kwargs: disk.stat(self))
    return disk


def entry(name: str, **extra: Any) -> dict[str, Any]:
    """One record entry.

    :param name: the file's record-relative name.
    :param extra: the rest of the entry.
    :returns: the raw entry.
    """
    return {"name": name, "crc32": "deadbeef", **extra}


# region Where the rows come from


def test_a_covered_file_and_an_uncovered_one_both_appear(disk: FakeDisk) -> None:
    """The record and the enumeration are both sources, and the second is distinguishable (#244).

    **Test steps:**

    * put a record covering only the video
    * read the rows
    * check the archive is there with an empty status and an empty date
    """
    disk.put_record([entry(VIDEO, verified=STAMP, status="matched")])

    rows = read_checksum_rows(INFO_PATH, PATTERNS)

    by_name = {row.name: row for row in rows.rows}
    assert set(by_name) == {VIDEO, ARCHIVE}
    assert by_name[VIDEO].status == "matched"
    assert by_name[ARCHIVE].status == ""
    assert by_name[ARCHIVE].verified is None


def test_a_resource_with_no_record_shows_every_content_file(disk: FakeDisk) -> None:
    """The dock is worth opening before anything has ever run (#244).

    **Test steps:**

    * read the rows of a resource that has never been checksummed
    * check both content files are listed, unchecked, and nothing is wrong
    """
    del disk
    rows = read_checksum_rows(INFO_PATH, PATTERNS)

    assert {row.name for row in rows.rows} == {VIDEO, ARCHIVE}
    assert all(row.status == "" for row in rows.rows)
    assert rows.reachable
    assert not rows.error


def test_the_bookkeeping_is_never_a_row(disk: FakeDisk) -> None:
    """The rows are #226's shared answer, so a screenshot and a ``Thumbs.db`` are not files (#244).

    **Test steps:**

    * read the rows
    * check no bookkeeping name is among them
    """
    del disk
    rows = read_checksum_rows(INFO_PATH, PATTERNS)

    assert {"info.rehu", "info00.jpg", "info.checksum", "Thumbs.db"}.isdisjoint({row.name for row in rows.rows})


def test_a_recorded_entry_outside_the_content_still_shows(disk: FakeDisk) -> None:
    """A verify checks what the record lists whatever the exclusion set says, so the table shows it too.

    **Test steps:**

    * put a record naming a file the enumeration excludes
    * read the rows
    * check the entry is listed with its recorded status
    """
    disk.put_record([entry("Thumbs.db", verified=STAMP, status="mismatched")])

    rows = read_checksum_rows(INFO_PATH, PATTERNS)

    assert {row.name: row.status for row in rows.rows}["Thumbs.db"] == "mismatched"


def test_an_unreachable_resource_is_not_an_empty_one(disk: FakeDisk) -> None:
    """An away mount answers *unreachable*, never an empty table (#245, #244).

    **Test steps:**

    * take the resource's own directory offline and read the rows
    * check nothing is listed and the read says why
    """
    disk.offline.add(DIRECTORY)

    rows = read_checksum_rows(INFO_PATH, PATTERNS)

    assert not rows.reachable
    assert not rows.rows


def test_a_record_this_build_cannot_read_still_lists_the_files(disk: FakeDisk) -> None:
    """The content was enumerated, and what could be read is worth showing (#244).

    **Test steps:**

    * put a record that is not JSON at all
    * read the rows
    * check the content files are listed unchecked and the failure is reported
    """
    disk.put(RECORD_PATH, b"not json")

    rows = read_checksum_rows(INFO_PATH, PATTERNS)

    assert {row.name for row in rows.rows} == {VIDEO, ARCHIVE}
    assert all(row.status == "" for row in rows.rows)
    assert rows.error


def test_an_entry_this_build_cannot_name_is_not_a_row(disk: FakeDisk) -> None:
    """A row that cannot say which file it is about is not one a reader can act on (#244).

    **Test steps:**

    * put a record holding an unnamed entry
    * read the rows
    * check only the content files are listed
    """
    disk.put_record([{"crc32": "deadbeef"}, entry(VIDEO, verified=STAMP, status="matched")])

    rows = read_checksum_rows(INFO_PATH, PATTERNS)

    assert {row.name for row in rows.rows} == {VIDEO, ARCHIVE}


# endregion


# region The table


def test_the_table_draws_the_path_the_status_and_a_local_date() -> None:
    """The record stores UTC; the table shows local time (#244).

    **Test steps:**

    * put one recorded row in the model
    * check each column's text, the date rendered in local time
    """
    stamp = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
    model = ChecksumTableModel()
    model.set_rows((ChecksumRow(VIDEO, "matched", stamp),))

    assert model.index(0, PATH_COLUMN).data() == VIDEO
    assert model.index(0, STATUS_COLUMN).data() == "matched"
    assert model.index(0, DATE_COLUMN).data() == stamp.astimezone().strftime("%Y-%m-%d %H:%M")


def test_an_unchecked_row_draws_two_empty_cells() -> None:
    """*Not checked yet* is two empty cells, which is the only honest thing to draw (#244).

    **Test steps:**

    * put one uncovered row in the model
    * check its status and date are empty and its path is not
    """
    model = ChecksumTableModel()
    model.set_rows((ChecksumRow(ARCHIVE),))

    assert model.index(0, PATH_COLUMN).data() == ARCHIVE
    assert model.index(0, STATUS_COLUMN).data() == ""
    assert model.index(0, DATE_COLUMN).data() == ""


def test_sorting_renumbers_the_rows_rather_than_carrying_them() -> None:
    """The row number is the vertical header, so it always numbers what is on screen (#244).

    **Test steps:**

    * sort three rows by status, descending then ascending
    * check the drawn order changes and the numbering stays 1..N either way
    """
    model = ChecksumTableModel()
    model.set_rows(
        (
            ChecksumRow("a.mp4", "matched"),
            ChecksumRow("b.mp4", "mismatched"),
            ChecksumRow("c.mp4", "missing"),
        )
    )
    proxy = ChecksumSortProxy()
    proxy.setSourceModel(model)

    proxy.sort(STATUS_COLUMN, Qt.SortOrder.DescendingOrder)
    descending = [proxy.index(row, PATH_COLUMN).data() for row in range(proxy.rowCount())]
    numbers = [proxy.headerData(row, Qt.Orientation.Vertical) for row in range(proxy.rowCount())]

    assert descending == ["c.mp4", "b.mp4", "a.mp4"]
    assert numbers == [1, 2, 3]

    proxy.sort(STATUS_COLUMN, Qt.SortOrder.AscendingOrder)

    assert [proxy.index(row, PATH_COLUMN).data() for row in range(proxy.rowCount())] == ["a.mp4", "b.mp4", "c.mp4"]
    assert [proxy.headerData(row, Qt.Orientation.Vertical) for row in range(proxy.rowCount())] == [1, 2, 3]


def test_dates_sort_chronologically_rather_than_lexically() -> None:
    """The proxy sorts on the value, not on the drawn text (#244).

    **Test steps:**

    * sort two rows whose local rendering would sort the other way round
    * check the older one comes first
    """
    model = ChecksumTableModel()
    model.set_rows(
        (
            ChecksumRow("late.mp4", "matched", datetime(2026, 12, 1, 9, 0, tzinfo=UTC)),
            ChecksumRow("early.mp4", "matched", datetime(2026, 2, 3, 9, 0, tzinfo=UTC)),
            ChecksumRow("never.mp4"),
        )
    )
    proxy = ChecksumSortProxy()
    proxy.setSourceModel(model)

    proxy.sort(DATE_COLUMN, Qt.SortOrder.AscendingOrder)

    assert [proxy.index(row, PATH_COLUMN).data() for row in range(proxy.rowCount())] == [
        "never.mp4",
        "early.mp4",
        "late.mp4",
    ]


# endregion


# region The summary


def test_the_summary_counts_how_many_of_what() -> None:
    """The row numbers answer *how many*; this answers *how many of what* (#244).

    **Test steps:**

    * tally a mixed set of rows
    * check the line names each count once, and the uncovered files as *not recorded*
    """
    rows = (
        ChecksumRow("a", "matched"),
        ChecksumRow("b", "matched"),
        ChecksumRow("c", "mismatched"),
        ChecksumRow("d"),
    )

    assert tally_text(tally_rows(rows)) == "4 files · 2 matched · 1 mismatched · 1 not recorded"


def test_the_summary_leaves_out_what_it_did_not_find() -> None:
    """A summary naming everything it did not find would bury the number that moved (#244).

    **Test steps:**

    * tally a clean single-file resource
    * check the line names only what is there
    """
    assert tally_text(tally_rows((ChecksumRow("a", "matched"),))) == "1 file · 1 matched"


def test_an_empty_resource_still_says_so() -> None:
    """Zero files is a real answer and a drawable one.

    **Test steps:**

    * tally nothing
    * check the line says zero
    """
    assert tally_text(tally_rows(())) == "0 files"


def test_rows_default_to_reachable_and_clean() -> None:
    """A read that says nothing is a reachable, error-free read -- what every caller assumes.

    **Test steps:**

    * build an empty result
    * check its defaults
    """
    rows = ChecksumRows()

    assert rows.reachable
    assert not rows.error
    assert not rows.rows


# endregion


# region The loader


def test_a_read_that_raises_reports_rather_than_leaving_the_dock_waiting(qtbot: QtBot, mocker: MockerFixture) -> None:
    """A ``loaded`` that never arrived would leave a busy state for the document's life (#244).

    **Test steps:**

    * make the read raise and start one
    * check the answer still came back, carrying the failure
    """
    mocker.patch(
        "rehuco_agent.documents.checksum_rows.read_checksum_rows", side_effect=RuntimeError("the walk fell over")
    )
    loader = ChecksumRowsLoader()
    delivered: list[ChecksumRows] = []
    loader.loaded.connect(delivered.append)

    loader.start(INFO_PATH, PATTERNS)

    qtbot.waitUntil(lambda: bool(delivered), timeout=5000)
    assert delivered[0].error == "the walk fell over"


def test_a_superseded_read_is_dropped_rather_than_drawn(qtbot: QtBot, mocker: MockerFixture) -> None:
    """A rename can ask for a re-read while the first walk is still out (#244).

    **Test steps:**

    * start a read, hold it inside the walk, and start a second one over it
    * check only the second one's answer is ever delivered
    """
    first = ChecksumRows(rows=(ChecksumRow("first.mp4"),))
    second = ChecksumRows(rows=(ChecksumRow("second.mp4"),))
    answers = iter((first, second))
    reached = Event()
    release = Event()

    def read(*_args: Any) -> ChecksumRows:
        """Park the first walk until the test has superseded it; answer the second at once."""
        answer = next(answers)
        if answer is first:
            reached.set()
            assert release.wait(SETTLE)
        return answer

    mocker.patch("rehuco_agent.documents.checksum_rows.read_checksum_rows", side_effect=read)
    loader = ChecksumRowsLoader()
    delivered: list[ChecksumRows] = []
    loader.loaded.connect(delivered.append)

    # the first read has to still be *out* when the second start supersedes it: two starts back to
    # back leave a window in which the pool thread finishes the first and delivers it before the
    # second start ever runs, which is a legitimate delivery and asserts nothing about generations
    loader.start(INFO_PATH, PATTERNS)
    assert reached.wait(SETTLE)
    loader.start(INFO_PATH, PATTERNS)
    release.set()

    qtbot.waitUntil(lambda: bool(delivered), timeout=5000)
    qtbot.wait(50)
    assert [row.name for answer in delivered for row in answer.rows] == ["second.mp4"]


def test_a_cell_names_its_file_on_hover() -> None:
    """A path column narrower than its longest path is the normal case, so the row says which file.

    **Test steps:**

    * ask a cell for its tooltip, and for a role this model has no answer to
    * check the first is the file's name whichever column was asked, and the second is nothing
    """
    model = ChecksumTableModel()
    model.set_rows((ChecksumRow(ARCHIVE, "matched"),))

    assert model.index(0, STATUS_COLUMN).data(Qt.ItemDataRole.ToolTipRole) == ARCHIVE
    assert model.index(0, STATUS_COLUMN).data(Qt.ItemDataRole.DecorationRole) is None


def test_an_invalid_index_answers_nothing() -> None:
    """Qt asks about the root index, which is not a cell.

    **Test steps:**

    * ask the model about an invalid index
    * check it answers nothing
    """
    assert ChecksumTableModel().data(QModelIndex()) is None


def test_the_headers_name_the_columns_and_nothing_else() -> None:
    """The source model titles the columns; the row numbers are the proxy's (#244).

    **Test steps:**

    * ask for each header
    * check the titles come back and the vertical header does not
    """
    model = ChecksumTableModel()

    assert model.headerData(PATH_COLUMN, Qt.Orientation.Horizontal) == "File"
    assert model.headerData(0, Qt.Orientation.Vertical) is None
    assert model.headerData(99, Qt.Orientation.Horizontal) is None


def test_a_flat_table_has_nothing_under_a_cell() -> None:
    """Rows and columns live at the root only.

    **Test steps:**

    * ask for the counts under a cell
    * check both are zero
    """
    model = ChecksumTableModel()
    model.set_rows((ChecksumRow(VIDEO),))
    under = model.index(0, PATH_COLUMN)

    assert model.rowCount(under) == 0
    assert model.columnCount(under) == 0


# endregion


def test_a_walk_that_answers_after_its_dock_is_gone_reports_into_nothing(mocker: MockerFixture) -> None:
    """A document closed mid-walk must not raise on the pool thread (#244).

    The loader is parented to the dock, so closing the document takes its C++ half while the walk is
    still out on a mount -- and an exception on a pool thread is printed and swallowed, which is the
    kind of failure nobody ever sees reported.

    **Test steps:**

    * destroy the loader's C++ object the way closing a document does, then let a read answer
    * check the run returned quietly rather than raising into the pool
    """
    mocker.patch("rehuco_agent.documents.checksum_rows.read_checksum_rows", return_value=ChecksumRows())
    dock = QObject()
    loader = ChecksumRowsLoader(dock)
    delivered: list[ChecksumRows] = []
    # connected, because an emit with nobody listening never reaches the deleted C++ half at all --
    # which is exactly the case this guard is *not* about
    loader.loaded.connect(delivered.append)
    run = loader._ChecksumRowsLoader__run  # type: ignore[attr-defined]  # pylint: disable=protected-access
    shiboken6.delete(dock)
    assert not shiboken6.isValid(loader)

    # generation 0 is the one a loader that has never been started is on, so this read is
    # current rather than superseded -- otherwise it returns before it ever tries to report
    run(INFO_PATH, PATTERNS, 0)

    assert not delivered
