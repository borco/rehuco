"""The location replacement rules as a three-column model: text to look for, what replaces it, and
whether the text is a regular expression (#350)."""

# The Qt row plumbing and the two protocols' row operations read the same as `AuthorsTableModel`'s,
# because they are the same contract `ItemListEditor` drives every list model through; the rows each
# holds differ, and a shared generic base would have to be typed over both entry shapes for no gain.
# pylint: disable=duplicate-code

from collections.abc import Sequence
from typing import Any, Final, override

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QPersistentModelIndex, Qt, Signal
from PySide6.QtGui import QBrush, QColor

from ...fields.colors import WARNING_COLOR
from ..location_replacements_settings import DEFAULT_RULES, ReplacementRule, rule_problem

TEXT_COLUMN: Final = 0
"""The text a rule looks for -- the cell an insert opens, and the one an empty row is abandoned on."""

REPLACEMENT_COLUMN: Final = 1
"""What the text becomes; empty is a legitimate rule (delete the matched text outright)."""

REGEX_COLUMN: Final = 2
"""A checkbox: whether :data:`TEXT_COLUMN` is a regular expression (`re.sub`) rather than a literal
(`str.replace`)."""

COLUMN_COUNT: Final = 3

COLUMN_TITLES: Final = ("Text", "Replace with", "Regexp")

type ModelIndex = QModelIndex | QPersistentModelIndex
"""What Qt hands a model method; the persistent form arrives from a view holding onto an index."""


