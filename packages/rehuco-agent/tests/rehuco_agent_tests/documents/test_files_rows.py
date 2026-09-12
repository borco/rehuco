"""Tests for the file browser's rows: the read, the checksum states and the table over them (#266).

What each file *is* is `test_rehu_file_kinds`' subject, core-side; what this module is about is the row
built from it -- which of them a reader may act on, what the checksum column says, and the order the
table draws them in.

The classification is mocked at :class:`~rehuco_core.DirectoryClassifier` and the record at the loader
this module calls, so a test declares a classified folder rather than arranging for one to exist -- and
the kinds arrive from the test rather than from the rules, which is the point: what is tested here is the
*mapping* from a kind to a row, where whether a given file has that kind is core's own subject.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from typing import Any, Final

import shiboken6
from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, Qt
from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.files_rows import (
    CHECKSUM_COLUMN,
    KIND_COLUMN,
    MODIFIED_COLUMN,
    NAME_COLUMN,
    PARENT_ROW_NAME,
    SIZE_COLUMN,
    FileChecksumState,
    FileRow,
    FilesRows,
    FilesRowsLoader,
    FilesRowsReader,
    FilesSortProxy,
    FilesTableModel,
    ModelIndex,
)
from rehuco_core import ChecksumRecordError, DirectoryClassifier, DirectoryEntry, DirectoryListing, FileKind, FileType

DIRECTORY: Final = Path("/fake/library/sculpting")
INFO_PATH: Final = DIRECTORY / "info.rehu"

NOW: Final = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
WEEK: Final = timedelta(days=7)
FRESH: Final = "2026-09-11T12:00:00Z"
OLD: Final = "2026-06-11T12:00:00Z"

MTIME: Final = 1_700_000_000.0

FOLDER: Final = (
    DirectoryEntry("info.rehu", FileKind.OWN_RECORD, FileType.RECORD, 10, MTIME),
    DirectoryEntry("info.checksum", FileKind.OWN_MANIFEST, FileType.MANIFEST, 10, MTIME),
    DirectoryEntry("info00.jpg", FileKind.OWN_SCREENSHOT, FileType.IMAGE, 10, MTIME),
    DirectoryEntry("info.tc.orig", FileKind.CONVERSION_BACKUP, FileType.BACKUP, 10, MTIME),
    DirectoryEntry("lesson01.mp4", FileKind.CONTENT, FileType.VIDEO, 10, MTIME),
    DirectoryEntry("notes.pdf", FileKind.CONTENT, FileType.GENERIC, 9, MTIME),
    DirectoryEntry("song.mp3", FileKind.CONTENT, FileType.AUDIO, 10, MTIME),
    DirectoryEntry("extra.mp4", FileKind.CONTENT, FileType.VIDEO, 10, MTIME),
    DirectoryEntry("Thumbs.db", FileKind.EXCLUDED, FileType.GENERIC, 10, MTIME),
    DirectoryEntry("other.rehu", FileKind.FOREIGN_RECORD, FileType.RECORD, 10, MTIME),
    DirectoryEntry("other00.jpg", FileKind.FOREIGN_SIDECAR, FileType.IMAGE, 10, MTIME),
    DirectoryEntry("other.zip", FileKind.FOREIGN_CONTENT, FileType.ARCHIVE, 10, MTIME),
    DirectoryEntry("sub", FileKind.DIRECTORY, FileType.DIRECTORY),
)
"""One resource's folder as core would classify it: its own record and sidecars, a retained backup,
content of four types -- one of which no record entry covers -- a junk name, a neighbour with its own
sidecar and content, and a subfolder."""


def mock_listing(
    mocker: MockerFixture,
    entries: tuple[DirectoryEntry, ...] = FOLDER,
    *,
    unreachable: bool = False,
    foreign_directory_record: str | None = None,
) -> None:
    """Mock what the classifier answers for whichever directory is asked about.

    :param mocker: pytest-mock fixture.
    :param entries: the classified entries it holds.
    :param unreachable: answer *away* instead -- an offline mount.
    :param foreign_directory_record: the foreign ``info.rehu`` covering this directory, if any, which is
        what decides whether the folders here may be entered.
    """
    mocker.patch.object(
        DirectoryClassifier,
        "classify",
        autospec=True,
        side_effect=lambda _self, directory: DirectoryListing(
            directory,
            entries=() if unreachable else entries,
            reachable=not unreachable,
            foreign_directory_record=foreign_directory_record,
        ),
    )


def mock_record(mocker: MockerFixture, entries: list[dict[str, Any]] | None, error: Exception | None = None) -> None:
    """Mock the ``.checksum`` this resource's rows are judged against.

    :param mocker: pytest-mock fixture.
    :param entries: the record's entries, or ``None`` for a resource that has never been checksummed.
    :param error: raise this instead -- a record this build cannot read.
    """
    target = "rehuco_agent.documents.files_rows.load_checksum_record"
    if error is not None:
        mocker.patch(target, side_effect=error)
    elif entries is None:
        mocker.patch(target, side_effect=FileNotFoundError)
    else:
        mocker.patch(target, return_value={"version": 1, "files": entries})


def entry(name: str, verified: str = FRESH, status: str = "matched") -> dict[str, Any]:
    """One recorded entry.

    :param name: the file's record-relative name.
    :param verified: when it was last checked.
    :param status: what that check answered.
    :returns: the raw entry.
    """
    return {"name": name, "xxh3": "0" * 16, "verified": verified, "status": status}


def read(mocker: MockerFixture, directory: Path = DIRECTORY, record: Path = INFO_PATH) -> dict[str, FileRow]:
    """Read one directory into rows, keyed by name.

    :param mocker: pytest-mock fixture, only to satisfy the mocks already installed.
    :param directory: the directory to read.
    :param record: the asking resource's record.
    :returns: the rows by name.
    """
    del mocker
    rows = FilesRowsReader(record, ("Thumbs.db",), (), WEEK).read(directory, NOW)
    return {row.name: row for row in rows.rows}


KEYLESS_NAMES: Final = ("zebra", "apple", "mango")


# region Sample classes


class KeylessModel(QAbstractTableModel):
    """A model that answers the sort role with a plain string rather than this table's key tuple.

    What :class:`~rehuco_agent.documents.files_rows.FilesSortProxy` defers to the base comparison for --
    a foreign model being the only way to ask for that deference, since this package's own model always
    answers a tuple.
    """

    def rowCount(self, parent: ModelIndex = QModelIndex()) -> int:  # noqa: N802  (Qt API name)
        """How many sample rows there are, or none under a row.

        :param parent: the parent index, valid only for a child of a row this model has none of.
        :returns: the row count.
        """
        return 0 if parent.isValid() else len(KEYLESS_NAMES)

    def columnCount(self, parent: ModelIndex = QModelIndex()) -> int:  # noqa: N802  (Qt API name)
        """One column, the name.

        :param parent: the parent index, valid only for a child of a row this model has none of.
        :returns: the column count.
        """
        return 0 if parent.isValid() else 1

    def data(self, index: ModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        """The row's name, for the display role and for the sort role alike.

        :param index: the cell.
        :param role: which role is being asked.
        :returns: the name as a plain string, which is the point -- never a key tuple.
        """
        if role in (Qt.ItemDataRole.DisplayRole, FilesTableModel.SORT_ROLE):
            return KEYLESS_NAMES[index.row()]
        return None


# endregion


# region Which rows a reader may act on


@fixture
def rows(mocker: MockerFixture) -> dict[str, FileRow]:
    """The resource's own folder, read with no checksum record at all."""
    mock_listing(mocker)
    mock_record(mocker, None)
    return read(mocker)


