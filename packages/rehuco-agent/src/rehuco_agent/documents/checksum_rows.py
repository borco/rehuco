"""One resource's checksum record as table rows ([[data-model#checksums]], #244).

**The rows come from the record *and* from the content enumeration**, merged here. An entry the record
holds shows its recorded status and date; a content file the record does not cover shows its path with
both cells empty, which is what *not checked yet* honestly looks like -- and is what makes the dock
worth opening on a resource that has never been checksummed at all. The enumeration is #226's shared
answer, the same set the size scan counts, so a file the table calls uncovered is exactly a file a
verify would adopt.

**The table shows the record, not the last run's report** (#244). The two differ on purpose -- a run
*reports* an adopted file ``unexpected`` while *recording* it ``matched`` -- and a view of the report
would go stale the moment anything else touched the resource. The transient report is the inline strip's
and the log's (#204).

**Reading it is a directory walk**, on a catalog that lives on an SMB mount
([[packaging-deployment#ts230-as-nas]]), so it never happens on the GUI thread:
:class:`ChecksumRowsLoader` runs :func:`read_checksum_rows` on the global pool and delivers the answer
back through a queued signal.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final, override

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QSortFilterProxyModel,
    Qt,
    QThreadPool,
    Signal,
)
from rehuco_core import (
    CHECKSUM_FILES_KEY,
    ChecksumRecordError,
    ScreenshotNamePattern,
    checksum_record_path,
    enumerate_content_files,
    load_checksum_record,
    parse_checksum_entry,
)

from .files_rows import CHECKSUM_STATE_TOOLTIPS, FileChecksumState, checksum_state_for

type ModelIndex = QModelIndex | QPersistentModelIndex
"""What Qt hands a model method; the persistent form arrives from a view holding onto an index."""

PATH_COLUMN: Final = 0
STATUS_COLUMN: Final = 1
DATE_COLUMN: Final = 2
COLUMN_COUNT: Final = 3
COLUMN_TITLES: Final = ("File", "", "Checked")
"""The three columns the table draws.

