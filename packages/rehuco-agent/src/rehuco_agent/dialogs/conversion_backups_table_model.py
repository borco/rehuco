"""The `Conversion Backups…` dialog's table: one row per **resource** that still holds retained
conversion backups, a checkbox to select it, and -- once an action has run -- what became of it (#193).

**Grouped per resource, not per file.** A converted tutorial holds six `.orig` files and one decision;
listing the files would put six rows in front of a reader who can only revert or discard the resource as
a whole ([[acquisition-tooling#convert-mechanics]]). The file count and the bytes are what the resource's
row *says*, not what it is split into.
"""

# the Qt model boilerplate -- rowCount/columnCount/headerData/flags/data/setData over a list of
# checkbox-plus-text rows -- reads the same here as in tc_conversion_plan_table_model, because it is the
# same contract written out the way Qt wants it. Worth a shared base once a third such table exists;
# extracting one now would mean reshaping #192's table for a symmetry #193 alone does not need.
# pylint: disable=duplicate-code

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, override

import humanize
from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QPersistentModelIndex, QSortFilterProxyModel, Qt
from rehuco_core import ConversionBackups

type ModelIndex = QModelIndex | QPersistentModelIndex
"""What Qt hands a model method; the persistent form arrives from a view holding onto an index."""

CHECKED_COLUMN: Final = 0
RESOURCE_COLUMN: Final = 1
CONVERTED_COLUMN: Final = 2
BACKUPS_COLUMN: Final = 3
FLAGS_COLUMN: Final = 4
OUTCOME_COLUMN: Final = 5

COLUMN_TITLES: Final = ("", "Resource", "Converted", "Backups", "Flags", "Outcome")

TEXT_COLUMNS: Final = (RESOURCE_COLUMN, CONVERTED_COLUMN, BACKUPS_COLUMN, FLAGS_COLUMN, OUTCOME_COLUMN)
"""The columns the filter matches against -- everything except the checkbox."""

TIE_BREAK_FLAG: Final = "tie-break"
EDITED_SINCE_FLAG: Final = "edited since"
NOT_REVERTIBLE_FLAG: Final = "not revertible"
"""What a row's Flags column can say (#193).

The three a :class:`~rehuco_core.ConversionBackups` can actually answer, and each is a reason to look:
a **tie-break** dropped a recognized screenshot, an **edited since** row would lose real work to a
revert, and a **not revertible** one has no backed-up `.tc` or an occupied restore target, so only
discarding is left. Filtering by :data:`TIE_BREAK_FLAG` is the review pass #192 deliberately skipped."""

NO_FLAGS: Final = "—"
NO_OUTCOME: Final = "—"

REFUSED_OUTCOME: Final = "refused"
"""What a row reads when the dialog declined to enqueue a revert over it at all -- the inventory already
says it cannot run, so asking the queue would only buy the same answer later and noisier."""


def format_size(total_bytes: int) -> str:
    """Render a byte total the way this dialog's rows and header say it.

    Long-form (``"14.0 MB"``) rather than the ``ls -sh`` style
    :meth:`~rehuco_agent.fields.widgets.SizeMeasurementEdit.format` uses: a size *field* sits in a dense
    grid beside its own label, while this is prose in a sentence about reclaiming space.

    :param total_bytes: the size to render.
    :returns: the formatted text.
    """
    return humanize.naturalsize(total_bytes)


def describe_backups(backups: ConversionBackups) -> str:
    """What one resource's retained backups amount to, e.g. ``"6 files, 14.0 MB"``.

    :param backups: the resource's inventory.
    :returns: the summary text.
    """
    count = len(backups.backups)
    return f"{count} file{'' if count == 1 else 's'}, {format_size(backups.total_bytes)}"


