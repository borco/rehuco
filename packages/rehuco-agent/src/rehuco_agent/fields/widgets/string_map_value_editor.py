"""A ``str -> str`` map as a value widget: a field's editor over :class:`~.string_map_editor.StringMapEditor` (#678)."""

from collections.abc import Mapping

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget

from .string_map_editor import StringMapEditor


class StringMapValueEditor(StringMapEditor):
    """A :class:`~.string_map_editor.StringMapEditor` that meets the value-widget contract
    ([[plugins#field-toolkit]]): :attr:`value`, ``value_changed`` and :meth:`set_value`.

    **The value is reported once per edit and never echoed back out.** :meth:`set_value` seeds the rows under a guard,
    so a map the *owner* wrote is not reported to the owner as a user edit. A map equal to the one the rows make is
    left alone, which is what keeps a row still waiting for its key: it is no part of the map, so the echo of the edit
    before it never replaces the table and loses it.

    :param parent: optional Qt parent.
    """

    value_changed = Signal(object)
    """Fires with the map the rows make, on every user edit -- the `ValueWidget` contract
    ([[plugins#field-toolkit]])."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__echoing = False
        self.values_changed.connect(self.__on_values_changed)

    @property
    def value(self) -> dict[str, str]:
        """The map the rows make: a row with no key, or a key an earlier row has, is left out."""
        return self.mapping

    @property
    def header_height(self) -> int:
        """The table's own column header height (`HeaderPinned`, [[plugins#field-toolkit]]): the row's label is pinned
        to it, so it sits level with the column titles however many rows there are."""
        return self.view.horizontalHeader().sizeHint().height()  # type: ignore[attr-defined]  # a table's view

    def set_value(self, value: Mapping[str, str]) -> None:
        """Show ``value`` without reporting an edit (the echo guard).

        :param value: the map to show.
        """
        if value == self.mapping:
            return
        self.__echoing = True
        try:
            self.mapping = value
        finally:
            self.__echoing = False

    def __on_values_changed(self) -> None:
        """Report an edit with the map it left, unless the owner is seeding the rows."""
        if not self.__echoing:
            self.value_changed.emit(self.mapping)