@mark.parametrize(
    ("name", "enabled"),
    [
        ("info.rehu", False),
        ("other00.jpg", False),
        ("other.zip", False),
        ("info.checksum", True),
        ("info00.jpg", True),
        ("info.tc.orig", True),
        ("lesson01.mp4", True),
        ("Thumbs.db", True),
        ("other.rehu", True),
        ("sub", True),
    ],
)
def test_a_row_is_actionable_only_where_this_resource_can_speak_for_it(
    rows: dict[str, FileRow], name: str, enabled: bool
) -> None:
    """Three refusals, each deliberate (#266): the document already on screen, and the two kinds that
    belong to a resource this document cannot speak for.

    **Test steps:**

    * read the resource's own folder
    * verify each row's enabled state
    """
    assert rows[name].enabled is enabled


def test_a_disabled_row_cannot_be_selected_or_activated(rows: dict[str, FileRow]) -> None:
    """The refusal lives in ``flags`` rather than as a check in every activation path, which is what
    makes a double-click on another resource's screenshot impossible rather than merely ignored.

    **Test steps:**

    * put the rows in a model
    * verify the disabled row answers no flags at all and an ordinary one is enabled and selectable
    """
    model = FilesTableModel()
    model.set_rows(tuple(rows.values()))
    order = list(rows)

    disabled = model.index(order.index("info.rehu"), NAME_COLUMN)
    enabled = model.index(order.index("lesson01.mp4"), NAME_COLUMN)

    assert model.flags(disabled) == Qt.ItemFlag.NoItemFlags
    assert model.flags(enabled) & Qt.ItemFlag.ItemIsEnabled
    assert model.flags(enabled) & Qt.ItemFlag.ItemIsSelectable


