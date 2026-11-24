"""The `text_choice` leaf field: free text with known values on offer ([[plugins#field-toolkit]], #678)."""

from collections.abc import Sequence
from typing import Final, override

from PySide6.QtWidgets import QLabel

from .field import Field, FieldBinding, FieldEditorWidgets, FieldsTab, FieldViewerWidgets
from .widgets import EditableChoiceComboBox


class TextChoiceField(Field[str | None]):
    """Text a record may leave out, with the usual values on offer ([[plugins#field-toolkit]]): a label viewer and an
    :class:`~rehuco_agent.fields.widgets.EditableChoiceComboBox` editor. Covers an asset's ``license``, the short id a
    library is filtered by: the scan writes the ones offered, and a license no list names has an id of its own, which
    can be typed ([[assets#licenses]]).

    Empty is **absent**, not ``""``, as in :class:`~rehuco_agent.fields.optional_text_field.OptionalTextField`.

    :param name: the model field this binds.
    :param label: the row's caption; derived from ``name`` when omitted.
    :param choices: the texts on offer, in order.
    """

    TYPE = "text_choice"

    def __init__(
        self,
        name: str,
        label: str | None = None,
        *,
        viewer_tab: FieldsTab,
        editor_tab: FieldsTab,
        choices: Sequence[str],
    ) -> None:
        super().__init__(name, label, viewer_tab=viewer_tab, editor_tab=editor_tab)
        self.__choices: Final = tuple(choices)

    @override
    def make_viewer(self, binding: FieldBinding[str | None]) -> FieldViewerWidgets:
        label = QLabel(binding.value or "")
        self.bind_external(binding.changed, lambda value: label.setText(value or ""))
        return FieldViewerWidgets(self.viewer_tab, self.make_label(), label)

    @override
    def make_editor(self, binding: FieldBinding[str | None]) -> FieldEditorWidgets:
        editor = EditableChoiceComboBox(self.__choices)
        editor.set_value(binding.value or "")
        editor.value_changed.connect(lambda text: binding.set_value(text or None))
        self.bind_external(binding.changed, lambda value: editor.set_value(value or ""))
        return FieldEditorWidgets(self.editor_tab, self.make_label(), editor)
