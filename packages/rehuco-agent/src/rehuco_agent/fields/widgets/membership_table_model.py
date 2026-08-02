"""What the two membership tables share: a **Title** cell, an **Index** cell, and the merge contract
both write back under ([[field-schema#field-types]], #235).

A *shape* base, matching the shape rule core states for reading these records
(:func:`~rehuco_core.titled_index`): ``collections`` and ``learning_paths`` are unrelated things -- a
publisher's series belongs to nobody, a learning path is somebody's -- so each keeps its own model, its own
extra columns, and its own idea of what a row even is. What they genuinely have in common is these two
cells and the rule that editing one must not rebuild the record around it.
"""

from typing import Any, Final, override

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QPersistentModelIndex, Qt, Signal
from PySide6.QtGui import QBrush, QColor
from rehuco_core import titled_index, with_titled_index

from ..colors import WARNING_COLOR
from ..indexed_list_field import UNPLACED_INDEX

TITLE_COLUMN: Final = 0
"""What the membership is called -- the cell an insert opens, and the one a row cannot be without."""

INDEX_COLUMN: Final = 1
"""Where this resource sits in it; :data:`~rehuco_agent.fields.indexed_list_field.UNPLACED_INDEX` shows
as no position at all ([[field-schema#sources]])."""

MISSING_TITLE_REASON: Final = "A membership needs a name."
"""Shown on a row whose title has been emptied. A record with no usable title renders as nothing at all
([[field-schema#field-types]]), so the editor says so where it was typed rather than letting the row
vanish from the viewer with no explanation."""

MAXIMUM_INDEX: Final = 9999
"""The highest position the spin cell offers. Not a rule the format has -- nothing on disk is refused for
exceeding it -- only a bound a spin box must be given; a series with five figures of members is not a
thing this editor is shaped for, and an unbounded spinner would size its cell for a number nobody types."""

type ModelIndex = QModelIndex | QPersistentModelIndex
"""What Qt hands a model method; the persistent form arrives from a view holding onto an index."""


