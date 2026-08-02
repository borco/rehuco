"""The ``authors`` record list as a two-column model: a name, and an optional author-page URL
([[field-schema#authors]]).
"""

from collections.abc import Sequence
from typing import Any, Final, override

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QPersistentModelIndex, Qt, Signal
from PySide6.QtGui import QBrush, QColor
from rehuco_core import AuthorEntry, author_name

from ..author_url import is_http_author_url
from ..colors import WARNING_COLOR

NAME_COLUMN: Final = 0
"""The author's name -- the cell an insert opens, and the one an entry cannot be without."""

URL_COLUMN: Final = 1
"""The author-page URL, empty for the common case: an entry carries one or it is a plain name."""

COLUMN_COUNT: Final = 2

COLUMN_TITLES: Final = ("Name", "URL")

MISSING_NAME_REASON: Final = "An author entry needs a name."
"""Shown on a row whose name has been emptied ([[field-schema#authors]]: the editor enforces a
non-empty name on what it writes)."""

INVALID_URL_REASON: Final = "A link must be a full http:// or https:// address, or empty."
"""Shown on a row whose URL is present but not a strict http/https address -- the value would render
as no link at all in the viewer ([[data-model#write-integrity]]), so the editor says so where it was
typed rather than letting it silently disappear."""

type ModelIndex = QModelIndex | QPersistentModelIndex
"""What Qt hands a model method; the persistent form arrives from a view holding onto an index."""


def canonical_author_entry(entry: AuthorEntry) -> AuthorEntry:
    """One entry in the minimal form it is stored in ([[field-schema#authors]]).

    A record carrying nothing but a name reduces to that name -- the same reduction
    :attr:`RehuDocument.authors <rehuco_core.RehuDocument.authors>`'s setter performs on write, applied
    here as well so an entry that reads as a record only because a URL was typed and then cleared does
    not keep the simple comma editor switched off for a reason no user could see. A record with any
    other key is left exactly as it is: it is not a plain name, and the key may be one no editor here
    can show.

    Public because both sides of the editor have to agree on it: the model stores entries this way and
    :class:`~rehuco_agent.fields.widgets.authors_editor.AuthorsEditor` holds its value that way, and
    were the two to disagree the editor would rebuild its rows -- closing an open cell -- after edits
    that changed nothing.

    :param entry: the entry as edited or as read from a document.
    :returns: the bare name for a record holding nothing else, the entry itself otherwise.
    """
    if isinstance(entry, dict) and set(entry) == {"name"} and isinstance(entry["name"], str):
        return entry["name"]
    return entry