@dataclass
class ConversionBackupsRow:
    """One table row: a resource's inventory, whether it is selected, and what became of it.

    :param backups: what this resource still holds, and what a revert would put back (#190).
    :param checked: whether this row is selected for the next action.
    :param outcome: ``None`` before an action has run over this row; ``"pending"`` once its job is
        enqueued; ``"reverted"``/``"discarded"``/``"failed"``/``"cancelled"`` once it finishes; or
        :data:`REFUSED_OUTCOME` for a revert the dialog declined to enqueue at all.
    :param message: why a ``"failed"`` or :data:`REFUSED_OUTCOME` row did not happen, else ``None``.
    """

    backups: ConversionBackups
    checked: bool
    outcome: str | None = None
    message: str | None = None

    @property
    def path(self) -> Path:
        """The converted resource's ``.rehu`` -- this row's identity, and what a job is enqueued over."""
        return self.backups.rehu_path

    def flags(self) -> tuple[str, ...]:
        """Every reason this row is worth a look, in a fixed order.

        :returns: the active flags; empty when there is nothing to say about this resource beyond that
            it still has backups.
        """
        active: list[str] = []
        if self.backups.dropped_screenshots:
            active.append(TIE_BREAK_FLAG)
        if self.backups.edited_since:
            active.append(EDITED_SINCE_FLAG)
        if not self.backups.revertible:
            active.append(NOT_REVERTIBLE_FLAG)
        return tuple(active)