def test_the_folders_of_another_resources_directory_are_refused(mocker: MockerFixture) -> None:
    """A directory holding a foreign ``info.rehu`` is that resource's wholesale (#254), so the folders
    beside it are not this browser's to walk into -- its record is the way in.

    **Test steps:**

    * read a folder holding a file-scoped record beside an ``info.rehu`` it does not own
    * verify the subfolder is refused while the foreign record stays openable
    """
    mock_listing(
        mocker,
        (
            DirectoryEntry("foo.rehu", FileKind.OWN_RECORD, FileType.RECORD),
            DirectoryEntry("info.rehu", FileKind.FOREIGN_RECORD, FileType.RECORD),
            DirectoryEntry("sub", FileKind.DIRECTORY, FileType.DIRECTORY),
        ),
        foreign_directory_record="info.rehu",
    )
    mock_record(mocker, None)
    found = read(mocker, DIRECTORY, DIRECTORY / "foo.rehu")

    assert not found["sub"].enabled
    assert found["info.rehu"].enabled


def test_file_scoped_neighbours_alone_do_not_refuse_the_folders(mocker: MockerFixture) -> None:
    """Only a directory-scoped record covers the ground a folder sits on: a listing full of
    ``foo.rehu``/``bar.rehu`` and no ``info.rehu`` reports nothing foreign, so the subfolder rows stay
    interactive (#254).

    **Test steps:**

    * read a listing of several file-scoped records and a subfolder, with nothing covering the directory
    * verify the subfolder is enabled and each record is openable
    """
    mock_listing(
        mocker,
        (
            DirectoryEntry("foo.rehu", FileKind.OWN_RECORD, FileType.RECORD),
            DirectoryEntry("bar.rehu", FileKind.FOREIGN_RECORD, FileType.RECORD),
            DirectoryEntry("baz.rehu", FileKind.FOREIGN_RECORD, FileType.RECORD),
            DirectoryEntry("sub", FileKind.DIRECTORY, FileType.DIRECTORY),
        ),
    )
    mock_record(mocker, None)
    found = read(mocker, DIRECTORY, DIRECTORY / "foo.rehu")

    assert found["sub"].enabled
    assert found["bar.rehu"].enabled
    assert found["baz.rehu"].enabled


