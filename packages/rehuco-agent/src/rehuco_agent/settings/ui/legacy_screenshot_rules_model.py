"""The legacy screenshot rules as a two-column model: a series' cover, and a template for the rest
([[acquisition-tooling#screenshot-schemes]], #53).
"""

# The Qt half and the two protocols' row operations are `AuthorsTableModel`'s almost line for line --
# both are a `QAbstractTableModel` over a list of frozen domain objects, driven by `ItemListEditor`.
# Kept as a copy rather than factored into a shared generic base: the halves that would *not* be shared
# are the ones worth reading (what a cell holds, what makes a row blank, what makes it invalid), and a
# base parameterized over all of those would be longer than either subclass and read as neither. If a
# third such model appears, that is the moment to reconsider.
# pylint: disable=duplicate-code

from collections.abc import Sequence
from typing import Any, Final, override

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QPersistentModelIndex, Qt, Signal
from PySide6.QtGui import QBrush, QColor
from rehuco_core import LEGACY_SCREENSHOT_RULES, LegacyScreenshotRule, LegacyScreenshotRuleMatcher

from ...fields.colors import WARNING_COLOR

COVER_COLUMN: Final = 0
"""The series' slot-0 filename -- the cell an insert opens, and the one that decides whether the rule
applies to a directory at all."""

REST_COLUMN: Final = 1
"""The template every file after the cover matches, carrying the ``#`` run that marks their number."""

COLUMN_COUNT: Final = 2

COLUMN_TITLES: Final = ("Cover", "Rest")

MISSING_COVER_REASON: Final = "A rule needs a cover: the file that becomes the first screenshot."

PLACEHOLDER_IN_COVER_REASON: Final = "A cover is one literal filename, so it carries no # placeholder."

MISSING_PLACEHOLDER_REASON: Final = "The rest needs exactly one run of #, marking where the number sits."

type ModelIndex = QModelIndex | QPersistentModelIndex
"""What Qt hands a model method; the persistent form arrives from a view holding onto an index."""


