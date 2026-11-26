"""The License dock's list of a record's licenses, as a table: one row per license, its id and the address of its
terms ([[assets#licenses]], #705)."""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any, Final, override

from PySide6.QtCore import QAbstractTableModel, QMimeData, QModelIndex, QObject, QPersistentModelIndex, Qt, Signal
from rehuco_core import AssetLicense

from ..scraping.sites.fab import LICENSES
from .rehu_document_model import RehuDocumentModel

LICENSE_COLUMN: Final = 0
"""The column of a license's short id -- the one an insert opens, and the one a license cannot be without."""

URL_COLUMN: Final = 1
"""The column of where the store states its terms."""

HEADERS: Final = ("License", "URL")
"""Each column's header, in column order."""

PRESET_URLS: Final = dict(LICENSES.values())
"""Each preset license's id to the address of its terms, empty for one with none (``fab-ue-only``): the licenses a
scan writes, which the id cell offers."""

LICENSE_MIME_TYPE: Final = "application/x-rehuco-license-row"
"""What a license dragged by its grip carries: its row."""

type ModelIndex = QModelIndex | QPersistentModelIndex
"""What Qt hands a model method; the persistent form arrives from a view holding onto an index."""


@dataclass(frozen=True)
class LicenseRow:
    """One row of the list: a license, or one being added that has no id yet.

    :param license: the license's short id; empty while the row is being added.
    :param url: where the store states its terms; empty for none.
    """

    license: str
    url: str = ""