def test_the_parent_row_appears_only_below_the_root_and_is_always_enabled(mocker: MockerFixture) -> None:
    """The browser is confined to the resource's own folder, so there is nothing above the root to
    offer -- and walking back out is never the thing another resource owns.

    **Test steps:**

    * read the root, and read a subfolder
    * verify the parent row is absent at the root and present, enabled, below it
    """
    mock_listing(mocker, ())
    mock_record(mocker, None)

    assert PARENT_ROW_NAME not in read(mocker, DIRECTORY)
    below = read(mocker, DIRECTORY / "sub")
    assert below[PARENT_ROW_NAME].enabled
    assert below[PARENT_ROW_NAME].path == DIRECTORY


# endregion


# region What the checksum column says


@mark.parametrize(
    ("name", "state"),
    [
        ("lesson01.mp4", FileChecksumState.OK),
        ("notes.pdf", FileChecksumState.BAD),
        ("song.mp3", FileChecksumState.OLD_OK),
        ("extra.mp4", FileChecksumState.MISSING),
        ("Thumbs.db", FileChecksumState.NONE),
        ("info.rehu", FileChecksumState.NONE),
        ("info00.jpg", FileChecksumState.NONE),
        ("info.checksum", FileChecksumState.NONE),
        ("info.tc.orig", FileChecksumState.NONE),
        ("other.zip", FileChecksumState.NONE),
        ("other00.jpg", FileChecksumState.NONE),
        ("sub", FileChecksumState.NONE),
    ],
)
def test_each_row_carries_what_this_record_claims_about_it(
    mocker: MockerFixture, name: str, state: FileChecksumState
) -> None:
    """Five verdicts and an empty cell, and the empty one is the point: this record makes no claim about
        a sidecar, a folder or another resource's content, which is different from claiming ignorance.

    An **ignored** file gets an empty cell rather than the missing glyph: a junk name is not this
        resource's content and never will be, so the record is not skipping it -- there is nothing to
        record. The missing glyph is for content the record has no hash for, which is a gap.

        **Test steps:**

        * read the folder against a record covering three of its files with three different verdicts
        * verify each row's state
    """
    mock_listing(mocker)
    mock_record(
        mocker,
        [entry("lesson01.mp4"), entry("notes.pdf", status="mismatched"), entry("song.mp3", verified=OLD)],
    )

    assert read(mocker)[name].checksum_state is state


def test_a_stale_mismatch_is_its_own_state(mocker: MockerFixture) -> None:
    """The pair with the stale match is what makes the column say *a fresh check would tell you
    something* rather than conflating never-checked with checked-long-ago.

    **Test steps:**

    * record a mismatch checked months ago
    * verify it reads as the stale-bad state
    """
    mock_listing(mocker)
    mock_record(mocker, [entry("notes.pdf", verified=OLD, status="mismatched")])

    assert read(mocker)["notes.pdf"].checksum_state is FileChecksumState.OLD_BAD


def test_a_dateless_entry_is_never_current(mocker: MockerFixture) -> None:
    """A claim seeded from a legacy manifest lands dateless, and is never fresh whatever the window --
    the freshness rule's own contract, read here through the column that reports it.

    **Test steps:**

    * record a matched entry with no stamp
    * verify it reads as the stale-ok state rather than the current one
    """
    mock_listing(mocker)
    mock_record(mocker, [{"name": "notes.pdf", "xxh3": "0" * 16, "status": "matched"}])

    assert read(mocker)["notes.pdf"].checksum_state is FileChecksumState.OLD_OK


