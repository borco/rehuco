"""The `size` leaf field: an opaque `FileSizeEdit` editor, shown formatted GNU ``ls -sh`` style
([[plugins#field-toolkit]]).
"""

from typing import override

from PySide6.QtWidgets import QLabel

from .field import Field, FieldBinding, FieldEditorWidgets, FieldViewerWidgets
from .widgets import FileSizeEdit


class FileSizeField(Field[int]):
    """A ``size`` field ([[plugins#field-toolkit]], [[field-schema#duration-size]]): stored as whole
    **bytes**, edited via :class:`~rehuco_agent.fields.widgets.FileSizeEdit`. The viewer formats those
    bytes GNU ``ls -sh`` style (``1.4G``, ``300B``). Covers ``original_size`` / ``current_size``.
    """

    TYPE = "size"

    @override
    def make_viewer(self, binding: FieldBinding[int]) -> FieldViewerWidgets:
        label = QLabel(FileSizeEdit.format(binding.value))
        binding.changed.connect(lambda value: label.setText(FileSizeEdit.format(value)))
        return FieldViewerWidgets(self.viewer_tab, self.make_label(), label)

    @override
    def make_editor(self, binding: FieldBinding[int]) -> FieldEditorWidgets:
        editor = FileSizeEdit()
        self.bind_value_widget(editor, binding)  # type: ignore[arg-type]  # set_value is a synthesized slot
        return FieldEditorWidgets(self.editor_tab, self.make_label(), editor)
