"""The location name patterns as a one-column model: a plain format-string pattern per row (#322)."""

# The Qt half and the two protocols' row operations are `ScreenshotNamePatternsModel`'s almost line for
# line -- see that module's own note on why this is a copy rather than a shared generic base.
# pylint: disable=duplicate-code

from collections.abc import Sequence
from typing import Any, Final, override

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QPersistentModelIndex, Qt, Signal
from PySide6.QtGui import QBrush, QColor

from ...fields.colors import WARNING_COLOR
from ..location_templates_settings import NAME_SUGGESTION_PATTERNS, location_pattern_is_valid

PATTERN_COLUMN: Final = 0
"""The row's only column: the raw pattern."""

COLUMN_COUNT: Final = 1

COLUMN_TITLES: Final = ("Pattern",)

MISSING_PATTERN_REASON: Final = "A pattern is a format string interpolating {title} / {publisher} / {authors} / {year}."

INVALID_PATTERN_REASON: Final = (
    "This does not parse as a format string, or names a placeholder other than "
    "{title} / {publisher} / {authors} / {year}."
)

type ModelIndex = QModelIndex | QPersistentModelIndex
"""What Qt hands a model method; the persistent form arrives from a view holding onto an index."""


# the count is `QAbstractTableModel`'s surface plus the two protocols `ItemListEditor` drives the model
# through -- four ordering methods, three editing ones -- none of which this class chose; splitting it
# would separate the rows from the operations performed on them
# pylint: disable-next=too-many-public-methods
class LocationTemplatePatternsModel(QAbstractTableModel):
    """One resource type's rename-suggestion patterns as editable rows of one plain format string each
    (#322).

    **Order matters: it is the order suggestions are offered in** -- an ordinary list, so reordering the
    list is a real edit for exactly that reason.

    **Validation is flagged, never enforced**, the same call
    :class:`~rehuco_agent.settings.ui.screenshot_name_patterns_model.ScreenshotNamePatternsModel` makes: a
    pattern that is blank, fails to parse, or names an unknown placeholder colors its cell and explains
    itself in a tooltip. Nothing refuses the keystroke -- a pattern is half-typed for as long as it takes
    to type it -- and the settings object drops what will not resolve on save.

    **The check is the settings module's own**, asked through
    :func:`~rehuco_agent.settings.location_templates_settings.location_pattern_is_valid` rather than
    restated here, which is what keeps what this page marks invalid exactly what a suggestion would
    refuse.

    **Also an `ItemEditor`/`ItemOrderingEditor`** (structurally -- no explicit `Protocol` inheritance,
    since mixing `Protocol`'s metaclass with Shiboken's raises a metaclass conflict), the same shape
    `ScreenshotNamePatternsModel` implements, so `ItemListEditor` drives this one identically.

    :param defaults: what :meth:`reset` restores; the shipped patterns unless a caller says otherwise.
    :param parent: optional Qt parent.
    """

    count_changed = Signal()
    """Fires whenever :attr:`count` changes -- the `ItemOrderingEditor` contract."""

    def __init__(
        self,
        defaults: Sequence[str] = NAME_SUGGESTION_PATTERNS,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.__entries: list[str] = []
        self.__defaults: tuple[str, ...] = tuple(defaults)
        self.rowsInserted.connect(self.count_changed)
        self.rowsRemoved.connect(self.count_changed)
        self.modelReset.connect(self.count_changed)

    @property
    def count(self) -> int:
        """How many patterns there are -- the `ItemOrderingEditor` contract."""
        return len(self.__entries)

    @property
    def entries(self) -> tuple[str, ...]:
        """Every pattern, in row order, exactly as typed -- unnormalized, since normalizing is the
        settings object's (:mod:`~rehuco_agent.settings.location_templates_settings`)."""
        return tuple(self.__entries)

    def set_entries(self, entries: Sequence[str]) -> None:
        """Replace every row, as one model reset, if the patterns actually differ.

        :param entries: the patterns to show, in order.
        """
        replacement = list(entries)
        if replacement == self.__entries:
            return
        self.beginResetModel()
        self.__entries = replacement
        self.endResetModel()

    @property
    def defaults(self) -> tuple[str, ...]:
        """What :meth:`reset` restores; an empty one means there is nothing to restore."""
        return self.__defaults

    @defaults.setter
    def defaults(self, defaults: Sequence[str]) -> None:
        """Set what :meth:`reset` restores.

        :param defaults: the patterns Reset should put back.
        """
        self.__defaults = tuple(defaults)

    def insert(self, at: int) -> int:
        """Insert a blank pattern after ``at``, or at the end -- the `ItemEditor` contract.

        :param at: the row to insert after, or a negative row to append.
        :returns: the new pattern's row.
        """
        target = at + 1 if at >= 0 else len(self.__entries)
        self.insertRow(target)
        return target

    def delete(self, at: int) -> None:
        """Drop one pattern -- the `ItemEditor` contract.

        :param at: the row to drop; a negative row is a no-op.
        """
        if at >= 0:
            self.removeRow(at)

    def reset(self) -> None:
        """Put :attr:`defaults` back -- the `ItemEditor` contract."""
        self.set_entries(self.__defaults)

    def move_to_top(self, at: int) -> int:
        """Move one pattern to the first row -- the `ItemOrderingEditor` contract.

        :param at: the row to move.
        :returns: the row it ended up at.
        """
        return self.__move(at, 0)

    def move_up(self, at: int) -> int:
        """Move one pattern up a row -- the `ItemOrderingEditor` contract.

        :param at: the row to move.
        :returns: the row it ended up at.
        """
        return self.__move(at, at - 1)

    def move_down(self, at: int) -> int:
        """Move one pattern down a row -- the `ItemOrderingEditor` contract.

        :param at: the row to move.
        :returns: the row it ended up at.
        """
        return self.__move(at, at + 1)

    def move_to_bottom(self, at: int) -> int:
        """Move one pattern to the last row -- the `ItemOrderingEditor` contract.

        :param at: the row to move.
        :returns: the row it ended up at.
        """
        return self.__move(at, len(self.__entries) - 1)

    def __move(self, row: int, destination: int) -> int:
        """Move ``row`` to ``destination``, as one model move, and say where it ended up.

        The same single-``moveRow`` discipline
        :meth:`~rehuco_agent.settings.ui.screenshot_name_patterns_model.ScreenshotNamePatternsModel.__move`
        uses: every other row keeps its index and the selection follows the pattern rather than the
        position.

        :param row: the row to move.
        :param destination: where to move it to; out-of-range or unchanged is a no-op.
        :returns: ``destination`` if the move happened, ``row`` (unchanged) otherwise.
        """
        if row < 0 or destination == row or not 0 <= destination < len(self.__entries):
            return row
        # Qt reads the destination in the *pre-move* row space -- the row the entry is inserted
        # *before* -- so a downward move has to name one past the target, because removing the source
        # first shifts everything below it up by one.
        before = destination + 1 if destination > row else destination
        self.moveRow(QModelIndex(), row, QModelIndex(), before)
        return destination

    def invalid_reason(self, row: int) -> str:
        """Why the pattern at ``row`` is not something a suggestion could use, if it isn't.

        :param row: the row to test.
        :returns: the explanation, or an empty string when the pattern is fine.
        """
        pattern = self.__entries[row]
        if not pattern.strip():
            return MISSING_PATTERN_REASON
        return "" if location_pattern_is_valid(pattern) else INVALID_PATTERN_REASON

    # region Qt model interface

    @override
    def rowCount(self, parent: ModelIndex = QModelIndex()) -> int:  # noqa: N802  (Qt API name)
        return 0 if parent.isValid() else len(self.__entries)

    @override
    def columnCount(self, parent: ModelIndex = QModelIndex()) -> int:  # noqa: N802  (Qt API name)
        return 0 if parent.isValid() else COLUMN_COUNT

    @override
    def headerData(  # noqa: N802  (Qt API name)
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if role != Qt.ItemDataRole.DisplayRole or orientation != Qt.Orientation.Horizontal:
            return None
        return COLUMN_TITLES[section]

    @override
    def flags(self, index: ModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable

    @override
    def data(self, index: ModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        entry = self.__entries[index.row()]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return entry
        reason = self.invalid_reason(index.row())
        if role == Qt.ItemDataRole.ToolTipRole:
            return reason or None
        if role == Qt.ItemDataRole.ForegroundRole and reason:
            return QBrush(QColor(WARNING_COLOR))
        return None

    @override
    def setData(  # noqa: N802  (Qt API name)
        self,
        index: ModelIndex,
        value: Any,
        role: int = Qt.ItemDataRole.EditRole,
    ) -> bool:
        if not index.isValid() or role != Qt.ItemDataRole.EditRole:
            return False
        row = index.row()
        replacement = str(value).strip()
        if replacement == self.__entries[row]:
            return False
        self.__entries[row] = replacement  # pylint: disable=unsupported-assignment-operation
        self.dataChanged.emit(index, index)
        return True

    @override
    def insertRows(self, row: int, count: int, parent: ModelIndex = QModelIndex()) -> bool:  # noqa: N802
        if parent.isValid() or count < 1 or not 0 <= row <= len(self.__entries):
            return False
        self.beginInsertRows(QModelIndex(), row, row + count - 1)
        self.__entries[row:row] = ["" for _ in range(count)]  # pylint: disable=unsupported-assignment-operation
        self.endInsertRows()
        return True

    @override
    def removeRows(self, row: int, count: int, parent: ModelIndex = QModelIndex()) -> bool:  # noqa: N802
        if parent.isValid() or count < 1 or not 0 <= row <= len(self.__entries) - count:
            return False
        self.beginRemoveRows(QModelIndex(), row, row + count - 1)
        del self.__entries[row : row + count]  # pylint: disable=unsupported-delete-operation
        self.endRemoveRows()
        return True

    @override
    def moveRows(  # noqa: N802  (Qt API name)
        self,
        sourceParent: ModelIndex,  # noqa: N803  (Qt API name)
        sourceRow: int,  # noqa: N803  (Qt API name)
        count: int,
        destinationParent: ModelIndex,  # noqa: N803  (Qt API name)
        destinationChild: int,  # noqa: N803  (Qt API name)
    ) -> bool:
        if sourceParent.isValid() or destinationParent.isValid():
            return False
        # beginMoveRows is the validity check as well as the announcement: it refuses a destination
        # inside the block being moved, and a move that would leave the list as it was
        if not self.beginMoveRows(QModelIndex(), sourceRow, sourceRow + count - 1, QModelIndex(), destinationChild):
            return False
        block = self.__entries[sourceRow : sourceRow + count]
        del self.__entries[sourceRow : sourceRow + count]  # pylint: disable=unsupported-delete-operation
        # the destination was read in the pre-move row space, so taking the block out first shifts it
        at = destinationChild if destinationChild < sourceRow else destinationChild - count
        self.__entries[at:at] = block  # pylint: disable=unsupported-assignment-operation
        self.endMoveRows()
        return True

    # endregion