class MembershipTableModel(QAbstractTableModel):
    """The Title/Index half of a memberships table, and the contract its subclasses fill in (#235).

    **Merge, don't rebuild.** Every cell edit here goes through
    :func:`~rehuco_core.with_titled_index`, which copies the record a row was built from and changes only
    the key the cell owns -- so a collection's cached ``url`` and a learning path's ``ref`` survive
    retyping the title beside them. A model that reconstructed the record from its visible columns would
    sever both, invisibly, on an entry nobody meant to touch.

    **Order is not the data.** ``index`` is: a row says where this resource sits in the thing it names,
    and the row's own position says nothing at all. So the four `ItemOrderingEditor` moves are honest
    no-ops rather than absent -- the protocol is what the shared
    :class:`~borco_pyside.widgets.ItemListEditor` machinery asks of a model, and an editor built on it
    simply hides the column (``with_ordering=False``) instead of offering four buttons that would change
    nothing a reader could see.

    **Validation is flagged, never enforced**, the same way the ``authors`` rows do it
    (:class:`~rehuco_agent.fields.widgets.authors_table_model.AuthorsTableModel`): an emptied title colors
    its cell and explains itself in a tooltip, and nothing refuses the keystroke.

    A subclass supplies what a *row* is -- :meth:`record`, :meth:`replace_record`, ``rowCount``, and the
    insert/remove primitives -- plus whatever columns it has of its own.

    :param parent: optional Qt parent.
    """

    COLUMN_TITLES: tuple[str, ...] = ("Title", "Index")
    """This table's headers, in column order; a subclass appends its own and keeps these two leading."""

    count_changed = Signal()
    """Fires whenever :attr:`count` changes -- the `ItemOrderingEditor` contract."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.rowsInserted.connect(self.count_changed)
        self.rowsRemoved.connect(self.count_changed)
        self.modelReset.connect(self.count_changed)

    # region subclass contract

    def record(self, row: int) -> dict[str, Any]:
        """The stored record ``row`` was built from.

        :param row: the row to read.
        :returns: the record, as stored -- never mutated by anything here.
        :raises NotImplementedError: unless a subclass overrides it.
        """
        raise NotImplementedError

    def replace_record(self, row: int, record: dict[str, Any]) -> None:
        """Put ``record`` where ``row``'s current one sits, keeping its position among the stored records.

        The one write every cell edit funnels through, so a subclass says *where* its records live exactly
        once however many columns it ends up with.

        :param row: the row to rewrite.
        :param record: the merged replacement.
        :raises NotImplementedError: unless a subclass overrides it.
        """
        raise NotImplementedError

    def row_is_editable(self, row: int) -> bool:
        """Whether this identity may rewrite ``row``'s title and position.

        ``True`` for everything by default -- a collection belongs to nobody, so there is no one whose
        permission it needs. Overridden where ownership is structural
        ([[field-schema#learning-path-ownership]]).

        :param row: the row to test.
        :returns: whether its shared cells accept an edit.
        """
        del row
        return True

    # endregion

    # region ItemEditor / ItemOrderingEditor

    @property
    def count(self) -> int:
        """How many rows there are -- the `ItemOrderingEditor` contract."""
        return self.rowCount()

    def insert(self, at: int) -> int:
        """Insert a blank membership after ``at``, or at the end -- the `ItemEditor` contract.

        :param at: the row to insert after, or a negative row to append.
        :returns: the new row's number.
        """
        target = at + 1 if at >= 0 else self.rowCount()
        self.insertRow(target)
        return target

    def delete(self, at: int) -> None:
        """Drop one membership -- the `ItemEditor` contract.

        :param at: the row to drop; a negative row is a no-op.
        """
        if at >= 0:
            self.removeRow(at)

    def reset(self) -> None:
        """No-op -- there is no such thing as a default set of memberships (the `ItemEditor` contract)."""

    def move_to_top(self, at: int) -> int:
        """No-op -- ``index`` is the position here, not the row (the `ItemOrderingEditor` contract).

        :param at: the row asked about.
        :returns: ``at``, unmoved.
        """
        return at

    def move_up(self, at: int) -> int:
        """No-op -- see :meth:`move_to_top`.

        :param at: the row asked about.
        :returns: ``at``, unmoved.
        """
        return at

    def move_down(self, at: int) -> int:
        """No-op -- see :meth:`move_to_top`.

        :param at: the row asked about.
        :returns: ``at``, unmoved.
        """
        return at

    def move_to_bottom(self, at: int) -> int:
        """No-op -- see :meth:`move_to_top`.

        :param at: the row asked about.
        :returns: ``at``, unmoved.
        """
        return at

    # endregion

    def invalid_reason(self, row: int, column: int) -> str:
        """Why the cell at ``row``/``column`` is not something this editor would write, if it isn't.

        :param row: the row to test.
        :param column: the column to test.
        :returns: the explanation, or an empty string when the cell is fine.
        """
        if column != TITLE_COLUMN:
            return ""
        return "" if titled_index(self.record(row)) is not None else MISSING_TITLE_REASON

    def title(self, row: int) -> str:
        """``row``'s title as the cell shows it.

        :param row: the row to read.
        :returns: the stored title, or an empty string where the record carries none this reader can use.
        """
        title = self.record(row).get("title")
        return title if isinstance(title, str) else ""

    def index_of(self, row: int) -> int:
        """``row``'s position in the thing it names.

        :param row: the row to read.
        :returns: the stored position, coerced the way core reads it -- absent or malformed is
            :data:`~rehuco_agent.fields.indexed_list_field.UNPLACED_INDEX`.
        """
        found = titled_index(self.record(row))
        if found is not None:
            return found[0]
        # a record with no usable title has no ``(index, title)`` pair to read, and its position is still
        # a cell the user can type in -- so it is coerced here the one way core would have
        stored = self.record(row).get("index")
        return stored if isinstance(stored, int) and not isinstance(stored, bool) else UNPLACED_INDEX

    # region Qt model interface

    # The flagged-cell roles and the setData preamble read the same here as in ``AuthorsTableModel``,
    # which is the point: both are record-list editors flagging what they would not write, and the two
    # agreeing by coincidence is better than a shared base whose only member would be this boilerplate.
    # pylint: disable=duplicate-code

    @override
    def columnCount(self, parent: ModelIndex = QModelIndex()) -> int:  # noqa: N802  (Qt API name)
        return 0 if parent.isValid() else len(self.COLUMN_TITLES)

    @override
    def headerData(  # noqa: N802  (Qt API name)
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if role != Qt.ItemDataRole.DisplayRole or orientation != Qt.Orientation.Horizontal:
            return None
        return self.COLUMN_TITLES[section]

    @override
    def flags(self, index: ModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        shared = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() in (TITLE_COLUMN, INDEX_COLUMN) and self.row_is_editable(index.row()):
            return shared | Qt.ItemFlag.ItemIsEditable
        return shared

    @override
    def data(self, index: ModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or index.column() not in (TITLE_COLUMN, INDEX_COLUMN):
            return None
        row, column = index.row(), index.column()
        if role == Qt.ItemDataRole.EditRole:
            return self.title(row) if column == TITLE_COLUMN else self.index_of(row)
        if role == Qt.ItemDataRole.DisplayRole:
            return self.title(row) if column == TITLE_COLUMN else self.displayed_index(row)
        reason = self.invalid_reason(row, column)
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
        row, column = index.row(), index.column()
        if column not in (TITLE_COLUMN, INDEX_COLUMN) or not self.row_is_editable(row):
            return False
        record = self.record(row)
        if column == TITLE_COLUMN:
            merged = with_titled_index(record, title=str(value).strip())
        else:
            merged = with_titled_index(record, index=int(value))
        if merged == record:
            return False
        self.replace_record(row, merged)
        self.dataChanged.emit(index, index)
        return True

    # pylint: enable=duplicate-code

    # endregion

    def displayed_index(self, row: int) -> str:
        """``row``'s position as the cell **shows** it.

        :data:`~rehuco_agent.fields.indexed_list_field.UNPLACED_INDEX` shows as nothing, the same rule the
        viewer renders under ([[field-schema#sources]]): printing ``0`` there would show a placement
        nobody made.

        :param row: the row to read.
        :returns: the number as text, or an empty string for an unplaced membership.
        """
        index = self.index_of(row)
        return "" if index == UNPLACED_INDEX else str(index)
