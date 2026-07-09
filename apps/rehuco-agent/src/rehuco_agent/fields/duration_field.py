"""The `duration` leaf field: an opaque `DurationEdit` editor, shown formatted per §17.3.2
([[plugins#field-toolkit]]).
"""

from typing import override

from PySide6.QtWidgets import QLabel, QWidget

from rehuco_agent.fields.field import Field, FieldBinding
from rehuco_agent.fields.widgets import DurationEdit


class DurationField(Field[int]):
    """A ``duration`` field ([[plugins#field-toolkit]], [[field-schema#field-types]]): stored as
    whole **seconds**, edited via :class:`~rehuco_agent.fields.widgets.DurationEdit`. The viewer
    formats those seconds per [[field-schema#duration-format]] (``2h 15m``; ``0`` renders empty, not
    ``0s``). Covers ``original_duration`` / ``current_duration`` / ``advertised_duration``.
    """

    TYPE = "duration"

    @override
    def make_viewer(self, binding: FieldBinding[int]) -> QWidget:
        label = QLabel(DurationEdit.format(binding.value))
        binding.changed.connect(lambda value: label.setText(DurationEdit.format(value)))
        return label

    @override
    def make_editors(self, binding: FieldBinding[int]) -> list[QWidget]:
        editor = DurationEdit()
        editor.value = binding.value
        editor.value_changed.connect(binding.set_value)
        binding.changed.connect(editor.set_value)  # type: ignore[attr-defined]
        return [editor]
