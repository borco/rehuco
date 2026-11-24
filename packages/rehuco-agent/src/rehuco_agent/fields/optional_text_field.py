"""The `optional_text` leaf field: free text where empty is absent ([[plugins#field-toolkit]], #678)."""

from typing import override

from PySide6.QtWidgets import QLabel

from .field import Field, FieldBinding, FieldEditorWidgets, FieldViewerWidgets
from .widgets import LineEdit


class OptionalTextField(Field[str | None]):
    """A single line of text a record may leave out ([[plugins#field-toolkit]], [[field-schema#deferred-items]]):
    a label viewer and a `LineEdit` editor. Covers an asset's versions and its advertised triangle count and
    texture size, the last two typed in the range notation of :class:`~rehuco_core.ValueRange` and **never refused**,
    since text that is no range stays as it was typed ([[assets#ranges]]).

    Empty is **absent**, not ``""``: clearing the editor removes the key, and an absent value edits as an empty line
    rather than a placeholder the user has to delete. The mapping is this field's, not the widget's: `LineEdit` is
    the plain text value widget every other string field binds to, and a text editor has no notion of a key that
    stops existing when it is emptied.
    """

    TYPE = "optional_text"

    @override
    def make_viewer(self, binding: FieldBinding[str | None]) -> FieldViewerWidgets:
        label = QLabel(binding.value or "")
        label.setWordWrap(True)
        self.bind_external(binding.changed, lambda value: label.setText(value or ""))
        return FieldViewerWidgets(self.viewer_tab, self.make_label(), label)

    @override
    def make_editor(self, binding: FieldBinding[str | None]) -> FieldEditorWidgets:
        editor = LineEdit()
        self.configure_editor(editor)
        editor.set_value(binding.value or "")
        editor.value_changed.connect(lambda text: binding.set_value(text or None))
        self.bind_external(binding.changed, lambda value: editor.set_value(value or ""))
        return FieldEditorWidgets(self.editor_tab, self.make_label(), editor)

    def configure_editor(self, editor: LineEdit) -> None:
        """Set up the editor before it is bound -- what a subclass restricts the text with.

        :param editor: the editor this field is about to bind.
        """
