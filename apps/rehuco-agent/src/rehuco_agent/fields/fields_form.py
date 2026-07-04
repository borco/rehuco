"""Composes an ordered field list into a viewer or editor `QFormLayout` (§13.2.1)."""

from collections.abc import Sequence
from typing import Any, Final

from PySide6.QtWidgets import QFormLayout, QWidget

from rehuco_agent.fields.field import Field, FieldModel


class FieldsForm:
    """Builds a viewer or editor form from an ordered list of fields (§13.2.1).

    :param fields: the fields to lay out, in display order.
    """

    def __init__(self, fields: Sequence[Field[Any]]) -> None:
        self.__fields: Final = tuple(fields)

    def make_viewer(self, model: FieldModel) -> QWidget:
        """Build a form of read-only viewer rows bound to the model.

        :param model: the reactive view-model each field resolves its binding against.
        :returns: a widget whose ``QFormLayout`` holds one label -> viewer row per field, in order.
        """
        widget = QWidget()
        layout = QFormLayout(widget)
        for field in self.__fields:
            layout.addRow(field.label, field.make_viewer(model.bind(field)))
        return widget

    def make_editor(self, model: FieldModel) -> QWidget:
        """Build a form of editor rows bound to the model.

        :param model: the reactive view-model each field resolves its binding against.
        :returns: a widget whose ``QFormLayout`` holds each field's editor(s); only a field's first
            editor carries the label (the rest seat the future multi-editor split, A2.6/#26).
        """
        widget = QWidget()
        layout = QFormLayout(widget)
        for field in self.__fields:
            binding = model.bind(field)
            for index, editor in enumerate(field.make_editors(binding)):
                layout.addRow(field.label if index == 0 else "", editor)
        return widget
