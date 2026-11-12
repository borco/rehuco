"""The editor of one ``str -> str`` map, a root's layouts or its fallbacks: `ItemListEditor` over a
:class:`~.string_map_model.StringMapModel` (#578)."""

# the table chrome here is `LocationReplacementsEditor`'s: both are multi-column rows over `ItemListEditor`
# pylint: disable=duplicate-code

from collections.abc import Callable, Mapping, Sequence
from typing import Final, override

from borco_pyside.widgets import ContentSizedTableView, ItemListEditor, RowBandDelegate
from PySide6.QtCore import QAbstractItemModel, QModelIndex, QPersistentModelIndex, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QAbstractItemView, QComboBox, QHeaderView, QStyleOptionViewItem, QWidget

from ..item_action_icons import apply_item_action_icons
from .string_map_model import KEY_COLUMN, VALUE_COLUMN, StringMapModel

type ModelIndex = QModelIndex | QPersistentModelIndex
"""What Qt hands a delegate method."""


class MapChoicesDelegate(RowBandDelegate):
    """Edits a column with an editable combo of the entries it knows, so a known one is picked rather than spelled; any
    other text can still be typed. The key column offers :attr:`choices`; the value column offers what
    :meth:`set_value_choices` was given says for the row's key (#637). A column with no choices keeps the plain line
    edit.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__choices: tuple[str, ...] = ()
        self.__value_choices: Callable[[str], Sequence[str]] | None = None

    @property
    def choices(self) -> tuple[str, ...]:
        """The keys the combo offers, in order; none leaves the key column a plain line edit."""
        return self.__choices

    @choices.setter
    def choices(self, choices: Sequence[str]) -> None:
        self.__choices = tuple(choices)

    def set_value_choices(self, value_choices: Callable[[str], Sequence[str]] | None) -> None:
        """Offer these values in the value column, by the row's key.

        :param value_choices: what a key's row offers, asked each time an editor opens; ``None`` leaves a plain line
            edit.
        """
        self.__value_choices = value_choices

    @override
    def createEditor(self, parent: QWidget, option: QStyleOptionViewItem, index: ModelIndex) -> QWidget:  # noqa: N802
        if index.column() == KEY_COLUMN:
            choices = self.__choices
        elif self.__value_choices is not None:
            choices = tuple(
                self.__value_choices(str(index.model().index(index.row(), KEY_COLUMN).data(Qt.ItemDataRole.EditRole)))
            )
        else:
            choices = ()
        if not choices:
            return super().createEditor(parent, option, index)
        combo = QComboBox(parent)
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        combo.addItems(list(choices))
        return combo

    @override
    def setEditorData(self, editor: QWidget, index: ModelIndex) -> None:  # noqa: N802  (Qt API name)
        if isinstance(editor, QComboBox):
            editor.setCurrentText(str(index.data(Qt.ItemDataRole.EditRole) or ""))
            return
        super().setEditorData(editor, index)

    @override
    def setModelData(  # noqa: N802  (Qt API name)
        self, editor: QWidget, model: QAbstractItemModel, index: ModelIndex
    ) -> None:
        if isinstance(editor, QComboBox):
            model.setData(index, editor.currentText(), Qt.ItemDataRole.EditRole)
            return
        super().setModelData(editor, model, index)


class StringMapEditor(ItemListEditor):
    """A ``str -> str`` map as a table of a key and a value, both stretched, with no ordering column -- a map has no
    order.

    **F2 is not this table's**: it is left to the Roots view's *Edit* toggle, which holds these tables
    (:class:`~.root_edit_pane.RootEditPane`); a cell still opens on a double-click or by typing.

    :param parent: optional Qt parent; what a ``.ui`` promotes the widget with.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        model = StringMapModel(("Key", "Value"))
        table = ContentSizedTableView()
        delegate = MapChoicesDelegate(table)
        super().__init__(table, model, parent, with_ordering=False, delegate=delegate)
        self.__model: Final = model
        self.__delegate: Final = delegate
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)
        table.setWordWrap(False)
        table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked
            | QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        header = table.horizontalHeader()
        header.setSectionResizeMode(KEY_COLUMN, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(VALUE_COLUMN, QHeaderView.ResizeMode.Stretch)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.item_actions.edit_action.setShortcut(QKeySequence())
        # a map's factory value is its owner's -- a root's file, a default layout -- never this table's
        self.item_actions.reset_action.setVisible(False)
        apply_item_action_icons(self)

    @property
    def mapping(self) -> dict[str, str]:
        """The map the rows make: a row with no key, or a key an earlier row has, is left out."""
        return self.__model.mapping

    @mapping.setter
    def mapping(self, mapping: Mapping[str, str]) -> None:
        self.__model.set_mapping(mapping)

    def set_titles(self, key: str, value: str) -> None:
        """Name the two columns.

        :param key: the key column's header.
        :param value: the value column's header.
        """
        self.__model.set_titles((key, value))

    def set_value_choices(self, value_choices: Callable[[str], Sequence[str]] | None) -> None:
        """Offer these values in the value column's editor, by the row's key (#637).

        :param value_choices: the values a key's row offers, in order; asked each time an editor opens. ``None`` leaves
            a plain line edit.
        """
        self.__delegate.set_value_choices(value_choices)

    def set_value_problem(self, value_problem: Callable[[str, str], str] | None) -> None:
        """Flag a value the checker finds fault with, in colour and with the reason as a tooltip (#637); the value is
        still kept.

        :param value_problem: given a row's key and value, the reason it is unusable, or ``""``.
        """
        self.__model.set_value_problem(value_problem)

    def set_fixed_keys(self, keys: Sequence[str]) -> None:
        """Make the table one row per key, in that order: the key column read-only and no way to add, duplicate or
        delete a row (#637). Show the values with :attr:`mapping`.

        The buttons go but their column's width stays, so a table fixed this way is as wide as one above it that keeps
        its buttons.

        :param keys: the keys, in row order.
        """
        self.__model.set_fixed_keys(keys)
        width = self.item_actions.sizeHint().width()
        for action in (
            self.item_actions.insert_action,
            self.item_actions.duplicate_action,
            self.item_actions.delete_action,
        ):
            action.setVisible(False)
        self.item_actions.setFixedWidth(width)

    def set_key_choices(self, choices: Sequence[str]) -> None:
        """Offer these keys in the key column's editor.

        :param choices: the keys, in order; none leaves a plain line edit.
        """
        self.__delegate.choices = choices
