"""The `text` leaf field: a read-only label viewer and a `LineEdit` value-widget editor ([[plugins#field-toolkit]])."""

from typing import override

from PySide6.QtWidgets import QLabel

from rehuco_agent.fields.field import Field, FieldBinding, FieldEditorWidgets, FieldViewerWidgets
from rehuco_agent.fields.widgets import LineEdit


class TextField(Field[str]):
    """A single-line `text` field ([[plugins#field-toolkit]]): a label viewer + a `LineEdit` editor,
    live-bound to the binding.

    The editor is a `LineEdit` value widget ([[plugins#field-toolkit]]) rather than a raw ``QLineEdit``,
    so the echo/cursor guard (#35) lives in that widget once and the two-way wiring goes through
    :meth:`~rehuco_agent.fields.field.Field.bind_value_widget` like every other content field.
    """

    TYPE = "text"

    @override
    def make_viewer(self, binding: FieldBinding[str]) -> FieldViewerWidgets:
        label = QLabel(binding.value)
        label.setWordWrap(True)
        binding.changed.connect(label.setText)
        return FieldViewerWidgets(self.viewer_tab, self.make_label(), label)

    @override
    def make_editor(self, binding: FieldBinding[str]) -> FieldEditorWidgets:
        editor = LineEdit()
        # pyright compares the class-level Signal against the protocol's SignalInstance and rejects the
        # descriptor duality PySide resolves at access time; the wiring is sound (see bind_value_widget).
        self.bind_value_widget(editor, binding)  # type: ignore[arg-type]
        return FieldEditorWidgets(self.editor_tab, self.make_label(), editor)