def test_a_row_in_a_subfolder_is_looked_up_by_its_record_relative_name(mocker: MockerFixture) -> None:
    """A record spells a nested file ``sub/movie.mp4`` (:func:`~rehuco_core.checksum_entry_name`), so a
    row read one level down has to ask under that name rather than its own.

    **Test steps:**

    * record an entry under the nested name
    * read the subfolder and verify the row found it
    """
    mock_listing(mocker, (DirectoryEntry("movie.mp4", FileKind.CONTENT, FileType.VIDEO),))
    mock_record(mocker, [entry("sub/movie.mp4")])

    assert read(mocker, DIRECTORY / "sub")["movie.mp4"].checksum_state is FileChecksumState.OK


def test_a_record_this_build_cannot_read_clears_every_cell(mocker: MockerFixture) -> None:
    """The folder is still the folder, so it is still listed -- with nothing claimed about any of it,
    which is honest: this build knows nothing about these files.

    **Test steps:**

    * make the record raise
    * verify the rows are there, every state is empty, and the error is reported
    """
    mock_listing(mocker)
    mock_record(mocker, None, ChecksumRecordError("version 9 is newer than this build"))
    rows = FilesRowsReader(INFO_PATH, ("Thumbs.db",), (), WEEK).read(DIRECTORY, NOW)

    assert rows.record_error
    assert {row.checksum_state for row in rows.rows} == {FileChecksumState.NONE}
    assert len(rows.rows) == len(FOLDER)


# endregion


# region The read itself


def test_a_folder_that_will_not_list_is_unreachable_rather_than_empty(mocker: MockerFixture) -> None:
    """*Empty* and *away* are not the same answer (#245): an empty table over an offline mount would
    say this resource's folder has nothing in it.

    **Test steps:**

    * make the listing raise
    * verify the read reports unreachable with no rows
    """
    mock_listing(mocker, unreachable=True)
    rows = FilesRowsReader(INFO_PATH, (), (), WEEK).read(DIRECTORY, NOW)

    assert not rows.reachable
    assert not rows.rows


def test_the_root_is_reported_as_the_root(mocker: MockerFixture) -> None:
    """What hides the parent row and greys the up action.

    **Test steps:**

    * read the resource's own folder and one below it
    * verify only the first is the root
    """
    mock_listing(mocker, ())
    mock_record(mocker, None)
    reader = FilesRowsReader(INFO_PATH, (), (), WEEK)

    assert reader.read(DIRECTORY, NOW).at_root
    assert not reader.read(DIRECTORY / "sub", NOW).at_root


def test_the_listings_own_metadata_reaches_the_row(mocker: MockerFixture) -> None:
    """Size and time come off what the listing already returned rather than a ``stat`` per entry, and a
    folder carries neither.

    **Test steps:**

    * read a folder holding one file and one subfolder
    * verify the file's size and time and the folder's absence of both
    """
    mock_listing(mocker)
    mock_record(mocker, None)
    found = read(mocker)

    assert found["notes.pdf"].size == len("notes.pdf")
    assert found["notes.pdf"].modified == MTIME
    assert found["sub"].size is None
    assert found["sub"].file_type is FileType.DIRECTORY


# endregion


# region What the table draws, and in what order


@fixture
def table(mocker: MockerFixture) -> FilesTableModel:
    """A model over a subfolder's rows, so the parent row is among them."""
    mock_listing(
        mocker,
        (
            DirectoryEntry("b.mp4", FileKind.CONTENT, FileType.VIDEO),
            DirectoryEntry("a-10.mp4", FileKind.CONTENT, FileType.VIDEO),
            DirectoryEntry("a-2.mp4", FileKind.CONTENT, FileType.VIDEO),
            DirectoryEntry("zzz", FileKind.DIRECTORY, FileType.DIRECTORY),
            DirectoryEntry("aaa", FileKind.DIRECTORY, FileType.DIRECTORY),
        ),
    )
    mock_record(mocker, None)
    model = FilesTableModel()
    model.set_rows(FilesRowsReader(INFO_PATH, (), (), WEEK).read(DIRECTORY / "sub", NOW).rows)
    return model