class AuthorsTableModel(QAbstractTableModel):
    """The document's ``authors`` list as editable rows of *name* and *URL* ([[field-schema#authors]]).

    **Merge, don't rebuild.** A cell edit writes back into the entry the row was built from, changing
    only the key it owns: retyping a name on a ``{"name", "url", <future_key>}`` record keeps both the
    URL and the key no editor here can show. Reconstructing the entry from the two cells instead would
    drop that key on an entry nobody meant to touch -- an *invisible* loss, and the one this issue's
    design note calls the worst kind. The entry itself is never mutated in place: the document hands
    its lists out by reference, so an edit builds a **new** record and leaves the old object alone,
    which is what keeps an unsaved document's own state from moving under it.

    **Canonical minimal form on the way out.** :attr:`entries` reduces a record carrying nothing but a
    name back to a plain string, matching what
    :attr:`RehuDocument.authors <rehuco_core.RehuDocument.authors>`'s setter would store anyway. Doing
    it here as well is what keeps :func:`~rehuco_core.authors_comma_editable` honest: an entry that
    *reads* as a record only because a URL was typed and then cleared would otherwise keep the simple
    comma editor switched off for no reason a user could see. A record with keys beyond ``name`` is
    left as it is -- it genuinely is not a plain name.

    **Validation is flagged, never enforced.** An empty name or a non-http(s) URL colors its cell and
    explains itself in a tooltip; nothing refuses the keystroke and nothing is dropped. A modal
    complaint mid-typing would fight the user for every intermediate state a URL passes through, and a
    silent revert would be worse.

    **Also an `ItemEditor`/`ItemOrderingEditor`** (structurally -- no explicit `Protocol` inheritance,
    since mixing `Protocol`'s metaclass with Shiboken's raises a metaclass conflict): :meth:`insert`,
    :meth:`delete`, :meth:`move_to_top` and friends are the row-number-in, row-number-out shape both
    protocols ask for, built on the same primitives (`insertRows`/`removeRows`/`moveRows`) their
    view-facing counterparts already use.

    :param parent: optional Qt parent.
    """

    count_changed = Signal()
    """Fires whenever :attr:`count` changes -- the `ItemOrderingEditor` contract."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__entries: list[AuthorEntry] = []
        """The rows, in order. Every write to it below carries a pylint suppression: the checker reads
        an ``AuthorEntry`` element as unsubscriptable and reports the *list* operation as the error."""
        self.rowsInserted.connect(self.count_changed)
        self.rowsRemoved.connect(self.count_changed)
        self.modelReset.connect(self.count_changed)

    @property
    def count(self) -> int:
        """How many authors there are -- the `ItemOrderingEditor` contract."""
        return len(self.__entries)

    def insert(self, at: int) -> int:
        """Insert a blank entry after ``at``, or at the end -- the `ItemEditor` contract.

        :param at: the row to insert after, or a negative row to append.
        :returns: the new entry's row.
        """
        target = at + 1 if at >= 0 else len(self.__entries)
        self.insertRow(target)
        return target

    def delete(self, at: int) -> None:
        """Drop one author -- the `ItemEditor` contract.

        :param at: the row to drop; a negative row is a no-op.
        """
        if at >= 0:
            self.removeRow(at)

    def reset(self) -> None:
        """No-op -- authors have no defaults concept (the `ItemEditor` contract)."""

    def move_to_top(self, at: int) -> int:
        """Move one author to the first row -- the `ItemOrderingEditor` contract.

        :param at: the row to move.
        :returns: the row it ended up at.
        """
        return self.__move(at, 0)

    def move_up(self, at: int) -> int:
        """Move one author up a row -- the `ItemOrderingEditor` contract.

        :param at: the row to move.
        :returns: the row it ended up at.
        """
        return self.__move(at, at - 1)

    def move_down(self, at: int) -> int:
        """Move one author down a row -- the `ItemOrderingEditor` contract.

        :param at: the row to move.
        :returns: the row it ended up at.
        """
        return self.__move(at, at + 1)

    def move_to_bottom(self, at: int) -> int:
        """Move one author to the last row -- the `ItemOrderingEditor` contract.

        :param at: the row to move.
        :returns: the row it ended up at.
        """
        return self.__move(at, len(self.__entries) - 1)

    def __move(self, row: int, destination: int) -> int:
        """Move ``row`` to ``destination``, as one model move, and say where it ended up.

        `QAbstractItemModel.moveRow` is the whole operation: the model reports a single ``rowsMoved``,
        every other row keeps its index, and the selection follows the entry rather than the position
        it used to sit at. Nothing is taken out and put back, so nothing has to be repaired afterwards.

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

    @property
    def entries(self) -> tuple[AuthorEntry, ...]:
        """Every entry, in row order, in canonical minimal form ([[field-schema#authors]])."""
        return tuple(self.__entries)

    def set_entries(self, entries: Sequence[AuthorEntry]) -> None:
        """Replace every row, as one model reset, if the entries actually differ.

        Canonicalized on the way in (:func:`canonical_author_entry`), so what is stored is what
        :attr:`entries` reports: a caller can hand back what it just read without that round trip
        counting as a change and rebuilding the rows under an open editor.

        :param entries: the authors list to show, in order.
        """
        replacement = [canonical_author_entry(entry) for entry in entries]
        if replacement == self.__entries:
            return
        self.beginResetModel()
        self.__entries = replacement
        self.endResetModel()

    def invalid_reason(self, row: int, column: int) -> str:
        """Why the cell at ``row``/``column`` is not something this editor would write, if it isn't.

        :param row: the row to test.
        :param column: :data:`NAME_COLUMN` or :data:`URL_COLUMN`.
        :returns: the explanation, or an empty string when the cell is fine.
        """
        entry = self.__entries[row]
        if column == NAME_COLUMN:
            return "" if author_name(entry).strip() else MISSING_NAME_REASON
        url = self.__entry_url(entry)
        return "" if not url or is_http_author_url(url) else INVALID_URL_REASON

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
            return author_name(entry) if index.column() == NAME_COLUMN else self.__entry_url(entry)
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
        entry = self.__entries[row]
        if index.column() == NAME_COLUMN:
            replacement = canonical_author_entry(self.__with_name(entry, text))
        else:
            replacement = canonical_author_entry(self.__with_url(entry, text))
        if replacement == entry:
            return False
        self.__entries[row] = replacement  # pylint: disable=unsupported-assignment-operation
        # both cells: a name typed onto a record can change what the URL cell's validity means, and
        # an emptied URL turns the record back into a plain string
        self.dataChanged.emit(index.sibling(row, NAME_COLUMN), index.sibling(row, URL_COLUMN))
        return True

    @override
    def insertRows(self, row: int, count: int, parent: ModelIndex = QModelIndex()) -> bool:  # noqa: N802
        if parent.isValid() or count < 1 or not 0 <= row <= len(self.__entries):
            return False
        self.beginInsertRows(QModelIndex(), row, row + count - 1)
        # a blank *string*, not a blank record: an entry with no name is not a record of anything yet
        self.__entries[row:row] = [""] * count  # pylint: disable=unsupported-assignment-operation
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

    @staticmethod
    def __entry_url(entry: AuthorEntry) -> str:
        """The author-page URL one entry carries.

        :param entry: one author entry, string or record.
        :returns: the URL, or an empty string for a plain name or a record with a non-string one.
        """
        url = entry.get("url") if isinstance(entry, dict) else None
        return url if isinstance(url, str) else ""

    @staticmethod
    def __with_name(entry: AuthorEntry, name: str) -> AuthorEntry:
        """``entry`` under a new name, keeping every other key it carries.

        :param entry: the entry to rename.
        :param name: the new name.
        :returns: a plain string for a plain-string entry, otherwise a new record.
        """
        return {**entry, "name": name} if isinstance(entry, dict) else name

    @staticmethod
    def __with_url(entry: AuthorEntry, url: str) -> AuthorEntry:
        """``entry`` under a new URL, keeping every other key it carries.

        An emptied URL **deletes the key** rather than storing ``""``: absent is not empty
        ([[field-schema#deferred-items]]), and a record left carrying an empty URL is one the
        canonical form would rewrite anyway.

        :param entry: the entry to link or unlink.
        :param url: the new URL, or an empty string to drop it.
        :returns: a new record, or the plain name when there is no URL to carry.
        """
        if isinstance(entry, dict):
            record = {key: value for key, value in entry.items() if key != "url"}
            return {**record, "url": url} if url else record
        return {"name": entry, "url": url} if url else entry
