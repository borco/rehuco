"""The `date` leaf field: partial-precision (Y / Y-M / Y-M-D) text, edited via an opaque `DateEdit`
([[plugins#field-toolkit]]).
"""

from typing import override

from PySide6.QtWidgets import QLabel

from .field import Field, FieldBinding, FieldEditorWidgets, FieldViewerWidgets
from .widgets import DateEdit


class DateField(Field[str]):
    """A ``date`` field ([[plugins#field-toolkit]], [[field-schema#field-types]]): **partial-precision**
    -- stored and edited as the ``YYYY`` / ``YYYY-MM`` / ``YYYY-MM-DD`` ISO-prefix string it is on
    disk ([[field-schema#deferred-items]]), never parsed into (or held as) a full calendar date --
    edited via :class:`~rehuco_agent.fields.widgets.DateEdit`. The viewer is a plain label showing
    the stored string as-is. Covers ``released``.
    """

    TYPE = "date"

    @override
    def make_viewer(self, binding: FieldBinding[str]) -> FieldViewerWidgets:
        label = QLabel(binding.value)
        binding.changed.connect(label.setText)
        return FieldViewerWidgets(self.viewer_tab, self.make_label(), label)

    @override
    def make_editor(self, binding: FieldBinding[str]) -> FieldEditorWidgets:
        editor = DateEdit()
        self.bind_value_widget(editor, binding)  # type: ignore[arg-type]  # set_value is a synthesized slot
        return FieldEditorWidgets(self.editor_tab, self.make_label(), editor)
