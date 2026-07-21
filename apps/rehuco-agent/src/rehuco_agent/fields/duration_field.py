"""The `duration` leaf field: an opaque `DurationEdit` editor, shown formatted per §17.3.2
([[plugins#field-toolkit]]).
"""

from typing import override

from PySide6.QtWidgets import QLabel

from .field import Field, FieldBinding, FieldEditorWidgets, FieldViewerWidgets
from .widgets import DurationEdit


class DurationField(Field[int | None]):
    """A ``duration`` field ([[plugins#field-toolkit]], [[field-schema#field-types]]): stored as
    whole **seconds**, edited via :class:`~rehuco_agent.fields.widgets.DurationEdit`. The viewer
    formats those seconds per [[field-schema#duration-format]] (``2h 15m``; ``None`` -- unmeasured --
    renders empty, a genuine ``0`` renders honestly as ``0s``). Covers ``original_duration`` /
    ``current_duration`` / ``advertised_duration``.
    """

    TYPE = "duration"

    @override
    def make_viewer(self, binding: FieldBinding[int | None]) -> FieldViewerWidgets:
        label = QLabel(DurationEdit.format(binding.value))
        self.bind_external(binding.changed, lambda value: label.setText(DurationEdit.format(value)))
        return FieldViewerWidgets(self.viewer_tab, self.make_label(), label)

    @override
    def make_editor(self, binding: FieldBinding[int | None]) -> FieldEditorWidgets:
        editor = DurationEdit()
        self.bind_value_widget(editor, binding)  # type: ignore[arg-type]  # set_value is a synthesized slot
        return FieldEditorWidgets(self.editor_tab, self.make_label(), editor)
