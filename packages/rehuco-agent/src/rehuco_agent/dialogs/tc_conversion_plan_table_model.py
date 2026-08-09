"""The `Import Legacy Catalog…` wizard's plan/result table: one row per resource the scan found, a
checkbox to select it, and -- once import has run -- what became of it (#192).

One model serves both the plan step and the result step: the rows, the paths and the flags never
change once the scan is done, only what each row's checkbox and outcome say. A second model for the
result table would need to be built from the first row for row, and would let the two drift.

**Two kinds of row, one table** (#259). A `.tc` to convert, and an already-converted resource still
carrying the legacy manifest its `.checksum` was made from -- both are *one resource, one job, one
outcome*, which is the whole of what a row means here, so a second table would repeat this one's
checkbox, filter, outcome column and Retry Failed to say nothing new. What differs is three cells and
the job the wizard enqueues.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, override

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QPersistentModelIndex, QSortFilterProxyModel, Qt
from rehuco_core import StrandedManifestPlan, TcConversionPlan

type ModelIndex = QModelIndex | QPersistentModelIndex
"""What Qt hands a model method; the persistent form arrives from a view holding onto an index."""

CHECKED_COLUMN: Final = 0
PATH_COLUMN: Final = 1
TARGET_COLUMN: Final = 2
SCREENSHOTS_COLUMN: Final = 3
FLAGS_COLUMN: Final = 4
OUTCOME_COLUMN: Final = 5

COLUMN_TITLES: Final = ("", "Path", "Target", "Screenshots", "Flags", "Outcome")

FLAG_LABELS: Final = (
    ("rehu_exists", "target exists"),
    ("stale_backup", "stale backup"),
    ("tie_break", "tie-break"),
    ("size_unparsed", "size unparsed"),
    ("duration_present", "duration advisory"),
    ("unmapped_keys", "unmapped keys"),
    ("suspect_mtime", "suspect mtime"),
)
"""Every :class:`~rehuco_core.TcConversionPlan` flag, in the order the Flags column lists them, paired
with the word a reader sees rather than the attribute name (#191)."""

STRANDED_FLAG: Final = "stranded manifest"
"""What the Flags column says of a :class:`~rehuco_core.StrandedManifestPlan` row (#259).

The one word that column has to carry for such a row -- there is nothing else to flag, since a
remediation makes no judgement calls and can be neither blocked nor tie-broken. Written as a flag rather
than as a row *type* column so the filter that already searches flags finds these by name."""


@dataclass
class TcConversionRow:
    """One table row: a plan, whether it is selected, and what became of it once import has run.

    :param plan: the dry-run plan this row shows -- a conversion (#191) or a stranded manifest (#259).
    :param checked: whether this row is selected for import -- for a
        :attr:`~rehuco_core.TcConversionPlan.blocked` row, checking it **is** the explicit per-row
        opt-in #192 requires before a blocked resource is enqueued at all.
    :param outcome: ``None`` before import has run over this row; ``"pending"`` once its job is
        enqueued; ``"converted"``/``"retired"``/``"failed"``/``"cancelled"`` once it finishes;
        ``"skipped"`` for a row import ran without, because it was left unchecked.
    :param message: why a ``"failed"`` row failed, else ``None``.
    """

    plan: TcConversionPlan | StrandedManifestPlan
    checked: bool
    outcome: str | None = None
    message: str | None = None

    @property
    def path(self) -> Path:
        """This row's identity -- the `.tc` it converts, or the `.rehu` it remediates.

        What the model keys rows by and what a finished job's ``source`` answers, so an outcome always
        finds its own row. The two can never collide: a conversion row is a `.tc` and a stranded row is
        a `.rehu`, and neither kind is planned for the other's path.
        """
        return self.plan.tc_path if isinstance(self.plan, TcConversionPlan) else self.plan.rehu_path


class TcConversionPlanTableModel(QAbstractTableModel):
    """One row per `.tc` resource the scan found, its checkbox, and its outcome once import has run.

    **A blocked row starts unchecked, and checking it is the opt-in.** #192 offers no other way to
    override the tie-break or the overwrite refusal, so the checkbox is the only control the plan step
    has, and it does two jobs: which rows import selects, and -- for a row
    :attr:`~rehuco_core.TcConversionPlan.rehu_exists` flagged -- whether the enqueued job is told
    ``overwrite=True``. A :attr:`~rehuco_core.TcConversionPlan.stale_backup` row cannot be unblocked
    this way (the forward converter refuses regardless), so checking one simply enqueues a job that
    fails with a message, which is the honest answer rather than a control that does nothing.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__root = Path()
        self.__rows: list[TcConversionRow] = []
        self.__index_by_path: dict[Path, int] = {}

    # region Building and reading

    def set_plans(
        self, root: Path, plans: Sequence[TcConversionPlan], stranded: Sequence[StrandedManifestPlan] = ()
    ) -> None:
        """Replace every row, as one model reset.

        :param root: the folder the plans were scanned from, for the relative paths shown.
        :param plans: the scan's resources (#191); a :attr:`~rehuco_core.TcConversionPlan.blocked` one
            starts unchecked, every other one starts checked.
        :param stranded: the scan's stranded manifests (#259), after the conversions and each starting
            checked -- nothing blocks a remediation, and it is the state the scan was run to find.
        """
        self.beginResetModel()
        self.__root = root
        self.__rows = [TcConversionRow(plan, checked=not plan.blocked) for plan in plans]
        self.__rows.extend(TcConversionRow(plan, checked=True) for plan in stranded)
        self.__index_by_path = {row.path: index for index, row in enumerate(self.__rows)}
        self.endResetModel()

    def rows(self) -> tuple[TcConversionRow, ...]:
        """Every row, in scan order."""
        return tuple(self.__rows)

    def checked_rows(self) -> tuple[TcConversionRow, ...]:
        """The rows currently selected for import."""
        return tuple(row for row in self.__rows if row.checked)

    def set_row_outcome(self, path: Path, outcome: str, message: str | None = None) -> None:
        """Record what became of the resource at ``path``, and repaint its row.

        A no-op for a path this model has no row for -- the plan was rebuilt (a fresh scan) since the
        job that reports this was enqueued, which the outcome then has nowhere honest to land.

        :param path: the resource the outcome is about, spelled as :attr:`TcConversionRow.path` spells
            it -- the `.tc` for a conversion, the `.rehu` for a remediation.
        :param outcome: one of the values :attr:`TcConversionRow.outcome` documents.
        :param message: why a ``"failed"`` outcome failed, else ``None``.
        """
        row = self.__index_by_path.get(path)
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
        if column == PATH_COLUMN:
            return self.__relative(row.path)
        if column == TARGET_COLUMN:
            return self.__relative(self.__target_of(row.plan))
        if column == SCREENSHOTS_COLUMN:
            return self.__screenshots_text(row.plan) if isinstance(row.plan, TcConversionPlan) else "—"
        if column == FLAGS_COLUMN:
            return self.__flags_text(row.plan)
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
    def __target_of(plan: TcConversionPlan | StrandedManifestPlan) -> Path:
        """What this row's job writes: the `.rehu` a conversion produces, or the `.checksum` a
        remediation merges the stranded claim into.

        :param plan: the row's plan.
        :returns: the path the Target column shows.
        """
        return plan.rehu_path if isinstance(plan, TcConversionPlan) else plan.record_path

    @staticmethod
    def __screenshots_text(plan: TcConversionPlan) -> str:
        """What the screenshot rename plan says, e.g. ``"5 → info00–04, 2 dropped"``.

        :param plan: the resource's plan.
        :returns: the summary text.
        """
        if not plan.renames:
            return "none"
        installed = len(plan.renames)
        # pylint's astroid mis-infers a tuple element of `renames` (a `ScreenshotRename`) as a PySide6
        # signal descriptor in this module -- the two lines below are ordinary attribute reads
        first = Path(plan.renames[0].new_name).stem  # pylint: disable=no-member
        last = Path(plan.renames[-1].new_name).stem  # pylint: disable=no-member
        span = first if installed == 1 else f"{first}–{last[-2:]}"
        recognized = sum(len(rename.recognized_filenames) for rename in plan.renames)
        dropped = recognized - installed
        text = f"{installed} → {span}"
        return f"{text}, {dropped} dropped" if dropped else text

    @staticmethod
    def __flags_text(plan: TcConversionPlan | StrandedManifestPlan) -> str:
        """Every active flag, in the order :data:`FLAG_LABELS` lists them.

        A stranded row carries the one flag that *is* its whole description, and names the manifest with
        it: which file is about to stop being the authority is the only detail worth showing, and it is
        what a reader would otherwise open the folder to find out.

        :param plan: the resource's plan.
        :returns: a comma-separated list, or an em dash when nothing is flagged.
        """
        if isinstance(plan, StrandedManifestPlan):
            return f"{STRANDED_FLAG}: {plan.manifest.name}"
        active = [label for attribute, label in FLAG_LABELS if getattr(plan, attribute)]
        return ", ".join(active) if active else "—"

    @staticmethod
    def __outcome_text(row: TcConversionRow) -> str:
        """What became of ``row``, or an em dash before import has run over it.

        :param row: the row to describe.
        :returns: the outcome text, with a failure's message appended.
        """
        if row.outcome is None:
            return "—"
        if row.outcome == "failed" and row.message:
            return f"failed: {row.message}"
        return row.outcome


class TcConversionPlanFilterProxyModel(QSortFilterProxyModel):
    """Shows only rows whose path or flags contain the filter text, case-insensitive (#192).

    A plain-substring match, the same shape
    :class:`~rehuco_agent.settings.ui.settings_dialog.SettingsDialog.CategoryFilterProxyModel` uses and
    for the same reason: a regex round trip through Qt's own fixed-string filter would need
    un-escaping :meth:`set_filter_text`'s plain text back out of it to match against.

    Sorting is left to the base class's default (by whichever column the view's header was clicked
    on), unlike :class:`~rehuco_agent.fields.widgets.learning_paths_table_model.LearningPathScopeFilterProxyModel`:
    a plan row's identity is the resource, not its position, so re-sorting under a click costs nothing.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__filter_text = ""

    def set_filter_text(self, text: str) -> None:
        """Update the filter text and re-evaluate every row.

        :param text: the text to match the path, target, screenshots, flags and outcome columns
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
        columns = (PATH_COLUMN, TARGET_COLUMN, SCREENSHOTS_COLUMN, FLAGS_COLUMN, OUTCOME_COLUMN)
        return any(
            needle
            in str(model.data(model.index(source_row, column, source_parent), Qt.ItemDataRole.DisplayRole)).lower()
            for column in columns
        )