# the count is `QAbstractTableModel`'s surface plus the two protocols `ItemListEditor` drives the model
# through -- four ordering methods, four editing ones -- none of which this class chose; splitting it
# would separate the rows from the operations performed on them
# pylint: disable-next=too-many-public-methods
class LocationReplacementsModel(QAbstractTableModel):
    """The global replacement-rule table as editable rows of *text*, *replacement* and a *regexp*
    checkbox (#350).

    **Order matters: rules apply in table order.** ``": "`` -> ``" - "`` then the pipe rule -> ``" - "``
    and the reverse order can render a different name whenever one rule's replacement contains the
    other's text, so reordering the list is a real edit for exactly that reason -- the same call
    `~rehuco_agent.settings.ui.location_template_patterns_model.LocationTemplatePatternsModel` makes.

    **Validation is flagged, never enforced.** A row whose text is empty, or whose regexp checkbox is
    set over text that does not parse as one, colors its text cell and explains itself in a tooltip
    (:func:`~rehuco_agent.settings.location_replacements_settings.rule_problem`); nothing refuses the
    keystroke and saving keeps the row so a typo is fixed in place rather than retyped. Only the text
    column can be invalid -- an empty replacement is a legitimate "delete this" rule, not a mistake, and
    the regexp checkbox is always a valid value (True or False).

    **Also an `ItemEditor`/`ItemOrderingEditor`** (structurally -- no explicit `Protocol` inheritance,
    since mixing `Protocol`'s metaclass with Shiboken's raises a metaclass conflict).

    :param defaults: what :meth:`reset` restores; :data:`DEFAULT_RULES` unless a caller says otherwise.
    :param parent: optional Qt parent.
    """

    count_changed = Signal()
    """Fires whenever :attr:`count` changes -- the `ItemOrderingEditor` contract."""

    def __init__(self, defaults: Sequence[ReplacementRule] = DEFAULT_RULES, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__entries: list[ReplacementRule] = []
        self.__defaults: tuple[ReplacementRule, ...] = tuple(defaults)
        self.rowsInserted.connect(self.count_changed)
        self.rowsRemoved.connect(self.count_changed)
        self.modelReset.connect(self.count_changed)

    @property
    def count(self) -> int:
        """How many rules there are -- the `ItemOrderingEditor` contract."""
        return len(self.__entries)

    @property
    def entries(self) -> tuple[ReplacementRule, ...]:
        """Every rule, in row order, exactly as typed."""
        return tuple(self.__entries)

    def set_entries(self, entries: Sequence[ReplacementRule]) -> None:
        """Replace every row, as one model reset, if the rules actually differ.

        :param entries: the rules to show, in order.
        """
        replacement = list(entries)
        if replacement == self.__entries:
            return
        self.beginResetModel()
        self.__entries = replacement
        self.endResetModel()

    @property
    def defaults(self) -> tuple[ReplacementRule, ...]:
        """What :meth:`reset` restores; an empty one means there is nothing to restore."""
        return self.__defaults

    @defaults.setter
    def defaults(self, defaults: Sequence[ReplacementRule]) -> None:
        """Set what :meth:`reset` restores.

        :param defaults: the rules Reset should put back.
        """
        self.__defaults = tuple(defaults)

    def insert(self, at: int) -> int:
        """Insert a blank rule after ``at``, or at the end -- the `ItemEditor` contract.

        :param at: the row to insert after, or a negative row to append.
        :returns: the new rule's row.
        """
        target = at + 1 if at >= 0 else len(self.__entries)
        self.insertRow(target)
        return target

    def duplicate(self, at: int) -> int:
        """Insert a copy of ``at`` below it -- the `ItemEditor` contract.

        :param at: the row to copy; a negative row is a no-op.
        :returns: the copy's row, or ``at`` when nothing was copied.
        """
        if at < 0:
            return at
        target = at + 1
        self.beginInsertRows(QModelIndex(), target, target)
        self.__entries.insert(target, self.__entries[at])
        self.endInsertRows()
        return target

    def delete(self, at: int) -> None:
        """Drop one rule -- the `ItemEditor` contract.

        :param at: the row to drop; a negative row is a no-op.
        """
        if at >= 0:
            self.removeRow(at)

    def reset(self) -> None:
        """Put :attr:`defaults` back -- the `ItemEditor` contract."""
        self.set_entries(self.__defaults)

    def move_to_top(self, at: int) -> int:
        """Move one rule to the first row -- the `ItemOrderingEditor` contract.

        :param at: the row to move.
        :returns: the row it ended up at.
        """
        return self.__move(at, 0)

    def move_up(self, at: int) -> int:
        """Move one rule up a row -- the `ItemOrderingEditor` contract.

        :param at: the row to move.
        :returns: the row it ended up at.
        """
        return self.__move(at, at - 1)

    def move_down(self, at: int) -> int:
        """Move one rule down a row -- the `ItemOrderingEditor` contract.

        :param at: the row to move.
        :returns: the row it ended up at.
        """
        return self.__move(at, at + 1)

    def move_to_bottom(self, at: int) -> int:
        """Move one rule to the last row -- the `ItemOrderingEditor` contract.

        :param at: the row to move.
        :returns: the row it ended up at.
        """
        return self.__move(at, len(self.__entries) - 1)

    def __move(self, row: int, destination: int) -> int:
        """Move ``row`` to ``destination``, as one model move, and say where it ended up.

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
        """Why the rule at ``row`` is not something :func:`apply_location_replacements
        <rehuco_agent.settings.location_replacements_settings.apply_location_replacements>` would act
        on, if it isn't.

        :param row: the row to test.
        :returns: the explanation, or an empty string when the rule is fine.
        """
        return rule_problem(self.__entries[row])

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
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == REGEX_COLUMN:
            return base | Qt.ItemFlag.ItemIsUserCheckable
        return base | Qt.ItemFlag.ItemIsEditable

    @override
    # four columns worth of role handling (three real, one derived from the read side) -- collapsing
    # them behind one exit would need a sentinel meaning both "no answer" and "the answer is None"
    def data(self, index: ModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:  # pylint: disable=too-many-return-statements
        if not index.isValid():
            return None
        entry = self.__entries[index.row()]
        column = index.column()
        if column == REGEX_COLUMN:
            if role == Qt.ItemDataRole.CheckStateRole:
                return Qt.CheckState.Checked if entry.is_regex else Qt.CheckState.Unchecked
            # EditRole too, which is what the settings dialog's frame snapshot reads and writes back:
            # without it a toggled box never lights the frame's Apply, and its Reset/Defaults drop it
            if role == Qt.ItemDataRole.EditRole:
                return entry.is_regex
            return None
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return entry.text if column == TEXT_COLUMN else entry.replacement
        if column != TEXT_COLUMN:
            return None
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
        if not index.isValid():
            return False
        row = index.row()
        entry = self.__entries[row]
        column = index.column()
        if column == REGEX_COLUMN:
            if role == Qt.ItemDataRole.CheckStateRole:
                replacement = entry._replace(is_regex=Qt.CheckState(value) == Qt.CheckState.Checked)
            elif role == Qt.ItemDataRole.EditRole:
                replacement = entry._replace(is_regex=bool(value))
            else:
                return False
        elif role != Qt.ItemDataRole.EditRole:
            return False
        elif column == TEXT_COLUMN:
            replacement = entry._replace(text=str(value))
        else:
            replacement = entry._replace(replacement=str(value))
        if replacement == entry:
            return False
        self.__entries[row] = replacement  # pylint: disable=unsupported-assignment-operation
        self.dataChanged.emit(index, index)
        return True

    @override
    def insertRows(self, row: int, count: int, parent: ModelIndex = QModelIndex()) -> bool:  # noqa: N802
        if parent.isValid() or count < 1 or not 0 <= row <= len(self.__entries):
            return False
        self.beginInsertRows(QModelIndex(), row, row + count - 1)
        self.__entries[row:row] = [ReplacementRule("", "", False)] * count  # pylint: disable=unsupported-assignment-operation
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
        if not self.beginMoveRows(QModelIndex(), sourceRow, sourceRow + count - 1, QModelIndex(), destinationChild):
            return False
        block = self.__entries[sourceRow : sourceRow + count]
        del self.__entries[sourceRow : sourceRow + count]  # pylint: disable=unsupported-delete-operation
        at = destinationChild if destinationChild < sourceRow else destinationChild - count
        self.__entries[at:at] = block  # pylint: disable=unsupported-assignment-operation
        self.endMoveRows()
        return True

    # endregion
