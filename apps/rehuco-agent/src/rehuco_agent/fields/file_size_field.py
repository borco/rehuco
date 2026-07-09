"""The `size` leaf field: an opaque `FileSizeEdit` editor, shown formatted GNU ``ls -sh`` style
([[plugins#field-toolkit]]).
"""

from typing import override

from PySide6.QtWidgets import QLabel, QWidget

from rehuco_agent.fields.field import Field, FieldBinding
from rehuco_agent.fields.widgets import FileSizeEdit


class FileSizeField(Field[int]):
    """A ``size`` field ([[plugins#field-toolkit]], [[field-schema#duration-size]]): stored as whole
    **bytes**, edited via :class:`~rehuco_agent.fields.widgets.FileSizeEdit`. The viewer formats those
    bytes GNU ``ls -sh`` style (``1.4G``, ``300B``). Covers ``original_size`` / ``current_size``.
    """

    TYPE = "size"

    @override
    def make_viewer(self, binding: FieldBinding[int]) -> QWidget:
        label = QLabel(FileSizeEdit.format(binding.value))
        binding.changed.connect(lambda value: label.setText(FileSizeEdit.format(value)))
        return label

    @override
    def make_editors(self, binding: FieldBinding[int]) -> list[QWidget]:
        editor = FileSizeEdit()
        editor.value = binding.value
        editor.value_changed.connect(binding.set_value)  # type: ignore[attr-defined]
        binding.changed.connect(editor.set_value)  # type: ignore[attr-defined]
        return [editor]