class ConversionBackupsTableModel(QAbstractTableModel):
    """One row per resource that still holds retained conversion backups, with its checkbox and outcome.

    **Every row starts checked.** Unlike the import wizard's plan table -- where a blocked row starts
    unchecked because checking it *is* an override (#192) -- nothing here is dangerous to *select*; the
    danger is entirely in which action is then run, and both of those confirm. Starting checked is what
    makes the common ending of the import flow (look at the flagged few, then discard the rest) one
    filter and one click.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__root = Path()
        self.__rows: list[ConversionBackupsRow] = []
        self.__index_by_path: dict[Path, int] = {}

    # region Building and reading

    def set_backups(self, root: Path, resources: Sequence[ConversionBackups]) -> None:
        """Replace every row, as one model reset.

        :param root: the folder the resources were scanned from, for the relative paths shown.
        :param resources: the scan's resources (#193); every one starts checked.
        """
        self.beginResetModel()
        self.__root = root
        self.__rows = [ConversionBackupsRow(backups, checked=True) for backups in resources]
        self.__index_by_path = {row.path: index for index, row in enumerate(self.__rows)}
        self.endResetModel()

    def rows(self) -> tuple[ConversionBackupsRow, ...]:
        """Every row, in scan order."""
        return tuple(self.__rows)

    def checked_rows(self) -> tuple[ConversionBackupsRow, ...]:
        """The rows currently selected."""
        return tuple(row for row in self.__rows if row.checked)

    def set_checked(self, paths: Collection[Path], checked: bool) -> None:
        """Check or uncheck exactly ``paths``, as one repaint.

        How *select all* is spelled: the dialog hands in whichever rows the filter currently shows, so
        selecting all of a filtered view selects what a reader can see rather than the whole scan --
        which is the entire point of having filtered.

        :param paths: the resources to change; one this model has no row for is ignored.
        :param checked: what to set them to.
        """
        changed = [self.__index_by_path[path] for path in paths if path in self.__index_by_path]
        if not changed:
            return
        for row in changed:
            self.__rows[row].checked = checked
        self.dataChanged.emit(
            self.index(min(changed), CHECKED_COLUMN),
            self.index(max(changed), CHECKED_COLUMN),
            [Qt.ItemDataRole.CheckStateRole],
        )

    def set_row_outcome(self, rehu_path: Path, outcome: str, message: str | None = None) -> None:
        """Record what became of the resource at ``rehu_path``, and repaint its row.

        A no-op for a path this model has no row for -- the scan was rebuilt since the job that reports
        this was enqueued, which the outcome then has nowhere honest to land.

        :param rehu_path: the resource the outcome is about.
        :param outcome: one of the values :attr:`ConversionBackupsRow.outcome` documents.
        :param message: why a failed or refused outcome did not happen, else ``None``.
        """
        row = self.__index_by_path.get(rehu_path)
        if row is None:
            return
        self.__rows[row].outcome = outcome
        self.__rows[row].message = message
        cell = self.index(row, OUTCOME_COLUMN)
        self.dataChanged.emit(cell, cell)

    # endregion

    # region Qt model interface

    @override
    def rowCount(self, parent: ModelIndex = QModelIndex()) -> int:  # noqa: N802  (Qt API name)
        return 0 if parent.isValid() else len(self.__rows)

    @override
    def columnCount(self, parent: ModelIndex = QModelIndex()) -> int:  # noqa: N802  (Qt API name)
        return 0 if parent.isValid() else len(COLUMN_TITLES)

    @override
    def headerData(  # noqa: N802  (Qt API name)
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return COLUMN_TITLES[section]
        return None

    @override
    def flags(self, index: ModelIndex) -> Qt.ItemFlag:
        base = super().flags(index)
        if not index.isValid():
            return base
        if index.column() == CHECKED_COLUMN:
            return base | Qt.ItemFlag.ItemIsUserCheckable
        return base

    @override
    # six columns, each with its own answer -- collapsing them behind one exit would need a sentinel
    # meaning both "no answer" and "the answer is None"
    def data(self, index: ModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:  # pylint: disable=too-many-return-statements
        if not index.isValid():
            return None
        row = self.__rows[index.row()]
        column = index.column()
        if column == CHECKED_COLUMN and role == Qt.ItemDataRole.CheckStateRole:
            return Qt.CheckState.Checked if row.checked else Qt.CheckState.Unchecked
        if role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return None
        if column == RESOURCE_COLUMN:
            return self.__relative(row.path)
        if column == CONVERTED_COLUMN:
            return row.backups.converted or NO_OUTCOME
        if column == BACKUPS_COLUMN:
            return describe_backups(row.backups)
        if column == FLAGS_COLUMN:
            return ", ".join(row.flags()) or NO_FLAGS
        if column == OUTCOME_COLUMN:
            return self.__outcome_text(row)
        return None

    @override
    def setData(  # noqa: N802  (Qt API name)
        self, index: ModelIndex, value: Any, role: int = Qt.ItemDataRole.EditRole
    ) -> bool:
        if not index.isValid() or index.column() != CHECKED_COLUMN or role != Qt.ItemDataRole.CheckStateRole:
            return False
        self.__rows[index.row()].checked = Qt.CheckState(value) == Qt.CheckState.Checked
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.CheckStateRole])
        return True

    # endregion

    def __relative(self, path: Path) -> str:
        """``path`` relative to the scanned root, or the path itself when it does not sit under it."""
        try:
            return path.relative_to(self.__root).as_posix()
        except ValueError:
            return str(path)

    @staticmethod
    def __outcome_text(row: ConversionBackupsRow) -> str:
        """What became of ``row``, or an em dash before anything has run over it.

        :param row: the row to describe.
        :returns: the outcome text, with a failure's or a refusal's reason appended.
        """
        if row.outcome is None:
            return NO_OUTCOME
        if row.message:
            return f"{row.outcome}: {row.message}"
        return row.outcome


class ConversionBackupsFilterProxyModel(QSortFilterProxyModel):
    """Shows only rows whose text columns contain the filter text, case-insensitive (#193).

    A plain-substring match, the same shape
    :class:`~rehuco_agent.dialogs.tc_conversion_plan_table_model.TcConversionPlanFilterProxyModel` uses
    and for the same reason: a regex round trip through Qt's own fixed-string filter would need
    un-escaping :meth:`set_filter_text`'s plain text back out of it to match against.

    Typing a flag's own word (:data:`TIE_BREAK_FLAG`) is how the review pass is reached, which is why
    the Flags column is one of the columns matched rather than a separate control.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__filter_text = ""

    def set_filter_text(self, text: str) -> None:
        """Update the filter text and re-evaluate every row.

        :param text: the text to match the resource, converted, backups, flags and outcome columns
            against, case-insensitively.
        """
        self.__filter_text = text
        # invalidateFilter() is deprecated in this Qt version; invalidate() is the non-deprecated
        # equivalent, and this proxy never overrides lessThan so it costs nothing extra here.
        self.invalidate()

    @override
    def filterAcceptsRow(self, source_row: int, source_parent: ModelIndex) -> bool:  # noqa: N802  (Qt API name)
        if not self.__filter_text:
            return True
        model = self.sourceModel()
        needle = self.__filter_text.lower()
        return any(
            needle
            in str(model.data(model.index(source_row, column, source_parent), Qt.ItemDataRole.DisplayRole)).lower()
            for column in TEXT_COLUMNS
        )
