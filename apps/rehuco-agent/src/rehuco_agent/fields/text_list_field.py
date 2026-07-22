"""The `text list` leaf field: a deduplicated comma-joined viewer and a tag-entry `QLineEdit` editor
([[plugins#field-toolkit]]).
"""

from typing import override

from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import QLabel, QLineEdit

from .field import Field, FieldBinding, FieldEditorWidgets, FieldViewerWidgets
from .text_list_string import TextListString


class TextListField(Field[list[str]]):
    """A ``text list`` field ([[plugins#field-toolkit]], [[field-schema#field-types]]): a comma-joined,
    deduplicated label viewer + a comma-separated ``QLineEdit`` tag-entry editor, live-bound to the
    binding. Covers ``authors``, ``advertised_tags``, ``extra_tags`` ([[field-schema#field-mapping]]).

    The echo guard compares the editor's own *parsed* text against the incoming value, not the raw
    text, so the editor is only overwritten when they actually differ -- a keystroke that round-trips
    through the model does not bounce back and reset the cursor.

    Deduplication is a **viewer-only** presentation rule (§17.4's "comma-joined for display,
    deduplicated") -- the editor round-trips the list as typed, duplicates included, so retyping a tag
    mid-entry never silently drops it.
    """

    TYPE = "text_list"

    @override
    def make_viewer(self, binding: FieldBinding[list[str]]) -> FieldViewerWidgets:
        label = QLabel(self.__display(binding.value))
        label.setWordWrap(True)
        self.bind_external(binding.changed, lambda value: label.setText(self.__display(value)))
        return FieldViewerWidgets(self.viewer_tab, self.make_label(), label)

    @override
    def make_editor(self, binding: FieldBinding[list[str]]) -> FieldEditorWidgets:
        line_edit = QLineEdit(TextListString.join(binding.value))
        line_edit.textChanged.connect(lambda text: binding.set_value(TextListString.split(text)))
        self.bind_external(binding.changed, lambda value: self.__echo(line_edit, value))
        return FieldEditorWidgets(self.editor_tab, self.make_label(), line_edit)

    def __display(self, items: list[str]) -> str:
        """Deduplicate (order-preserving) and join a list for the read-only viewer.

        :param items: the list to render.
        :returns: the deduplicated, comma-joined text.
        """
        return TextListString.join(dict.fromkeys(items))

    def __echo(self, line_edit: QLineEdit, value: list[str]) -> None:
        """Update the editor from a binding change without re-emitting ``textChanged`` (echo guard).

        :param line_edit: the editor to update.
        :param value: the new value.
        """
        if TextListString.split(line_edit.text()) != value:
            with QSignalBlocker(line_edit):
                line_edit.setText(TextListString.join(value))