def drawn(proxy: FilesSortProxy, column: int = NAME_COLUMN) -> list[str]:
    """One column, in the order the table draws it.

    :param proxy: the sorted proxy to read.
    :param column: which column.
    :returns: the cells' text.
    """
    return [proxy.index(row, column).data() for row in range(proxy.rowCount())]


@mark.parametrize("order", [Qt.SortOrder.AscendingOrder, Qt.SortOrder.DescendingOrder])
def test_the_parent_row_leads_and_the_folders_follow_it_in_both_directions(
    table: FilesTableModel, order: Qt.SortOrder
) -> None:
    """A listing that put ``..`` at the bottom on a second header click would be one nobody can walk, so
    the grouping is never reversed -- only the values inside each group are.

    **Test steps:**

    * sort by name ascending, then descending
    * verify ``..`` leads and both folders sit above every file either way
    """
    proxy = FilesSortProxy()
    proxy.setSourceModel(table)
    proxy.sort(NAME_COLUMN, order)
    names = drawn(proxy)

    assert names[0] == PARENT_ROW_NAME
    assert set(names[1:3]) == {"aaa", "zzz"}
    assert names[3:] == (
        ["a-2.mp4", "a-10.mp4", "b.mp4"] if order is Qt.SortOrder.AscendingOrder else ["b.mp4", "a-10.mp4", "a-2.mp4"]
    )


def test_names_sort_naturally_rather_than_lexically(table: FilesTableModel) -> None:
    """``file-2`` before ``file-10``, the same ordering the screenshot lists already use.

    **Test steps:**

    * sort by name ascending
    * verify the two-digit name follows the one-digit one
    """
    proxy = FilesSortProxy()
    proxy.setSourceModel(table)
    proxy.sort(NAME_COLUMN, Qt.SortOrder.AscendingOrder)

    assert drawn(proxy)[3:] == ["a-2.mp4", "a-10.mp4", "b.mp4"]


def test_the_checksum_column_draws_no_text(mocker: MockerFixture) -> None:
    """Its glyph is the delegate's, and a cell answering text here would size the column for words
    nobody sees.

    **Test steps:**

    * read a folder and put it in a model
    * verify the checksum cells are empty while the other columns are not
    """
    mock_listing(mocker)
    mock_record(mocker, [entry("notes.pdf")])
    model = FilesTableModel()
    model.set_rows(FilesRowsReader(INFO_PATH, (), (), WEEK).read(DIRECTORY, NOW).rows)
    row = [model.index(position, NAME_COLUMN).data() for position in range(model.rowCount())].index("notes.pdf")

    assert model.index(row, CHECKSUM_COLUMN).data() == ""
    assert model.index(row, KIND_COLUMN).data() == "content"
    assert model.index(row, SIZE_COLUMN).data() == "9B"
    assert model.index(row, MODIFIED_COLUMN).data()


def test_the_checksum_cell_explains_its_glyph_on_hover(mocker: MockerFixture) -> None:
    """What an icon-only column owes a reader who has not learnt the glyphs yet; every other column's
    tooltip is the file's full path.

    **Test steps:**

    * read a folder against a record holding a mismatch
    * verify the checksum cell's tooltip names the verdict and the name cell's is the path
    """
    mock_listing(mocker)
    mock_record(mocker, [entry("notes.pdf", status="mismatched")])
    model = FilesTableModel()
    model.set_rows(FilesRowsReader(INFO_PATH, (), (), WEEK).read(DIRECTORY, NOW).rows)
    row = [model.index(position, NAME_COLUMN).data() for position in range(model.rowCount())].index("notes.pdf")

    assert model.index(row, CHECKSUM_COLUMN).data(Qt.ItemDataRole.ToolTipRole) == (
        "Checksum did not match when it was last checked."
    )
    assert model.index(row, NAME_COLUMN).data(Qt.ItemDataRole.ToolTipRole) == str(DIRECTORY / "notes.pdf")


