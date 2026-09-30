"""The `text` leaf field: a read-only label viewer and a `LineEdit` value-widget editor ([[plugins#field-toolkit]])."""

from typing import Final, override

from PySide6.QtWidgets import QLabel

from .field import Field, FieldBinding, FieldEditorWidgets, FieldsTab, FieldViewerWidgets
from .widgets import LineEdit


class TextField(Field[str]):
    """A single-line `text` field ([[plugins#field-toolkit]]): a label viewer + a `LineEdit` editor,
    live-bound to the binding.

    The editor is a `LineEdit` value widget ([[plugins#field-toolkit]]) rather than a raw ``QLineEdit``,
    so the echo/cursor guard (#35) lives in that widget once and the two-way wiring goes through
    :meth:`~rehuco_agent.fields.field.Field.bind_value_widget` like every other content field.

    :param name: the model field this binds.
    :param label: the row's caption; derived from ``name`` when omitted.
    :param viewer_only: build no editor: the value is edited elsewhere (the ``title``, ``publisher`` and
        ``url`` fields are the top source's own, edited on its card by
        :class:`~rehuco_agent.fields.sources_field.SourcesField`, #391) and only read here.
    """

    TYPE = "text"

    def __init__(
        self,
        name: str,
        label: str | None = None,
        *,
        viewer_tab: FieldsTab,
        editor_tab: FieldsTab,
        viewer_only: bool = False,
    ) -> None:
        super().__init__(name, label, viewer_tab=viewer_tab, editor_tab=editor_tab)
        self.__viewer_only: Final = viewer_only

    @override
    def make_viewer(self, binding: FieldBinding[str]) -> FieldViewerWidgets:
        label = QLabel(binding.value)
        label.setWordWrap(True)
        binding.changed.connect(label.setText)
        return FieldViewerWidgets(self.viewer_tab, self.make_label(), label)

    @override
    def make_editor(self, binding: FieldBinding[str]) -> FieldEditorWidgets:
        if self.__viewer_only:
            # an all-``None`` bundle, so the assembler drops the row (the ``TypeField`` idiom, reversed)
            return FieldEditorWidgets(self.editor_tab, None, None)
        editor = LineEdit()
        # pyright compares the class-level Signal against the protocol's SignalInstance and rejects the
        # descriptor duality PySide resolves at access time; the wiring is sound (see bind_value_widget).
        self.bind_value_widget(editor, binding)  # type: ignore[arg-type]
        return FieldEditorWidgets(self.editor_tab, self.make_label(), editor)
