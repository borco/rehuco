"""The memberships tables: ``collections`` and ``learning_paths`` as editable rows
([[plugins#field-toolkit]], [[field-schema#sources]], [[field-schema#learning-path-ownership]]).
"""

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Final

from borco_pyside.widgets import ContentSizedTableView, ItemListEditor
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QWidget

from ...item_action_icons import apply_item_action_icons
from .collections_table_model import CollectionsTableModel
from .index_spin_box_delegate import IndexSpinBoxDelegate, index_spin_box
from .learning_paths_table_model import (
    OWNER_COLUMN,
    SUBSCRIBED_COLUMN,
    LearningPathScopeFilterProxyModel,
    LearningPathsTableModel,
)
from .membership_table_model import INDEX_COLUMN, TITLE_COLUMN

INDEX_COLUMN_PADDING: Final = 8
"""Pixels added to the position column beyond the widest thing that goes in it.

The cell's own margins, which is what sits between the section's edges and the editor Qt puts inside it --
a column sized to the editor exactly is a column the editor is one margin too wide for."""

ALL_SCOPES_TOOLTIP: Final = "Show every identity's learning paths in this file, not only the ones you are in."
"""What the row's misc-column toggle offers -- the all-scopes view
([[field-schema#learning-path-ownership]])."""


