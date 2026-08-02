"""Edit a list of strings: `ItemListEditor`'s machinery over a row-sized view onto a `StringItemListModel`."""

from collections.abc import Sequence
from typing import Final

from PySide6.QtWidgets import QWidget

from .content_sized_list_view import ContentSizedListView
from .item_actions import ResetItemAction
from .item_list_editor import ItemListEditor
from .string_item_list_model import StringItemListModel


class StringListEditor(ItemListEditor):
    """Edit an ordered list of strings in place -- `ItemListEditor` with a `StringItemListModel` behind it.

    Everything about *how* the list is edited (the buttons, the keys, one model call per edit, the
    abandoned-insert rule) lives in the base; the model owns *what* insert/delete/reset/reorder do
    (:class:`StringItemListModel`). What is here is just: showing Reset exactly while there is something
    to restore (``reset_action.setVisible(bool(defaults))``, in both :attr:`defaults`' setter and here),
    and the thin :attr:`values`/:attr:`defaults` wrappers over the model.

    The view is a `ContentSizedListView`: it grows with its rows rather than scrolling them, so an
    enclosing page's scroll area does the scrolling instead of a second scrollbar appearing inside a
    widget the reader must first scroll *to*.

    :param parent: optional Qt parent.
    :param defaults: what Reset restores; also what hides Reset while it is empty, since a Reset with
        nothing to restore promises an action that does nothing. Settable later through
        :attr:`defaults`, which is how a widget promoted into a ``.ui`` (constructed with a parent and
        nothing else) gets its own.
    :param with_ordering: whether the ordering column is shown; see
        :meth:`~borco_pyside.widgets.item_list_editor.ItemListEditor.set_ordering_visible`.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        defaults: Sequence[str] = (),
        with_ordering: bool = True,
    ) -> None:
        model: Final = StringItemListModel(defaults=defaults)
        super().__init__(ContentSizedListView(), model, parent, with_ordering=with_ordering)
        self.__model: Final = model
        """The same model the base holds, kept at its concrete type -- ``entries``/``defaults`` are
        what makes this a string-list editor, and the base knows only the two protocols."""
        self.reset_action.setVisible(bool(self.__model.defaults))

    @property
    def reset_action(self) -> ResetItemAction:
        """Put :attr:`defaults` back -- shown exactly while there are any."""
        return self.item_actions.reset_action

    @property
    def values(self) -> tuple[str, ...]:
        """Every entry, in order, exactly as typed -- unnormalized, since normalizing is the owner's."""
        return self.__model.entries

    @values.setter
    def values(self, values: Sequence[str]) -> None:
        """Replace every entry, reporting one edit if the list actually changed.

        :param values: the entries to show, in order.
        """
        self.__model.set_entries(values)

    @property
    def defaults(self) -> tuple[str, ...]:
        """What Reset restores; an empty one hides Reset rather than offering to empty the list."""
        return self.__model.defaults

    @defaults.setter
    def defaults(self, defaults: Sequence[str]) -> None:
        """Set what Reset restores.

        :param defaults: the entries Reset puts back, in order.
        """
        self.__model.defaults = defaults
        self.reset_action.setVisible(bool(self.__model.defaults))
