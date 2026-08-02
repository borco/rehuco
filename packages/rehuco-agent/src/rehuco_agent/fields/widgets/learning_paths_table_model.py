"""The ``learning_paths`` records as a four-column model over every scope in the block: a title, a
position, whose path it is, and whether this identity follows it
([[field-schema#learning-path-ownership]]).
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, override

from PySide6.QtCore import QModelIndex, QObject, QSortFilterProxyModel, Qt
from rehuco_core import PUBLIC_USERNAME, learning_path_ref, titled_index

from ..indexed_list_field import UNPLACED_INDEX
from .membership_table_model import INDEX_COLUMN, TITLE_COLUMN, MembershipTableModel, ModelIndex

OWNER_COLUMN: Final = 2
"""Whose path this is -- the scope its owned record sits in ([[field-schema#learning-path-ownership]]).

Read-only, and not a field: ownership is *structural*, so there is nothing here a cell could set. Moving a
path between identities is what deleting it does, and only in the one case that has to
(:meth:`LearningPathsTableModel.delete`)."""

SUBSCRIBED_COLUMN: Final = 3
"""Whether this identity follows somebody else's path -- a checkbox, because subscribing **is** a boolean:
a bare ``{ref}`` in your own scope, present or not ([[field-schema#learning-path-ownership]]). There is no
title or index beside it to fill in, since a subscriber has neither of their own."""

REF_KEY: Final = "ref"
"""The slot key a minted path and a subscription both carry; core's own spelling
(:data:`~rehuco_core.learning_path_entries.REF_KEY`), restated here because this module *writes* it."""

OWN_SCOPE_TOOLTIP: Final = "Your own path. Editing its title renames it in this file only."
"""Why the title cell of an owned row is editable, and how far the rename reaches
([[field-schema#learning-path-ownership]]: there is no global rename yet, and the cell says so rather than
being disabled for a limit that is temporary)."""

PUBLIC_SCOPE_TOOLTIP: Final = (
    "Published to everyone. Visible without subscribing; deleting it leaves every private copy."
)
"""What the reserved ``public`` scope is, on the rows sitting in it."""

FOREIGN_SCOPE_TOOLTIP: Final = "{owner}'s own path. Subscribe to follow it; only its owner can retitle it."
"""Why another identity's row is read-only -- and what the one control on it does."""


@dataclass
class LearningPathRow:
    """One **owned** learning-path record, and the scope it sits in
    ([[field-schema#learning-path-ownership]]).

    A row is an owned record, never a subscription: a bare ``{ref}`` has no title and no index of its own,
    so showing it as a row of its own would show a blank line where the path it points at already has one.
    Following somebody's path is a checkbox **on their row** instead, which is also the shape the storage
    has -- the subscription is a pointer, not an entry.

    :param scope: the identity whose block the record sits in, or
        :data:`~rehuco_core.PUBLIC_USERNAME`.
    :param record: the stored record, by reference -- never mutated, only replaced (the merge contract).
    """

    scope: str
    record: dict[str, Any]


class LearningPathsTableModel(MembershipTableModel):
    """The block's learning paths as editable rows across **every** scope
    ([[field-schema#learning-path-ownership]]).

    The rows are what is *in the file*; which of them an identity is actually in is a filter over them
    (:class:`LearningPathScopeFilterProxyModel`), not a second model -- the private paths of other
    identities are exactly what the editor exists to be able to act on, and hiding them by building a
    different model would leave nothing to reveal.

    **One row per owned record, not per path.** A path published to ``public`` *and* kept privately is two
    records, and deleting the public copy while keeping the private one is a thing the spec asks for
    ([[field-schema#learning-path-ownership]]) -- so the editor shows two rows where the viewer, which
    renders a set of paths rather than acting on records, deduplicates them into one
    (:func:`~rehuco_core.visible_learning_paths`).

    **Who may edit what.** A row is editable exactly where there is somebody to permit it: this identity's
    own rows, and the reserved ``public`` scope, which is not a person and so belongs to no one to refuse.
    Another identity's rows are read-only -- their titles are theirs, and following one is the checkbox
    rather than a copy of it.

    **Deleting can reparent instead of removing.** An owned path that others subscribe to moves to the
    ``unknown`` identity rather than stranding them: their subscriptions still resolve, and the path is
    left ownerless rather than deleted out from under people who did not ask for that
    ([[field-schema#learning-path-ownership]]). With no subscribers it simply goes.

    **A minted ``ref`` comes from outside.** Uniqueness is file-wide and this model sees one block, so the
    slot is asked for rather than computed here (``next_ref``) -- the same runtime-callback seam every
    other field with a question the toolkit can't answer uses.

    :param username: the current identity -- whose rows are editable, and where a subscription is written.
    :param next_ref: hands back the next free file-scoped slot, called once per minted path
        (:meth:`~rehuco_core.RehuDocument.next_learning_path_ref`).
    :param unknown_username: the identity a deleted-but-subscribed path is reparented to.
    :param parent: optional Qt parent.
    """

    COLUMN_TITLES = ("Title", "Index", "Owner", "Subscribed")

    def __init__(
        self,
        username: str,
        next_ref: Callable[[], int],
        unknown_username: str,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.__username: Final = username
        self.__next_ref: Final = next_ref
        self.__unknown_username: Final = unknown_username
        self.__records: dict[str, list[dict[str, Any]]] = {}
        """Every scope's records, the value this model holds and hands back. Records that are neither an
        owned path nor a usable subscription are in here too, and have no row: unshowable is not the same
        as unwanted, and the merge contract's whole point is that a record nobody edited survives."""
        self.__rows: list[LearningPathRow] = []
        """The owned records, in scope-then-stored order -- maintained alongside :attr:`__records` rather
        than recomputed, so an edit never resets the model out from under an open cell editor."""

    @property
    def entries(self) -> dict[str, list[dict[str, Any]]]:
        """Every scope's records, ready to store ([[field-schema#learning-path-ownership]])."""
        return {scope: list(records) for scope, records in self.__records.items()}

    def set_entries(self, records_by_scope: Mapping[str, Sequence[dict[str, Any]]]) -> None:
        """Replace every row, as one model reset, if the records actually differ.

        The equality check is the echo guard, exactly as it is for the collections rows: a caller handing
        back what it just read must not rebuild the rows under an open cell editor.

        :param records_by_scope: the records to show, keyed by scope
            (:attr:`~rehuco_core.RehuDocument.learning_path_records`).
        """
        replacement = {scope: list(records) for scope, records in records_by_scope.items() if records}
        if replacement == self.__records:
            return
        self.beginResetModel()
        self.__records = replacement
        self.__rows = [
            LearningPathRow(scope, record)
            for scope, records in self.__records.items()
            for record in records
            if titled_index(record) is not None
        ]
        self.endResetModel()

    def scope(self, row: int) -> str:
        """Whose path ``row`` is.

        :param row: the row to read.
        :returns: the identity owning it, or :data:`~rehuco_core.PUBLIC_USERNAME`.
        """
        return self.__rows[row].scope

    def is_subscribed(self, row: int) -> bool:
        """Whether the current identity follows ``row``.

        :param row: the row to read.
        :returns: whether this identity's own scope holds a bare ``{ref}`` pointing at it.
        """
        ref = learning_path_ref(self.__rows[row].record)
        return ref is not None and self.__subscription(ref) is not None

    def row_is_subscribable(self, row: int) -> bool:
        """Whether following ``row`` is a thing that can be done at all.

        Not for one's own rows (owning is not following) and not for ``public`` (published paths are
        visible to everyone without subscribing, [[field-schema#learning-path-ownership]]), and not for a
        record carrying no ``ref``, which is a path nothing can point at.

        :param row: the row to test.
        :returns: whether the checkbox is offered on it.
        """
        return self.__rows[row].scope not in (self.__username, PUBLIC_USERNAME) and (
            learning_path_ref(self.__rows[row].record) is not None
        )

    def row_is_visible(self, row: int) -> bool:
        """Whether ``row`` is one the current identity is actually *in*.

        The same three sources the viewer resolves ([[field-schema#learning-path-ownership]]): its own
        paths, the ones it subscribes to, and the reserved ``public`` scope. What
        :class:`LearningPathScopeFilterProxyModel` filters on.

        :param row: the row to test.
        :returns: whether it belongs in the identity's own view of the file.
        """
        return self.__rows[row].scope in (self.__username, PUBLIC_USERNAME) or self.is_subscribed(row)

    def set_subscribed(self, row: int, subscribed: bool) -> bool:
        """Start or stop following ``row``'s path ([[field-schema#learning-path-ownership]]).

        Adding a bare ``{ref}`` to this identity's own scope, or dropping it again -- never copying the
        row: a subscriber has no title and no index of their own, so there is nothing else to write, and
        an owner's later fix reaches every subscriber with no work.

        :param row: the row to follow or stop following.
        :param subscribed: whether this identity should follow it.
        :returns: whether anything changed -- ``False`` for a row that cannot be followed, or one already
            in the state asked for.
        """
        ref = learning_path_ref(self.__rows[row].record)
        if not self.row_is_subscribable(row) or ref is None or self.is_subscribed(row) == subscribed:
            return False
        if subscribed:
            self.__records.setdefault(self.__username, []).append({REF_KEY: ref})
        else:
            # is_subscribed disagreeing with ``subscribed`` above is exactly this record being present,
            # so the lookup cannot come back empty -- the guard is for the type checker, not the flow
            existing = self.__subscription(ref)
            if existing is not None:
                self.__records[self.__username].remove(existing)
            self.__prune(self.__username)
        cell = self.index(row, SUBSCRIBED_COLUMN)
        self.dataChanged.emit(cell, cell)
        return True

    # region MembershipTableModel contract

    @override
    def record(self, row: int) -> dict[str, Any]:
        return self.__rows[row].record

    @override
    def replace_record(self, row: int, record: dict[str, Any]) -> None:
        entry = self.__rows[row]
        records = self.__records[entry.scope]
        # by identity, not equality: two rows of one scope may hold equal records, and the merge contract
        # is about *this* record's position among them
        position = next(at for at, stored in enumerate(records) if stored is entry.record)
        records[position] = record
        entry.record = record

    @override
    def row_is_editable(self, row: int) -> bool:
        return self.__rows[row].scope in (self.__username, PUBLIC_USERNAME)

    @override
    def insert(self, at: int) -> int:
        """Mint a new path of this identity's own, at the end of its scope -- the `ItemEditor` contract.

        ``at`` is ignored: a new path is this identity's whoever's row was current, and where its record
        sits among that identity's is not something a reader can see (``index`` is the position).

        :param at: the current row; unused, see above.
        :returns: the new row's number.
        """
        del at
        row = len(self.__rows)
        self.insertRow(row)
        return row

    @override
    def delete(self, at: int) -> None:
        """Drop one path, **reparenting** it instead when others follow it -- the `ItemEditor` contract.

        An owned path with subscribers moves to the ``unknown`` identity rather than being removed: the
        subscriptions still resolve, and what is lost is the ownership, not the path
        ([[field-schema#learning-path-ownership]]). It leaves this identity's view either way, which is
        what "delete" means from here. A row this identity may not edit is not one it may delete.

        :param at: the row to drop; a negative or read-only row is a no-op.
        """
        if at < 0 or not self.row_is_editable(at):
            return
        entry = self.__rows[at]
        ref = learning_path_ref(entry.record)
        if entry.scope == self.__username and ref is not None and self.__has_foreign_subscriber(ref):
            self.__reparent(at)
            return
        self.removeRow(at)

    # endregion

    # region Qt model interface

    @override
    def rowCount(self, parent: ModelIndex = QModelIndex()) -> int:  # noqa: N802  (Qt API name)
        return 0 if parent.isValid() else len(self.__rows)

    @override
    def flags(self, index: ModelIndex) -> Qt.ItemFlag:
        flags = super().flags(index)
        if index.isValid() and index.column() == SUBSCRIBED_COLUMN and self.row_is_subscribable(index.row()):
            return flags | Qt.ItemFlag.ItemIsUserCheckable
        return flags

    @override
    # four columns, each with its own answer and its own "nothing to say" -- collapsing them behind one
    # exit would need a sentinel meaning *both* "no answer" and "the answer is None"
    def data(  # pylint: disable=too-many-return-statements
        self, index: ModelIndex, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        if not index.isValid():
            return None
        row, column = index.row(), index.column()
        if column in (TITLE_COLUMN, INDEX_COLUMN):
            if role == Qt.ItemDataRole.ToolTipRole and not super().data(index, role):
                return self.__scope_tooltip(row)
            return super().data(index, role)
        if column == OWNER_COLUMN:
            if role == Qt.ItemDataRole.DisplayRole:
                return self.__rows[row].scope
            return self.__scope_tooltip(row) if role == Qt.ItemDataRole.ToolTipRole else None
        if column == SUBSCRIBED_COLUMN and role == Qt.ItemDataRole.CheckStateRole and self.row_is_subscribable(row):
            return Qt.CheckState.Checked if self.is_subscribed(row) else Qt.CheckState.Unchecked
        return None

    @override
    def setData(  # noqa: N802  (Qt API name)
        self,
        index: ModelIndex,
        value: Any,
        role: int = Qt.ItemDataRole.EditRole,
    ) -> bool:
        if index.isValid() and index.column() == SUBSCRIBED_COLUMN and role == Qt.ItemDataRole.CheckStateRole:
            return self.set_subscribed(index.row(), Qt.CheckState(value) == Qt.CheckState.Checked)
        return super().setData(index, value, role)

    @override
    def insertRows(self, row: int, count: int, parent: ModelIndex = QModelIndex()) -> bool:  # noqa: N802
        # only an append of one: a path is minted into this identity's own scope, so there is no other
        # position in the rows for it to land at -- see :meth:`insert`
        if parent.isValid() or count != 1 or row != len(self.__rows):
            return False
        self.beginInsertRows(QModelIndex(), row, row)
        record = {"title": "", "index": UNPLACED_INDEX, REF_KEY: self.__next_ref()}
        self.__records.setdefault(self.__username, []).append(record)
        self.__rows.append(LearningPathRow(self.__username, record))
        self.endInsertRows()
        return True

    @override
    def removeRows(self, row: int, count: int, parent: ModelIndex = QModelIndex()) -> bool:  # noqa: N802
        if parent.isValid() or count != 1 or not 0 <= row < len(self.__rows):
            return False
        entry = self.__rows[row]
        self.beginRemoveRows(QModelIndex(), row, row)
        records = self.__records[entry.scope]
        records.remove(entry.record)
        self.__prune(entry.scope)
        del self.__rows[row]  # pylint: disable=unsupported-delete-operation
        self.endRemoveRows()
        return True

    # endregion

    def __reparent(self, row: int) -> None:
        """Move ``row``'s record from this identity's scope to the ``unknown`` one, leaving it ownerless.

        What deleting a subscribed-to path does instead of removing it
        ([[field-schema#learning-path-ownership]]). The record itself is untouched -- its ``ref`` is what
        every subscription resolves through, so rewriting it here would break exactly the thing the
        reparenting exists to protect.

        :param row: the row to reparent.
        """
        entry = self.__rows[row]
        self.__records[entry.scope].remove(entry.record)
        self.__prune(entry.scope)
        self.__records.setdefault(self.__unknown_username, []).append(entry.record)
        entry.scope = self.__unknown_username
        self.dataChanged.emit(self.index(row, TITLE_COLUMN), self.index(row, SUBSCRIBED_COLUMN))

    def __has_foreign_subscriber(self, ref: int) -> bool:
        """Whether an identity other than this one follows the path at ``ref``.

        :param ref: the file-scoped slot to look for.
        :returns: whether any other scope holds a bare ``{ref}`` pointing at it.
        """
        return any(
            titled_index(record) is None and learning_path_ref(record) == ref
            for scope, records in self.__records.items()
            if scope != self.__username
            for record in records
        )

    def __subscription(self, ref: int) -> dict[str, Any] | None:
        """This identity's own subscription record for ``ref``, if it has one.

        :param ref: the file-scoped slot to look for.
        :returns: the stored bare ``{ref}`` record, or ``None`` when this identity does not follow it.
        """
        for record in self.__records.get(self.__username, []):
            if titled_index(record) is None and learning_path_ref(record) == ref:
                return record
        return None

    def __prune(self, scope: str) -> None:
        """Drop ``scope`` from the mapping once it holds no records at all.

        So the last path leaving a scope takes the scope with it, rather than leaving an identity in the
        file that only ever existed to hold it.

        :param scope: the scope to drop if it is now empty.
        """
        if not self.__records.get(scope):
            self.__records.pop(scope, None)

    def __scope_tooltip(self, row: int) -> str:
        """What owning, publishing or following ``row`` means, said on the row it applies to.

        :param row: the row to explain.
        :returns: the tooltip text.
        """
        scope = self.__rows[row].scope
        if scope == self.__username:
            return OWN_SCOPE_TOOLTIP
        if scope == PUBLIC_USERNAME:
            return PUBLIC_SCOPE_TOOLTIP
        return FOREIGN_SCOPE_TOOLTIP.format(owner=scope)


class LearningPathScopeFilterProxyModel(QSortFilterProxyModel):
    """Shows either the paths this identity is **in**, or every path in the file
    ([[field-schema#learning-path-ownership]]).

    A proxy over the one model rather than a second model, which is what keeps the two views from becoming
    two code paths: every edit, every row number the action columns hand back, and every record written
    out is the model's, whichever view is on screen.

    Filtering only, deliberately not sorting: ``index`` is the data here, so a table that re-sorted itself
    as that cell was typed into would move the row out from under the cursor.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__all_scopes = False

    @property
    def all_scopes(self) -> bool:
        """Whether every scope's paths are shown, rather than this identity's own view of the file."""
        return self.__all_scopes

    def set_all_scopes(self, all_scopes: bool) -> None:
        """Show every scope's paths, or only the ones this identity is in.

        :param all_scopes: ``True`` for every path in the file, ``False`` for this identity's view.
        """
        if all_scopes == self.__all_scopes:
            return
        self.__all_scopes = all_scopes
        # the public slot rather than either ``invalidate*Filter`` protected one: PySide6 marks both of
        # those deprecated, and there is no sort here for the broader reset to cost anything
        self.invalidate()

    @override
    def filterAcceptsRow(self, source_row: int, source_parent: ModelIndex) -> bool:  # noqa: N802  (Qt API name)
        if source_parent.isValid():
            return False
        model = self.sourceModel()
        if self.__all_scopes or not isinstance(model, LearningPathsTableModel):
            return True
        return model.row_is_visible(source_row)
