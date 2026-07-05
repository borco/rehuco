"""The `text` leaf field: a read-only label viewer and a `QLineEdit` editor ([[plugins#field-toolkit]])."""

from typing import override

from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import QLabel, QLineEdit, QWidget

from rehuco_agent.fields.field import Field, FieldBinding


class TextField(Field[str]):
    """A single-line `text` field ([[plugins#field-toolkit]]): a label viewer + a `QLineEdit` editor,
    live-bound to the binding.
    """

    TYPE = "text"

    @override
    def make_viewer(self, binding: FieldBinding[str]) -> QWidget:
        label = QLabel(binding.value)
        binding.changed.connect(label.setText)
        return label

    @override
    def make_editors(self, binding: FieldBinding[str]) -> list[QWidget]:
        line_edit = QLineEdit(binding.value)
        line_edit.textChanged.connect(binding.set_value)
        binding.changed.connect(lambda value: self.__echo(line_edit, value))
        return [line_edit]

    @staticmethod
    def __echo(line_edit: QLineEdit, value: str) -> None:
        """Update the editor from a binding change without re-emitting ``textChanged`` (echo guard).

        The text-equality check is not an optimization: ``setText`` resets the cursor to the end
        even for identical text, so echoing the editor's own edit back into it unguarded would
        teleport the cursor on every mid-string keystroke (#35).

        :param line_edit: the editor to update.
        :param value: the new value.
        """
        if line_edit.text() != value:
            with QSignalBlocker(line_edit):
                line_edit.setText(value)