class MembershipsEditor(ItemListEditor):
    """What both memberships tables are made of: rows with an insert/edit/delete column, no ordering, and
    a spin box on the position cell (#235).

    **No ordering column.** ``index`` is the position and the row's own place is nothing a reader can see,
    so four move buttons would offer an edit that changes no stored value -- the model's moves are
    correspondingly honest no-ops
    (:class:`~rehuco_agent.fields.widgets.membership_table_model.MembershipTableModel`).

    **The value is reported once per edit and never echoed back out.** ``set_value`` seeds the rows under
    a guard, so a model change the *owner* caused is not reported to the owner as a user edit -- the same
    echo guard every value widget in the toolkit keeps ([[plugins#field-toolkit]]).

    :param view: the table to show the rows in.
    :param model: the rows themselves.
    :param parent: optional Qt parent.
    :param proxy: an optional filter between the two (the learning paths' scope view).
    """

    value_changed = Signal(object)
    """Fires with the new value on every user edit -- the `ValueWidget` contract
    ([[plugins#field-toolkit]])."""

    def __init__(
        self,
        view: ContentSizedTableView,
        model: Any,
        parent: QWidget | None = None,
        *,
        proxy: LearningPathScopeFilterProxyModel | None = None,
    ) -> None:
        super().__init__(view, model, parent, with_ordering=False, proxy=proxy)
        self.__table: Final = view
        """The same view the base holds, kept at its concrete type -- the base knows only
        ``QAbstractItemView``, and a column header is a table's."""
        self.__echoing = False
        """Held while :meth:`set_value` seeds the rows, so the model changes that causes are not reported
        back to the owner that caused them."""

        # a row is one membership, so a click anywhere on it acts on that membership; multi-select would
        # promise a bulk edit none of the actions here can carry out
        view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        # the row numbers say nothing -- the position is a column of its own here
        view.verticalHeader().setVisible(False)
        # banded rows already separate one entry from the next
        view.setShowGrid(False)
        # one line per membership: a table wraps its cells by default, so a long title in a narrow column
        # grows its row to two lines -- and a view sized to its rows then reports a height measured before
        # the columns were laid out, which clips the last entry off the bottom (the ``authors`` rows'
        # lesson, same view class)
        view.setWordWrap(False)
        view.setItemDelegateForColumn(INDEX_COLUMN, IndexSpinBoxDelegate(view))
        self.__size_index_column(view)
        # a default set of memberships would be somebody else's memberships -- there is no reset concept
        # here at all, not just none configured, so the button is hidden rather than left disabled
        self.item_actions.reset_action.setVisible(False)
        # the same glyphs the settings pages' string lists and the authors rows wear
        apply_item_action_icons(self)
        self.values_changed.connect(self.__on_values_changed)

    @property
    def header_height(self) -> int:
        """The table's own column header height (`HeaderPinned`, [[plugins#field-toolkit]]).

        The row's label is pinned to it rather than centred against the whole table, so ``Collections``
        sits level with ``Title``/``Index`` instead of drifting down the middle of a table whose height
        is however many memberships there happen to be. The header is what the label names, and it is
        the one band whose height does not move as rows come and go.
        """
        return self.__table.horizontalHeader().sizeHint().height()

    def report_value(self, value: Any) -> None:
        """Report an edit, unless the rows are being seeded from the owner right now.

        :param value: the newly edited value to report.
        """
        if not self.__echoing:
            self.value_changed.emit(value)

    def seed(self, seed_rows: Callable[[], None]) -> None:
        """Run ``seed_rows`` with the echo guard held, so what it changes is not reported as a user edit.

        :param seed_rows: writes the owner's value into the model.
        """
        self.__echoing = True
        try:
            seed_rows()
        finally:
            self.__echoing = False

    def __on_values_changed(self) -> None:
        """Turn the base's per-edit signal into the `ValueWidget` one, carrying the value."""
        self.report_value(self.value)

    @staticmethod
    def __size_index_column(view: ContentSizedTableView) -> None:
        """Fix the position column at the width its **open editor** needs, not the width its text has.

        A ``ResizeToContents`` column here is sized by what the cell *draws* -- two digits, or nothing at
        all for an unplaced position -- which leaves the spin box that opens in it showing its up/down
        buttons and none of the number between them. The editor is measured instead, built in the table
        (:func:`~rehuco_agent.fields.widgets.index_spin_box_delegate.index_spin_box`) so it is styled the
        way the real one will be, and the header's own label is the floor beneath that.

        Fixed rather than merely wide: the width does not depend on the rows, so there is nothing for a
        re-measurement to discover when they change.

        :param view: the table whose position column to size.
        """
        prototype = index_spin_box(view)
        # never shown: an explicit hide beats deletion alone, which would otherwise leave a stray spin box
        # visible at the table's top-left corner for as long as the deferred delete takes
        prototype.hide()
        header = view.horizontalHeader()
        width = max(prototype.sizeHint().width(), header.sectionSizeHint(INDEX_COLUMN)) + INDEX_COLUMN_PADDING
        prototype.deleteLater()
        header.setSectionResizeMode(INDEX_COLUMN, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(INDEX_COLUMN, width)

    @property
    def value(self) -> Any:
        """The edited value, in the shape the model this editor was built over holds it.

        :raises NotImplementedError: unless a subclass overrides it.
        """
        raise NotImplementedError


class CollectionsEditor(MembershipsEditor):
    """The ``collections`` memberships table: a series name and this resource's position in it
    ([[field-schema#sources]]).

    The simple half of the pair -- one scope, no ownership, no ``ref``, and the collection's cached ``url``
    carried through with no cell of its own.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        model = CollectionsTableModel()
        table = ContentSizedTableView()
        super().__init__(table, model, parent)
        self.__model: Final = model
        """The same model the base holds, kept at its concrete type -- the base knows only
        ``QAbstractItemModel``, and the records are what this widget is for."""

        # the title takes the row: a series name is unbounded where a position is a few digits, so
        # stretching both would leave half the row empty. The position column is the base's to size.
        table.horizontalHeader().setSectionResizeMode(TITLE_COLUMN, QHeaderView.ResizeMode.Stretch)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    @property
    def value(self) -> list[dict[str, Any]]:
        """Every membership record, in row order ([[field-schema#sources]])."""
        return self.__model.entries

    def set_value(self, value: Sequence[dict[str, Any]]) -> None:
        """Seed or echo the rows from ``value`` without reporting an edit (the echo guard).

        :param value: the membership records to show, in stored order.
        """
        self.seed(lambda: self.__model.set_entries(value))


class LearningPathsEditor(MembershipsEditor):
    """The ``learning_paths`` memberships table: a path, its position, whose it is, and whether this
    identity follows it ([[field-schema#learning-path-ownership]]).

    Two views over one model, switched by :meth:`set_all_scopes`: the identity's own -- its paths, its
    subscriptions, and the reserved ``public`` scope -- and every path in the file, which is where another
    identity's private paths become visible and subscribable. The switch is a filter
    (:class:`~rehuco_agent.fields.widgets.learning_paths_table_model.LearningPathScopeFilterProxyModel`),
    never a second model, so an edit made in either view is the same edit.

    :param username: the current identity -- whose rows are editable, and where a subscription is written.
    :param next_ref: hands back the next free file-scoped slot for a minted path.
    :param unknown_username: the identity a deleted-but-subscribed path is reparented to.
    :param parent: optional Qt parent.
    """

    all_scopes_changed = Signal(bool)
    """Fires when the view switches -- what the owner's toggle is kept in step with, so a view restored
    from the saved session state (:meth:`restore_state`) reaches it too."""

    def __init__(
        self,
        username: str,
        next_ref: Callable[[], int],
        unknown_username: str,
        parent: QWidget | None = None,
    ) -> None:
        model = LearningPathsTableModel(username, next_ref, unknown_username)
        table = ContentSizedTableView()
        proxy = LearningPathScopeFilterProxyModel()
        super().__init__(table, model, parent, proxy=proxy)
        self.__model: Final = model
        self.__proxy: Final = proxy

        header = table.horizontalHeader()
        header.setSectionResizeMode(TITLE_COLUMN, QHeaderView.ResizeMode.Stretch)
        for column in (OWNER_COLUMN, SUBSCRIBED_COLUMN):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    @property
    def value(self) -> dict[str, list[dict[str, Any]]]:
        """Every scope's records ([[field-schema#learning-path-ownership]])."""
        return self.__model.entries

    def set_value(self, value: Mapping[str, Sequence[dict[str, Any]]]) -> None:
        """Seed or echo the rows from ``value`` without reporting an edit (the echo guard).

        :param value: the records to show, keyed by scope.
        """
        self.seed(lambda: self.__model.set_entries(value))

    @property
    def all_scopes(self) -> bool:
        """Whether every identity's paths are shown, rather than this identity's own view of the file."""
        return self.__proxy.all_scopes

    def set_all_scopes(self, all_scopes: bool) -> None:
        """Switch between the identity's own view and every path in the file.

        :param all_scopes: ``True`` for every path, ``False`` for this identity's own view.
        """
        if all_scopes == self.all_scopes:
            return
        self.__proxy.set_all_scopes(all_scopes)
        self.all_scopes_changed.emit(all_scopes)

    def save_state(self) -> bytes:
        """Encode which view is shown, for per-``.rehu`` session persistence
        (:class:`~rehuco_agent.fields.field.StatefulWidget`).

        A view choice, not a value: which paths a user was last looking at in *this* file is theirs to
        keep, the same way the ``authors`` editor's mode is.

        :returns: a one-byte blob restorable by :meth:`restore_state`.
        """
        return b"\x01" if self.all_scopes else b"\x00"

    def restore_state(self, state: bytes) -> None:
        """Restore the view produced by :meth:`save_state`.

        :param state: the blob to restore from; anything but a leading ``0x01`` reads as the identity's
            own view.
        """
        self.set_all_scopes(state[:1] == b"\x01")
