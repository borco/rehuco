"""The ``collections`` record list as a two-column model: a series name, and this resource's position in
it ([[field-schema#sources]]).
"""

from collections.abc import Sequence
from typing import Any, override

from PySide6.QtCore import QModelIndex
from rehuco_core import titled_index

from ..indexed_list_field import UNPLACED_INDEX
from .membership_table_model import MembershipTableModel, ModelIndex


class CollectionsTableModel(MembershipTableModel):
    """The document's ``collections`` list as editable rows of *title* and *index*
    ([[field-schema#sources]]).

    The simple client of the shared membership shape: a collection is **publisher-defined and belongs to
    nobody**, so its records sit inline in the block with no owner, no scope and no ``ref`` -- one list,
    every row editable, and the whole model is which records are in it.

    **The ``url`` gets no cell.** It is a cached copy of the series' own page, owned by the collection and
    not authored here ([[field-schema#sources]]) -- the same child-caches-what-the-entity-owns rule the
    membership itself follows. It is carried through untouched instead, which is exactly what the base's
    merge contract is for: retyping a title must not be how a resource loses its series' link.

    **Stored order is kept.** ``index`` is the position and the row's own place says nothing, so the rows
    are shown as stored rather than sorted -- a table that re-sorted itself as the index cell was typed
    into would move the row out from under the cursor mid-edit, and it would rewrite the stored order of
    a document opened merely to fix a spelling.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self.__records: list[dict[str, Any]] = []
        """The rows, in stored order. Every write to it below carries a pylint suppression: the checker
        reads the ``dict`` element as unsubscriptable and reports the *list* operation as the error, the
        same false positive ``AuthorsTableModel`` records."""
        self.__pending: list[bool] = []
        """Per row, alongside :attr:`__records`: whether it was added here and has no title yet -- kept on
        screen, left out of :attr:`entries`, the same rule the authors rows follow."""

    @property
    def entries(self) -> list[dict[str, Any]]:
        """Every membership record, in row order, ready to store ([[field-schema#sources]]) -- leaving out
        the rows added here that have no title yet.

        A **list**, matching what the document holds: a tuple would read as a change to every value
        comparison downstream even where nothing was edited.
        """
        return [record for record, pending in zip(self.__records, self.__pending, strict=True) if not pending]

    def set_entries(self, records: Sequence[dict[str, Any]]) -> None:
        """Replace every row, as one model reset, if the records actually differ.

        The equality check is the echo guard: a caller handing back what it just read must not count as a
        change and rebuild the rows under an open cell editor.

        :param records: the membership records to show, in stored order.
        """
        replacement = [dict(record) for record in records]
        if replacement == self.entries:
            return
        self.beginResetModel()
        self.__records = replacement
        self.__pending = [False] * len(replacement)
        self.endResetModel()

    # region MembershipTableModel contract

    @override
    def record(self, row: int) -> dict[str, Any]:
        return self.__records[row]

    @override
    def replace_record(self, row: int, record: dict[str, Any]) -> None:
        self.__records[row] = record  # pylint: disable=unsupported-assignment-operation
        if titled_index(record) is not None:
            self.__pending[row] = False  # pylint: disable=unsupported-assignment-operation

    # endregion

    # region Qt model interface

    @override
    def rowCount(self, parent: ModelIndex = QModelIndex()) -> int:  # noqa: N802  (Qt API name)
        return 0 if parent.isValid() else len(self.__records)

    @override
    def insertRows(self, row: int, count: int, parent: ModelIndex = QModelIndex()) -> bool:  # noqa: N802
        if parent.isValid() or count < 1 or not 0 <= row <= len(self.__records):
            return False
        self.beginInsertRows(QModelIndex(), row, row + count - 1)
        # a blank title and no position: a membership with no series named is not a membership in anything
        # yet, which is also what keeps the row out of the value until it has a title
        blank: list[dict[str, Any]] = [{"title": "", "index": UNPLACED_INDEX} for _ in range(count)]
        self.__records[row:row] = blank  # pylint: disable=unsupported-assignment-operation
        self.__pending[row:row] = [True] * count  # pylint: disable=unsupported-assignment-operation
        self.endInsertRows()
        return True

    @override
    def removeRows(self, row: int, count: int, parent: ModelIndex = QModelIndex()) -> bool:  # noqa: N802
        if parent.isValid() or count < 1 or not 0 <= row <= len(self.__records) - count:
            return False
        self.beginRemoveRows(QModelIndex(), row, row + count - 1)
        del self.__records[row : row + count]  # pylint: disable=unsupported-delete-operation
        del self.__pending[row : row + count]  # pylint: disable=unsupported-delete-operation
        self.endRemoveRows()
        return True

    # endregion