def test_the_parent_rows_kind_cell_says_nothing(table: FilesTableModel) -> None:
    """``..`` is a way out rather than a thing in the folder, so naming it *folder* beside real folders
    would read as one.

    **Test steps:**

    * find the parent row
    * verify its Kind cell is empty
    """
    row = [table.index(position, NAME_COLUMN).data() for position in range(table.rowCount())].index(PARENT_ROW_NAME)

    assert table.index(row, KIND_COLUMN).data() == ""


def test_an_entry_this_build_cannot_read_says_nothing_about_its_file(mocker: MockerFixture) -> None:
    """A malformed entry is carried through untouched by the runs and reports nothing here, which leaves
    its row saying *nothing is recorded* -- the same thing a record with no entry for it says, and
    equally true.

    **Test steps:**

    * record an entry carrying two hash keys, which this build refuses to read
    * verify the row reads as missing rather than as a verdict
    """
    mock_listing(mocker)
    mock_record(mocker, [{"name": "notes.pdf", "xxh3": "0" * 16, "crc32": "42342424", "status": "matched"}])

    assert read(mocker)["notes.pdf"].checksum_state is FileChecksumState.MISSING


@mark.parametrize("column", [NAME_COLUMN, CHECKSUM_COLUMN, KIND_COLUMN, SIZE_COLUMN, MODIFIED_COLUMN])
def test_every_column_sorts_with_the_folders_still_first(table: FilesTableModel, column: int) -> None:
    """The grouping leads every column's key, so no header click can scatter the folders through the
    files or bury the way out.

    **Test steps:**

    * sort by each column in turn
    * verify ``..`` still leads and both folders still sit above every file
    """
    proxy = FilesSortProxy()
    proxy.setSourceModel(table)
    proxy.sort(column, Qt.SortOrder.AscendingOrder)
    names = drawn(proxy)

    assert names[0] == PARENT_ROW_NAME
    assert set(names[1:3]) == {"aaa", "zzz"}


def test_a_role_this_model_does_not_serve_answers_nothing(table: FilesTableModel) -> None:
    """Four roles are answered and every other one is Qt's business, not this model's: a model that
    fell through to its display text for, say, ``EditRole`` would offer an editor's initial value for a
    table nothing edits.

    **Test steps:**

    * ask a drawn cell for a role this model does not serve
    * verify it answers nothing
    """
    index = table.index(0, NAME_COLUMN)

    assert index.data(Qt.ItemDataRole.EditRole) is None
    assert index.data(Qt.ItemDataRole.DecorationRole) is None


def test_a_source_model_with_no_sort_keys_falls_back_to_the_base_comparison() -> None:
    """The tuple comparison is this proxy's own; handed a model that answers the sort role with
    something else, it defers rather than guessing -- the deference every delegate and proxy here shows
    a foreign model.

    **Test steps:**

    * sort a proxy over a model whose sort role answers nothing
    * verify it still produced an order rather than raising
    """
    proxy = FilesSortProxy()
    source = KeylessModel()
    proxy.setSourceModel(source)
    proxy.sort(NAME_COLUMN, Qt.SortOrder.AscendingOrder)

    # the base's own ordering, whatever it is -- the claim is that it deferred rather than raised or
    # dropped rows, not that Qt orders strings the way this proxy's keys would
    assert set(drawn(proxy)) == set(KEYLESS_NAMES)


def test_an_invalid_index_answers_nothing(table: FilesTableModel) -> None:
    """What Qt asks a model during teardown and while a view is between models; a model that indexed
    its rows anyway would raise there.

    **Test steps:**

    * ask an invalid index for data and for flags
    * verify neither answers anything
    """
    invalid = QModelIndex()

    assert table.data(invalid) is None
    assert table.flags(invalid) == Qt.ItemFlag.NoItemFlags
    assert table.headerData(0, Qt.Orientation.Vertical) is None
    assert table.rowCount(table.index(0, NAME_COLUMN)) == 0
    assert table.columnCount(table.index(0, NAME_COLUMN)) == 0


