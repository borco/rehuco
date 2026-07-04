"""The `text` leaf field: a read-only label viewer and a `QLineEdit` editor (§13.2.1)."""

from typing import override

from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import QLabel, QLineEdit, QWidget

from rehuco_agent.fields.field import Field, FieldBinding


class TextField(Field[str]):
    """A single-line `text` field (§13.2.1): a label viewer + a `QLineEdit` editor, live-bound to the binding."""

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

        :param line_edit: the editor to update.
        :param value: the new value.
        """
        with QSignalBlocker(line_edit):
            line_edit.setText(value)
