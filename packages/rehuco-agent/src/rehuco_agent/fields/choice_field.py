"""The `choice` leaf field: one of a closed list, or none ([[plugins#field-toolkit]], #678)."""

from collections.abc import Sequence
from typing import Final, override

from PySide6.QtWidgets import QLabel

from .field import Field, FieldBinding, FieldEditorWidgets, FieldsTab, FieldViewerWidgets
from .widgets import SingleChoiceComboBox


class ChoiceField(Field[str | None]):
    """One value of a closed list, or none ([[plugins#field-toolkit]], [[field-schema#field-types]]): a label viewer
    and a :class:`~rehuco_agent.fields.widgets.SingleChoiceComboBox` editor whose first entry is empty. Covers an
    asset's ``kind``, whose missing value is *not known*, a different thing from its ``unknown`` ([[assets#kind]]).

    Empty is **absent**, not ``""``: choosing the empty entry removes the key. A stored value no choice names shows
    empty and is left as it is until the user picks one.

    :param name: the model field this binds.
    :param label: the row's caption; derived from ``name`` when omitted.
    :param choices: the values on offer, in order.
    """

    TYPE = "choice"

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
        editor = SingleChoiceComboBox([("", ""), *((choice, choice) for choice in self.__choices)])
        editor.set_value(binding.value or "")
        editor.value_changed.connect(lambda value: binding.set_value(value or None))
        self.bind_external(binding.changed, lambda value: editor.set_value(value or ""))
        return FieldEditorWidgets(self.editor_tab, self.make_label(), editor)