The Status column's title is **empty** on purpose, the same reason
:data:`~rehuco_agent.documents.files_rows.COLUMN_TITLES` is for the file browser's own checksum column:
it holds one 16px glyph, and a word above it would set the column's width to the word rather than to
the glyph. What each glyph means is on its tooltip (#303)."""

MISSING_STATUS: Final = "missing"
"""The one status a surface has to reason about by name (#244).

*Delete missing* is scoped to it, because dropping the entry of a file that is still on disk achieves
nothing -- the next verify adopts it straight back ([[data-model#checksums]])."""

DATE_FORMAT: Final = "%Y-%m-%d %H:%M"
"""How a recorded moment is drawn: **local time**, to the minute.

The record stores UTC ([[data-model#checksums]]), which is the right thing to store and not what anyone
wants to read off a table; seconds are noise on a stamp whose whole purpose is answering *how long
ago*."""


@dataclass(frozen=True, slots=True)
class ChecksumRow:
    """One file, as the table shows it (#244).

    :param name: the file as the record spells it -- relative to the ``.rehu``, POSIX-separated.
    :param status: what the last check answered, or ``""`` for a content file the record does not
        cover. Carried as the record spells it rather than mapped to a label: the statuses are already
        the words [[data-model#checksums]] uses, and a second vocabulary would only have to be kept in
        step with the first.
    :param verified: when that status was recorded, or ``None`` -- never checked, or a stamp the record
        reader could not make sense of, which reads as *never* for the same reason it does there.
    :param checksum_state: what the Status column draws for this row -- the same
        :class:`~rehuco_agent.documents.files_rows.FileChecksumState` the file browser resolves an entry
        to (#303), so a file's verdict reads the same glyph in both docks.
    """

    name: str
    status: str = ""
    verified: datetime | None = None
    checksum_state: FileChecksumState = FileChecksumState.MISSING


@dataclass(frozen=True, slots=True)
class ChecksumRows:
    """What one read of a resource established, rows and reachability together (#244).

    :param rows: one per file, record entries first in the record's own order, then the content files
        it does not cover in enumeration order. Deliberately not sorted here -- the view sorts, and a
        read that imposed an order would fight it.
    :param reachable: whether the resource's own directory listed. **The record shares its files'
        fate**: if the mount is away the ``.checksum`` is as unreachable as the content it describes, so
        one answer covers both, and every action is greyed on it (#245, #244).
    :param error: why the record could not be read at all, when that is what happened -- a file this
        build cannot parse. Distinct from an empty record, which is a real and ordinary state.
    """

    rows: tuple[ChecksumRow, ...] = ()
    reachable: bool = True
    error: str = ""


def read_checksum_rows(
    rehu_path: Path,
    excluded_patterns: tuple[str, ...],
    screenshot_name_patterns: tuple[ScreenshotNamePattern, ...],
    stale_after: timedelta,
    now: datetime,
) -> ChecksumRows:
    """Read one resource's record and enumerate its content, merged into rows (#244).

    Called on a worker thread, so it touches no widget and no ``QObject`` -- a plain filesystem read
    answering a plain value, the shape :class:`~rehuco_agent.fields.BackgroundMeasurement` established
    for the size scan this walk shares (#226).

    :param rehu_path: the resource's ``.rehu`` file.
    :param excluded_patterns: the filename globs the content walk leaves out (#226), resolved by the
        caller the way every other core call takes them.
    :param screenshot_name_patterns: the naming rules a ``.tc``'s screenshots are recognized by (#53),
        resolved by the caller the same way.
    :param stale_after: the staleness window a run would use, so a row's state matches what
        *Verify Old* would actually do with it (#303).
    :param now: the instant to measure freshness against, so every row of one read is judged against
        one moment.
    :returns: the rows, and whether the resource was reachable at all.
    """
    enumeration = enumerate_content_files(rehu_path, excluded_patterns, screenshot_name_patterns)
    if not enumeration.reachable:
        return ChecksumRows(reachable=False)
    content = [path.relative_to(rehu_path.parent).as_posix() for path in enumeration.files]
    try:
        record = load_checksum_record(checksum_record_path(rehu_path))
    except FileNotFoundError:
        record = None
    except (OSError, ChecksumRecordError) as error:
        # NONE, not MISSING: the record exists and could not be read, so this build knows nothing about
        # these bytes -- a `missing` glyph would claim there is no hash and invite a generate over one.
        # The same answer the file browser gives for an unreadable record (#303)
        return ChecksumRows(
            rows=tuple(ChecksumRow(name, checksum_state=FileChecksumState.NONE) for name in content),
            error=str(error),
        )
    rows: list[ChecksumRow] = []
    if record is not None:
        # an entry this build cannot name is left out: a row that cannot say which file it is about is
        # not one a reader can select, verify or forget, and core already carries it through untouched
        for raw in record[CHECKSUM_FILES_KEY]:
            entry = parse_checksum_entry(raw)
            if entry is not None:
                state = checksum_state_for(entry, stale_after, now)
                rows.append(ChecksumRow(entry.name, entry.status or "", entry.verified, state))
    recorded = {row.name for row in rows}
    rows.extend(ChecksumRow(name, checksum_state=FileChecksumState.MISSING) for name in content if name not in recorded)
    return ChecksumRows(rows=tuple(rows))


class ChecksumRowsLoader(QObject):
    """Reads a resource's rows off the GUI thread and delivers them back onto it (#244).

    The same shape :class:`~rehuco_agent.fields.BackgroundMeasurement` uses, and deliberately its own
    class rather than that one: what comes back here is a table's worth of rows plus a reachability
    verdict, not a measured number, and teaching one runner both would put this surface's policy inside
    a field's helper.

    **A read already in flight is not cancelled, it is disowned.** A rename or a finished job can ask
    for a re-read while the first walk is still round-tripping over a mount; each read carries the
    generation it was started in, and an answer from an older one is dropped rather than drawn. That is
    cheaper and more honest than trying to interrupt a walk that has no checkpoint.

    :param parent: optional Qt parent.
    """

    loaded = Signal(object)
    """Fires on the GUI thread with the :class:`ChecksumRows` of the **most recent** request.

    Queued, because the emit happens on a pool thread. Fires exactly once per :meth:`start` that was
    still current when it finished, **including when the read raised**, so a caller that showed a busy
    state always gets it back."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__generation = 0

    def start(
        self,
        rehu_path: Path,
        excluded_patterns: tuple[str, ...],
        screenshot_name_patterns: tuple[ScreenshotNamePattern, ...],
        stale_after: timedelta,
    ) -> None:
        """Read ``rehu_path``'s rows on a pool thread and emit :attr:`loaded` with them.

        :param rehu_path: the resource's ``.rehu`` file.
        :param excluded_patterns: the filename globs the content walk leaves out (#226).
        :param screenshot_name_patterns: the naming rules a ``.tc``'s screenshots are recognized by (#53).
        :param stale_after: the staleness window a run would use (#303).
        """
        self.__generation += 1
        generation = self.__generation
        # taken here, on the GUI thread, so every row of one read is judged against one moment -- and a
        # frozen clock in a test needs no reach into the pool (the same reason FilesRowsLoader.start does)
        now = datetime.now(tz=UTC)
        QThreadPool.globalInstance().start(
            lambda: self.__run(rehu_path, excluded_patterns, screenshot_name_patterns, stale_after, now, generation)
        )

    def __run(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        rehu_path: Path,
        excluded_patterns: tuple[str, ...],
        screenshot_name_patterns: tuple[ScreenshotNamePattern, ...],
        stale_after: timedelta,
        now: datetime,
        generation: int,
    ) -> None:
        """Do the read on the worker thread and report it, raise or no raise.

        The blanket catch is the point rather than a shortcut: an exception escaping here is printed and
        swallowed by the pool, and the :attr:`loaded` that never arrived would leave the dock showing a
        busy state for the rest of the document's life.

        **The emit is guarded too, and for a different reason.** A document can be closed while its walk
        is still out on a mount; this object is parented to the dock, so by the time the walk answers
        its C++ half may be gone, and emitting from a deleted ``QObject`` raises on the pool thread.
        Reporting into a document that no longer exists is exactly the nothing it should be.

        :param rehu_path: the resource's ``.rehu`` file.
        :param excluded_patterns: the filename globs the content walk leaves out.
        :param screenshot_name_patterns: the naming rules a ``.tc``'s screenshots are recognized by.
        :param stale_after: the staleness window a run would use.
        :param now: the instant to measure freshness against.
        :param generation: which request this is, so a superseded answer can be dropped.
        """
        try:
            rows = read_checksum_rows(rehu_path, excluded_patterns, screenshot_name_patterns, stale_after, now)
        except Exception as error:  # pylint: disable=broad-exception-caught
            rows = ChecksumRows(error=str(error))
        if generation != self.__generation:
            return
        try:
            self.loaded.emit(rows)
        except RuntimeError:
            # the dock this belongs to was destroyed while the walk was out
            pass


class ChecksumTableModel(QAbstractTableModel):
    """The rows, as a table (#244).

    A plain snapshot holder: it is handed a :class:`ChecksumRows` and shows it, and every refresh is a
    whole new read. There is nothing to diff -- a verify rewrites most of a record at once -- and a
    model that tried would be guessing at what a run did rather than reading what it wrote.

    Sort keys are served under :data:`SORT_ROLE` so the proxy sorts on the value rather than on the
    drawn text: a date sorts chronologically rather than lexically, and an unchecked row sorts together
    with the other unchecked ones instead of wherever ``""`` happens to fall against a formatted stamp.

    :param parent: optional Qt parent.
    """

    SORT_ROLE: Final = Qt.ItemDataRole.UserRole
    """The role :class:`ChecksumSortProxy` sorts on -- the underlying value, never the drawn text."""

    ROW_ROLE: Final = Qt.ItemDataRole.UserRole + 1
    """The whole :class:`ChecksumRow`, for the delegate that draws its Status glyph -- the same role
    :class:`~rehuco_agent.documents.files_rows.FilesTableModel.ROW_ROLE` serves the file browser's own
    delegate (#303)."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__rows: tuple[ChecksumRow, ...] = ()

    def set_rows(self, rows: tuple[ChecksumRow, ...]) -> None:
        """Replace everything shown.

        :param rows: the rows to show.
        """
        self.beginResetModel()
        self.__rows = rows
        self.endResetModel()

    def row_at(self, row: int) -> ChecksumRow:
        """The row behind a source-model index.

        :param row: the source row number.
        :returns: that row.
        """
        return self.__rows[row]

    @override
    def rowCount(self, parent: ModelIndex = QModelIndex()) -> int:
        """See ``QAbstractTableModel``: a flat table has rows only at the root."""
        return 0 if parent.isValid() else len(self.__rows)

    @override
    def columnCount(self, parent: ModelIndex = QModelIndex()) -> int:
        """See ``QAbstractTableModel``: :data:`COLUMN_COUNT` at the root, none under a cell."""
        return 0 if parent.isValid() else COLUMN_COUNT

    @override
    def data(self, index: ModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        """What one cell shows, and what it sorts on.

        :param index: the cell.
        :param role: what is being asked for.
        :returns: the cell's value for that role, or ``None``.
        """
        if not index.isValid():
            return None
        row = self.__rows[index.row()]
        if role == ChecksumTableModel.ROW_ROLE:
            return row
        if role == Qt.ItemDataRole.DisplayRole:
            return ChecksumTableModel.__display(row, index.column())
        if role == ChecksumTableModel.SORT_ROLE:
            return ChecksumTableModel.__sort_key(row, index.column())
        if role == Qt.ItemDataRole.ToolTipRole:
            return ChecksumTableModel.__tooltip(row, index.column())
        return None

    @staticmethod
    def __display(row: ChecksumRow, column: int) -> str:
        """One cell's drawn text.

        The Status column draws **none**: its glyph is
        :class:`~rehuco_agent.documents.checksum_row_delegate.ChecksumRowDelegate`'s, and a cell
        answering text here would size the column for a word nobody sees (#303).

        :param row: the row.
        :param column: which column.
        :returns: the text, ``""`` where there is nothing to draw.
        """
        if column == PATH_COLUMN:
            return row.name
        if column == STATUS_COLUMN:
            return ""
        return "" if row.verified is None else row.verified.astimezone().strftime(DATE_FORMAT)

    @staticmethod
    def __sort_key(row: ChecksumRow, column: int) -> Any:
        """One cell's sort value.

        A never-checked row sorts as a stamp older than any real one rather than as ``""``, so the rows
        with nothing recorded gather at one end instead of interleaving with formatted dates. The Status
        column sorts on the resolved :attr:`~ChecksumRow.checksum_state` rather than the raw text, the
        same as :meth:`~rehuco_agent.documents.files_rows.FilesTableModel.__sort_key` does for its own
        checksum column -- what the column now draws is the state, not the status.

        :param row: the row.
        :param column: which column.
        :returns: the value to sort that column on.
        """
        if column == PATH_COLUMN:
            return row.name
        if column == STATUS_COLUMN:
            return row.checksum_state.value
        return "" if row.verified is None else row.verified.isoformat()

    @staticmethod
    def __tooltip(row: ChecksumRow, column: int) -> str:
        """One cell's tooltip -- the Status glyph's meaning, and the full name elsewhere.

        :param row: the row.
        :param column: which column.
        :returns: the tooltip.
        """
        if column == STATUS_COLUMN:
            return CHECKSUM_STATE_TOOLTIPS.get(row.checksum_state, "")
        return row.name

    @override
    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        """The column titles; there is no vertical header (#303).

        :param section: the column or row.
        :param orientation: which header.
        :param role: what is being asked for.
        :returns: the title, or ``None``.
        """
        if role != Qt.ItemDataRole.DisplayRole or orientation is not Qt.Orientation.Horizontal:
            return None
        return COLUMN_TITLES[section] if 0 <= section < COLUMN_COUNT else None


class ChecksumSortProxy(QSortFilterProxyModel):
    """Sorts the table (#244).

    A proxy rather than sorting in place, so a selection survives a sort: Qt maps persistent indexes
    through it, where a source-side reset would drop the selection every time a header was clicked --
    the same reason :class:`~rehuco_agent.documents.files_rows.FilesSortProxy` is one.

    No row-number column and no numbered vertical header, matching the file browser (#303): the count
    is already in the summary line under the table (:func:`tally_text`), which answers *how many*
    without costing a column, or a header, on every row.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.setSortRole(ChecksumTableModel.SORT_ROLE)


@dataclass(frozen=True, slots=True)
class ChecksumTally:
    """How many files, and how many of what -- the summary line under the table (#244).

    The one place a reader still gets *how many* now that the table draws no row numbers (#303); this
    answers *how many of what*, which is the question a verify actually raises.

    :param total: how many rows the table holds.
    :param statuses: how many rows carry each recorded status.
    :param not_recorded: how many carry none -- content the record does not cover.
    """

    total: int = 0
    statuses: dict[str, int] = field(default_factory=dict)
    not_recorded: int = 0


def tally_rows(rows: tuple[ChecksumRow, ...]) -> ChecksumTally:
    """Count what the table is showing.

    :param rows: the rows.
    :returns: the counts behind the summary line.
    """
    statuses: dict[str, int] = {}
    not_recorded = 0
    for row in rows:
        if row.status:
            statuses[row.status] = statuses.get(row.status, 0) + 1
        else:
            not_recorded += 1
    return ChecksumTally(total=len(rows), statuses=statuses, not_recorded=not_recorded)


def tally_text(tally: ChecksumTally) -> str:
    """The summary line, e.g. ``214 files · 210 matched · 2 mismatched · 1 not recorded``.

    :param tally: what the table is showing.
    :returns: the line, with the counts that are zero left out -- a summary naming everything it did
        *not* find would bury the one number that moved.
    """
    parts = [f"{tally.total} file{'' if tally.total == 1 else 's'}"]
    parts.extend(f"{count} {status}" for status, count in sorted(tally.statuses.items()))
    if tally.not_recorded:
        parts.append(f"{tally.not_recorded} not recorded")
    return " · ".join(parts)