# the count is `QAbstractTableModel`'s surface plus the two protocols `ItemListEditor` drives the model through, none
# of which this class chose, as `AuthorsTableModel`'s is
# pylint: disable-next=too-many-public-methods
class LicensesTableModel(QAbstractTableModel):
    """A record's licenses, in their order, edited in place while the License dock edits (#705).

    **Every edit is the document's**: a row moved, a URL typed or a row deleted sets the document's licenses, an id
    picked or typed replaces the license in its place
    (:meth:`~rehuco_agent.documents.rehu_document_model.RehuDocumentModel.replace_license`), and a deleted row takes
    its text along (:meth:`~rehuco_agent.documents.rehu_document_model.RehuDocumentModel.remove_license`). So Revert
    drops them, and the document's own licenses coming back (:meth:`set_entries`) changes nothing it already shows.

    **A preset is its URL and its text**: picking one (:data:`PRESET_URLS`) sets the row's URL and drops the text the
    row had, and :attr:`preset_chosen` asks for the preset's own text, which arrives later. **A custom id** keeps what
    the row's user typed -- its URL and text, under the new id -- and nothing a preset put there.

    **A row added here has no id until one is picked or typed**, and is left out of the licenses until then, as an
    author with no name is: its URL can be typed first. Such rows stay while the dock edits, however the focus moves,
    and go when it stops (:meth:`drop_unnamed`). An id is never emptied or given twice -- licenses are unique by id --
    so such an edit is refused and the cell keeps what it had.

    **Also an `ItemEditor`/`ItemOrderingEditor`** (structurally, as `AuthorsTableModel` is), for `ItemListEditor`'s
    buttons and keys; while the dock only reads (:meth:`set_editable`) every one of them does nothing. There is no
    duplicate -- a copy would hold the same id -- and no reset.

    :param document: the document whose licenses these are.
    :param parent: optional Qt parent.
    """

    count_changed = Signal()
    """Fires whenever :attr:`count` changes -- the `ItemOrderingEditor` contract."""

    preset_chosen = Signal(str, str)
    """A preset with terms was picked: its id and the address of its terms, whose text is to be read."""

    def __init__(self, document: RehuDocumentModel, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__document: Final = document
        self.__rows: list[LicenseRow] = []
        """The rows, in order. Its writes carry a pylint suppression: the checker infers the list as a ``LicenseRow``
        and reports each list write as an error, as it does ``AuthorsTableModel``'s."""
        self.__editable = False
        self.rowsInserted.connect(self.count_changed)
        self.rowsRemoved.connect(self.count_changed)
        self.modelReset.connect(self.count_changed)

    @property
    def editable(self) -> bool:
        """Whether the rows can be edited, added, deleted and dragged."""
        return self.__editable

    def set_editable(self, editable: bool) -> None:
        """Let the rows be edited, or only read; the grip a row is dragged by shows only while they can be.

        :param editable: whether they can.
        """
        if editable == self.__editable:
            return
        # a layout change: the first column is measured again, with its grip or without
        self.layoutAboutToBeChanged.emit()
        self.__editable = editable
        self.layoutChanged.emit()

    @property
    def entries(self) -> list[AssetLicense]:
        """The licenses, in row order, leaving out the rows that have no id yet."""
        return [AssetLicense(row.license, row.url or None) for row in self.__rows if row.license]

    def set_entries(self, entries: Sequence[AssetLicense]) -> None:
        """Show ``entries``, resetting the rows only when they differ from what is shown -- so a row being added is
        kept while the document's licenses come back as this model wrote them.

        :param entries: the licenses, in order.
        """
        if list(entries) == self.entries:
            return
        self.beginResetModel()
        self.__rows = [LicenseRow(entry.license, entry.url or "") for entry in entries]
        self.endResetModel()

    def license_at(self, row: int) -> str | None:
        """The id of the license a row shows.

        :param row: the row.
        :returns: its id; ``None`` for a row there is not, or one that has no id yet.
        """
        return self.__rows[row].license or None if 0 <= row < len(self.__rows) else None

    def row_of(self, license_id: str) -> int:
        """Where a license is.

        :param license_id: its short id.
        :returns: its row; ``-1`` when the record holds no such license.
        """
        return next((at for at, row in enumerate(self.__rows) if row.license == license_id), -1)

    def taken(self, row: int) -> set[str]:
        """The ids the other rows hold: none of them can be given to ``row``.

        :param row: the row being given an id.
        :returns: the ids.
        """
        return {held.license for at, held in enumerate(self.__rows) if at != row and held.license}

    def drop_unnamed(self) -> None:
        """Take out the rows that never got an id: the dock stopped editing, or the record was saved."""
        for at in reversed(range(len(self.__rows))):
            if not self.__rows[at].license:
                self.removeRow(at)

    # region ItemEditor and ItemOrderingEditor

    @property
    def count(self) -> int:
        """How many rows there are -- the `ItemOrderingEditor` contract."""
        return len(self.__rows)

    def insert(self, at: int) -> int:
        """Add a row with no id after ``at``, or at the end -- the `ItemEditor` contract.

        :param at: the row to insert after, or a negative row to append.
        :returns: the new row; ``at`` while the rows cannot be edited.
        """
        if not self.__editable:
            return at
        target = at + 1 if at >= 0 else len(self.__rows)
        self.insertRow(target)
        return target

    def duplicate(self, at: int) -> int:
        """Nothing: a copy of a license would hold its id, which no other row may -- the `ItemEditor` contract.

        :param at: the row.
        :returns: ``at``.
        """
        return at

    def delete(self, at: int) -> None:
        """Take a license off the record, its text with it -- the `ItemEditor` contract.

        :param at: the row; a negative row, or any while the rows cannot be edited, is a no-op.
        """
        if not self.__editable or not 0 <= at < len(self.__rows):
            return
        license_id = self.__rows[at].license
        self.removeRow(at)
        if license_id:
            self.__document.remove_license(license_id)

    def reset(self) -> None:
        """Nothing: licenses have no defaults -- the `ItemEditor` contract."""

    def move_to_top(self, at: int) -> int:
        """Move a row to the top -- the `ItemOrderingEditor` contract.

        :param at: the row.
        :returns: where it ended up.
        """
        return self.move(at, 0)

    def move_up(self, at: int) -> int:
        """Move a row up one -- the `ItemOrderingEditor` contract.

        :param at: the row.
        :returns: where it ended up.
        """
        return self.move(at, at - 1)

    def move_down(self, at: int) -> int:
        """Move a row down one -- the `ItemOrderingEditor` contract.

        :param at: the row.
        :returns: where it ended up.
        """
        return self.move(at, at + 1)

    def move_to_bottom(self, at: int) -> int:
        """Move a row to the bottom -- the `ItemOrderingEditor` contract.

        :param at: the row.
        :returns: where it ended up.
        """
        return self.move(at, len(self.__rows) - 1)

    def move(self, row: int, destination: int) -> int:
        """Move ``row`` to ``destination`` as one model move, and give the document the new order -- what a drop of
        a row dragged by its grip does.

        :param row: the row to move.
        :param destination: the row it is to end up at; out of range, unchanged, or any while the rows cannot be
            edited, is a no-op.
        :returns: ``destination`` if the move happened, ``row`` otherwise.
        """
        if not self.__editable or row < 0 or destination == row or not 0 <= destination < len(self.__rows):
            return row
        # Qt reads the destination before the move: a row moved down is inserted before the one past its target
        before = destination + 1 if destination > row else destination
        self.moveRow(QModelIndex(), row, QModelIndex(), before)
        self.__write()
        return destination

    # endregion

    # region Qt model interface

    @override
    def rowCount(self, parent: ModelIndex = QModelIndex()) -> int:  # noqa: N802  (Qt API)
        return 0 if parent.isValid() else len(self.__rows)

    @override
    def columnCount(self, parent: ModelIndex = QModelIndex()) -> int:  # noqa: N802  (Qt API)
        return 0 if parent.isValid() else len(HEADERS)

    @override
    def flags(self, index: ModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if not self.__editable:
            return flags
        return flags | Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsEditable

    @override
    def data(self, index: ModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or role not in (
            Qt.ItemDataRole.DisplayRole,
            Qt.ItemDataRole.EditRole,
            Qt.ItemDataRole.ToolTipRole,
        ):
            return None
        row = self.__rows[index.row()]
        return row.license if index.column() == LICENSE_COLUMN else row.url

    @override
    def setData(  # noqa: N802  (Qt API)
        self, index: ModelIndex, value: Any, role: int = Qt.ItemDataRole.EditRole
    ) -> bool:
        if not index.isValid() or role != Qt.ItemDataRole.EditRole or not self.__editable:
            return False
        text = str(value).strip()
        if index.column() == URL_COLUMN:
            return self.__set_url(index.row(), text)
        return self.__set_license(index.row(), text)

    @override
    def headerData(  # noqa: N802  (Qt API)
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        if (
            orientation is Qt.Orientation.Horizontal
            and role == Qt.ItemDataRole.DisplayRole
            and 0 <= section < len(HEADERS)
        ):
            return HEADERS[section]
        return super().headerData(section, orientation, role)

    @override
    def insertRows(self, row: int, count: int, parent: ModelIndex = QModelIndex()) -> bool:  # noqa: N802  (Qt API)
        if parent.isValid() or count < 1 or not 0 <= row <= len(self.__rows):
            return False
        self.beginInsertRows(QModelIndex(), row, row + count - 1)
        self.__rows[row:row] = [LicenseRow("")] * count  # pylint: disable=unsupported-assignment-operation
        self.endInsertRows()
        return True

    @override
    def removeRows(self, row: int, count: int, parent: ModelIndex = QModelIndex()) -> bool:  # noqa: N802  (Qt API)
        if parent.isValid() or count < 1 or not 0 <= row <= len(self.__rows) - count:
            return False
        self.beginRemoveRows(QModelIndex(), row, row + count - 1)
        del self.__rows[row : row + count]  # pylint: disable=unsupported-delete-operation
        self.endRemoveRows()
        return True

    @override
    def moveRows(  # noqa: N802  (Qt API)
        self,
        sourceParent: ModelIndex,  # noqa: N803  (Qt API)
        sourceRow: int,  # noqa: N803  (Qt API)
        count: int,
        destinationParent: ModelIndex,  # noqa: N803  (Qt API)
        destinationChild: int,  # noqa: N803  (Qt API)
    ) -> bool:
        if sourceParent.isValid() or destinationParent.isValid():
            return False
        # beginMoveRows refuses a destination inside the block, and a move that changes nothing
        if not self.beginMoveRows(QModelIndex(), sourceRow, sourceRow + count - 1, QModelIndex(), destinationChild):
            return False
        block = self.__rows[sourceRow : sourceRow + count]
        del self.__rows[sourceRow : sourceRow + count]  # pylint: disable=unsupported-delete-operation
        at = destinationChild if destinationChild < sourceRow else destinationChild - count
        self.__rows[at:at] = block  # pylint: disable=unsupported-assignment-operation
        self.endMoveRows()
        return True

    @override
    def mimeTypes(self) -> list[str]:  # noqa: N802  (Qt API)
        return [LICENSE_MIME_TYPE]

    @override
    def mimeData(self, indexes: Sequence[QModelIndex]) -> QMimeData:  # noqa: N802  (Qt API)
        """What a row dragged by its grip carries: its row number, which only this model's drag reads.

        :param indexes: the dragged row's cells.
        :returns: the data.
        """
        mime = QMimeData()
        rows = {index.row() for index in indexes if index.isValid()}
        if len(rows) == 1:
            mime.setData(LICENSE_MIME_TYPE, str(rows.pop()).encode("ascii"))
        return mime

    # endregion

    def __set_url(self, at: int, text: str) -> bool:
        """Give a row another URL, the document too once the row has an id.

        :param at: the row.
        :param text: the URL typed; empty for none.
        :returns: whether it changed.
        """
        row = self.__rows[at]
        if text == row.url:
            return False
        self.__rows[at] = replace(row, url=text)  # pylint: disable=unsupported-assignment-operation
        index = self.index(at, URL_COLUMN)
        self.dataChanged.emit(index, index)
        if row.license:
            self.__write()
        return True

    def __set_license(self, at: int, text: str) -> bool:
        """Give a row an id: a row being added becomes a license, a license is replaced in its place. A preset brings
        its URL and asks for its text; a custom id keeps the row's own URL and text, and drops a preset's.

        :param at: the row.
        :param text: the id picked or typed.
        :returns: whether it was taken; an empty, unchanged or taken id is not.
        """
        row = self.__rows[at]
        old = row.license
        if not text or text == old or text in self.taken(at):
            return False
        preset = text in PRESET_URLS
        if preset:
            url = PRESET_URLS[text]
        else:
            url = "" if old in PRESET_URLS else row.url
        self.__rows[at] = LicenseRow(text, url)  # pylint: disable=unsupported-assignment-operation
        self.dataChanged.emit(self.index(at, LICENSE_COLUMN), self.index(at, URL_COLUMN))
        if old:
            keep_text = not preset and old not in PRESET_URLS
            self.__document.replace_license(old, AssetLicense(text, url or None), keep_text=keep_text)
        else:
            self.__write()
        if preset and url:
            self.preset_chosen.emit(text, url)
        return True

    def __write(self) -> None:
        """Give the document the licenses as the rows hold them."""
        self.__document.licenses = self.entries
