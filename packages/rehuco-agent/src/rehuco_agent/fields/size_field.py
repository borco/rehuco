"""The `size` leaf field: one size in whole bytes a record states ([[plugins#field-toolkit]], #678)."""

from typing import override

from PySide6.QtWidgets import QLabel

from .field import Field, FieldBinding, FieldEditorWidgets, FieldViewerWidgets
from .widgets import SizeEdit, SizeMeasurementEdit


class SizeField(Field[int | None]):
    """One size in whole bytes ([[plugins#field-toolkit]], [[field-schema#field-types]]): a label of the human reading
    and a :class:`~rehuco_agent.fields.widgets.SizeEdit` editor. Covers an asset's ``advertised_size``, the download
    size the store states. Unlike the measured pair of :class:`~rehuco_agent.fields.size_pair_field.SizePairField`
    it has nothing to measure: nothing on disk says what a download weighs.

    ``None`` is unknown, distinct from a genuine ``0``; the viewer's tooltip is the exact bytes.
    """

    TYPE = "size"

    @override
    def make_viewer(self, binding: FieldBinding[int | None]) -> FieldViewerWidgets:
        label = QLabel()
        self.__render(label, binding.value)
        self.bind_external(binding.changed, lambda value: self.__render(label, value))
        return FieldViewerWidgets(self.viewer_tab, self.make_label(), label)

    @override
    def make_editor(self, binding: FieldBinding[int | None]) -> FieldEditorWidgets:
        editor = SizeEdit()
        self.bind_value_widget(editor, binding)  # type: ignore[arg-type]  # set_value is a synthesized slot
        return FieldEditorWidgets(self.editor_tab, self.make_label(), editor)

    @staticmethod
    def __render(label: QLabel, value: int | None) -> None:
        """Show a size as the viewer words it.

        :param label: the viewer label.
        :param value: the size in bytes, or ``None``.
        """
        label.setText(SizeMeasurementEdit.format(value))
        label.setToolTip("" if value is None else f"{value:,} bytes")