# the count is `QAbstractTableModel`'s surface plus the two protocols `ItemListEditor` drives the model
# through -- four ordering methods, three editing ones -- none of which this class chose; splitting it
# would separate the rows from the operations performed on them
# pylint: disable-next=too-many-public-methods
class LegacyScreenshotRulesModel(QAbstractTableModel):
    """The legacy screenshot rules as editable rows of *cover* and *rest* (#53).

    **Order is meaning, not presentation.** The first rule whose cover is present in a directory claims
    that directory, which is the only thing separating an ``image-00``-first series from an
    ``image-01``-first one -- so the move actions here change what a conversion does, unlike a list
    whose order is merely how it reads.

    **Validation is flagged, never enforced**, the same call
    :class:`~rehuco_agent.fields.widgets.authors_table_model.AuthorsTableModel` makes: a cover that is
    empty or carries a ``#``, or a rest template without exactly one ``#`` run, colors its cell and
    explains itself in a tooltip. Nothing refuses the keystroke -- a rule is half-typed for as long as
    it takes to type it -- and the settings object drops what will not compile on save.

    **The check is core's own**, asked through
    :class:`~rehuco_core.LegacyScreenshotRuleMatcher` rather than restated here: a cell is tested by
    compiling a rule that varies only in the field being judged, so what this page marks invalid is
    exactly what a scan would refuse.

    **Also an `ItemEditor`/`ItemOrderingEditor`** (structurally -- no explicit `Protocol` inheritance,
    since mixing `Protocol`'s metaclass with Shiboken's raises a metaclass conflict), the same shape
    `AuthorsTableModel` implements, so `ItemListEditor` drives this one identically.

    :param defaults: what :meth:`reset` restores; the shipped rules unless a caller says otherwise.
    :param parent: optional Qt parent.
    """

    count_changed = Signal()
    """Fires whenever :attr:`count` changes -- the `ItemOrderingEditor` contract."""

    def __init__(
        self,
        defaults: Sequence[LegacyScreenshotRule] = LEGACY_SCREENSHOT_RULES,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.__entries: list[LegacyScreenshotRule] = []
        self.__defaults: tuple[LegacyScreenshotRule, ...] = tuple(defaults)
        self.rowsInserted.connect(self.count_changed)
        self.rowsRemoved.connect(self.count_changed)
        self.modelReset.connect(self.count_changed)

    @property
    def count(self) -> int:
        """How many rules there are -- the `ItemOrderingEditor` contract."""
        return len(self.__entries)

    @property
    def entries(self) -> tuple[LegacyScreenshotRule, ...]:
        """Every rule, in row order, exactly as typed -- unnormalized, since normalizing is the settings
        object's (:mod:`~rehuco_agent.settings.legacy_screenshots_settings`)."""
        return tuple(self.__entries)

    def set_entries(self, entries: Sequence[LegacyScreenshotRule]) -> None:
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
    def defaults(self) -> tuple[LegacyScreenshotRule, ...]:
        """What :meth:`reset` restores; an empty one means there is nothing to restore."""
        return self.__defaults

    @defaults.setter
    def defaults(self, defaults: Sequence[LegacyScreenshotRule]) -> None:
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

        The same single-``moveRow`` discipline
        :meth:`~rehuco_agent.fields.widgets.authors_table_model.AuthorsTableModel.move_up` uses: every
        other row keeps its index and the selection follows the rule rather than the position.

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

    def row_is_blank(self, row: int) -> bool:
        """Whether ``row`` holds nothing in either cell -- what makes an insert abandonable.

        Both columns, unlike the base's first-column default: a rule half-typed into its rest column is
        a rule somebody is writing, and discarding it because the cover is still empty would delete
        what they had just typed.

        :param row: the row to test.
        :returns: whether both cells are empty.
        """
        if not 0 <= row < len(self.__entries):
            return False
        rule = self.__entries[row]
        return not rule.cover.strip() and not rule.rest.strip()

    def invalid_reason(self, row: int, column: int) -> str:
        """Why the cell at ``row``/``column`` is not something a scan could use, if it isn't.

        :param row: the row to test.
        :param column: :data:`COVER_COLUMN` or :data:`REST_COLUMN`.
        :returns: the explanation, or an empty string when the cell is fine.
        """
        rule = self.__entries[row]
        if column == COVER_COLUMN:
            if not rule.cover.strip():
                return MISSING_COVER_REASON
            # a rest known to compile, so only the cover can be what a refusal is about
            return "" if self.__compiles(LegacyScreenshotRule(rule.cover, "#")) else PLACEHOLDER_IN_COVER_REASON
        # and a cover known to compile, so only the rest can be
        return "" if self.__compiles(LegacyScreenshotRule("cover", rule.rest)) else MISSING_PLACEHOLDER_REASON

    @staticmethod
    def __compiles(rule: LegacyScreenshotRule) -> bool:
        """Whether core would accept ``rule`` -- the scan's own check, not a second spelling of it.

        :param rule: the rule to compile.
        :returns: whether it compiled.
        """
        try:
            LegacyScreenshotRuleMatcher(rule)
        except ValueError:
            return False
        return True

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
        rule = self.__entries[index.row()]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return rule.cover if index.column() == COVER_COLUMN else rule.rest
        reason = self.invalid_reason(index.row(), index.column())
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
        text = str(value).strip()
        rule = self.__entries[row]
        if index.column() == COVER_COLUMN:
            replacement = LegacyScreenshotRule(text, rule.rest)
        else:
            replacement = LegacyScreenshotRule(rule.cover, text)
        if replacement == rule:
            return False
        self.__entries[row] = replacement  # pylint: disable=unsupported-assignment-operation
        # both cells: the two are judged against each other, so a fixed cover can clear the rest's
        # complaint and vice versa
        self.dataChanged.emit(index.sibling(row, COVER_COLUMN), index.sibling(row, REST_COLUMN))
        return True

    @override
    def insertRows(self, row: int, count: int, parent: ModelIndex = QModelIndex()) -> bool:  # noqa: N802
        if parent.isValid() or count < 1 or not 0 <= row <= len(self.__entries):
            return False
        self.beginInsertRows(QModelIndex(), row, row + count - 1)
        self.__entries[row:row] = [  # pylint: disable=unsupported-assignment-operation
            LegacyScreenshotRule("", "") for _ in range(count)
        ]
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