# endregion


# region The loader


def test_a_read_that_raises_still_reports_back(qtbot: QtBot, mocker: MockerFixture) -> None:
    """An exception escaping onto the pool is printed and swallowed there, and the ``loaded`` that never
    arrived would leave the dock saying *reading* for the rest of the document's life.

    **Test steps:**

    * make the read raise
    * verify the loader still reported, as an unreachable answer naming the failure
    """
    reader = FilesRowsReader(INFO_PATH, (), (), WEEK)
    mocker.patch.object(FilesRowsReader, "read", side_effect=RuntimeError("boom"))
    loader = FilesRowsLoader()

    with qtbot.waitSignal(loader.loaded, timeout=5000) as reported:
        loader.start(reader, DIRECTORY)

    rows = reported.args[0] if reported.args else None
    assert isinstance(rows, FilesRows)
    # pylint cannot see past the signal blocker's args to the FilesRows the isinstance has established
    assert not rows.reachable  # pylint: disable=no-member
    assert "boom" in rows.record_error  # pylint: disable=no-member


def test_a_superseded_read_is_dropped_rather_than_drawn(qtbot: QtBot, mocker: MockerFixture) -> None:
    """Walking into a subfolder while the previous listing is still out is the ordinary case here, so an
    answer from an older read must not be drawn over the folder the reader has since moved to.

    **Test steps:**

    * hold the first read until a second has been started, then release it
    * verify only the second directory was ever reported
    """
    reader = FilesRowsReader(INFO_PATH, (), (), WEEK)
    started = Event()
    release = Event()

    def read(directory: Path, _now: datetime) -> FilesRows:
        if directory == DIRECTORY:
            started.set()
            # the gate outlasts this test's own assertions: the first read is held until the second has
            # been enqueued, which is what makes "superseded" deterministic rather than a race
            release.wait(timeout=5)
        return FilesRows(directory)

    mocker.patch.object(FilesRowsReader, "read", side_effect=read)
    loader = FilesRowsLoader()
    reported: list[Path] = []
    loader.loaded.connect(lambda rows: reported.append(rows.directory))

    loader.start(reader, DIRECTORY)
    assert started.wait(timeout=5)
    loader.start(reader, DIRECTORY / "sub")
    release.set()
    qtbot.waitUntil(lambda: reported == [DIRECTORY / "sub"], timeout=5000)

    assert reported == [DIRECTORY / "sub"]


def test_a_listing_that_answers_after_its_dock_is_gone_reports_into_nothing(mocker: MockerFixture) -> None:
    """The same failure `ChecksumRowsLoader` documents, for the browser's own read: the loader is
    parented to the dock, so closing a document takes its C++ half while a listing is still out on a
    share -- and the exception that emit would raise is printed and swallowed by the pool, which is the
    kind of failure nobody ever sees reported.

    **Test steps:**

    * destroy the loader's C++ object the way closing a document does, then let a read answer
    * verify the run returned quietly rather than raising into the pool
    """
    mocker.patch.object(FilesRowsReader, "read", return_value=FilesRows(DIRECTORY))
    dock = QObject()
    loader = FilesRowsLoader(dock)
    delivered: list[FilesRows] = []
    # connected, because an emit with nobody listening never reaches the deleted C++ half at all --
    # which is exactly the case this guard is *not* about
    loader.loaded.connect(delivered.append)
    run = loader._FilesRowsLoader__run  # type: ignore[attr-defined]  # pylint: disable=protected-access
    shiboken6.delete(dock)
    assert not shiboken6.isValid(loader)

    # generation 0 is the one a loader that has never been started is on, so this read is current
    # rather than superseded -- otherwise it returns before it ever tries to report
    run(FilesRowsReader(INFO_PATH, (), (), WEEK), DIRECTORY, NOW, 0)

    assert not delivered


# endregion
