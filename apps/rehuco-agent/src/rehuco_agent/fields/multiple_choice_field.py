"""The `multi_choice` leaf field: zero or more values from a fixed set, shown as a `FlowLayout` of
checkboxes ([[plugins#field-toolkit]]).
"""

from collections.abc import Sequence
from typing import Final, override

from PySide6.QtWidgets import QLabel

from .field import Field, FieldBinding, FieldEditorWidgets, FieldsTab, FieldViewerWidgets
from .widgets import ChoiceCheckBoxes


class MultipleChoiceField(Field[list[str]]):
    """A ``multi_choice`` field ([[plugins#field-toolkit]], [[field-schema#field-types]]): zero or
    more values from a fixed ``choices`` set, shown as a `FlowLayout`
    (:class:`~borco_pyside.widgets.FlowLayout`) of checkboxes -- covers ``level``
    ([[field-schema#field-mapping]]), which tc4 could tag with more than one of
    beginner/intermediate/advanced/any at once, so this stays multi-select rather than
    mutually-exclusive.

    :param name: the field's identifier on its model.
    :param label: display label; derived from ``name`` when omitted.
    :param choices: the fixed, ordered set of selectable values; defaults empty since the
        registry's uniform ``create(type_, name, label)`` call site can't supply one -- pass the
        real set when constructing this field directly for actual use.
    """

    TYPE = "multi_choice"

    def __init__(
        self,
        name: str,
        label: str | None = None,
        choices: Sequence[str] = (),
        *,
        viewer_tab: FieldsTab,
        editor_tab: FieldsTab,
    ) -> None:
        super().__init__(name, label, viewer_tab=viewer_tab, editor_tab=editor_tab)
        self.__choices: Final = tuple(choices)

    @override
    def make_viewer(self, binding: FieldBinding[list[str]]) -> FieldViewerWidgets:
        label = QLabel(self.__display(binding.value))
        label.setWordWrap(True)
        binding.changed.connect(lambda value: label.setText(self.__display(value)))
        return FieldViewerWidgets(self.viewer_tab, self.make_label(), label)

    @override
    def make_editor(self, binding: FieldBinding[list[str]]) -> FieldEditorWidgets:
        editor = ChoiceCheckBoxes(self.__choices)
        # pyright compares the class-level Signal against the protocol's SignalInstance and rejects the
        # descriptor duality PySide resolves at access time; the wiring is sound (see bind_value_widget).
        self.bind_value_widget(editor, binding)  # type: ignore[arg-type]
        return FieldEditorWidgets(self.editor_tab, self.make_label(), editor)

    def __display(self, values: list[str]) -> str:
        """Join the selected values for the read-only viewer, in ``choices`` order.

        :param values: the bound list of selected choices.
        :returns: the comma-joined display text.
        """
        selected = set(values)
        return ", ".join(choice for choice in self.__choices if choice in selected)
