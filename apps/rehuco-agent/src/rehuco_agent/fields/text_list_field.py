"""The `text list` leaf field: a deduplicated comma-joined viewer and a tag-entry `QLineEdit` editor
([[plugins#field-toolkit]]).
"""

from typing import Final, override

from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import QLabel, QLineEdit

from .field import Field, FieldBinding, FieldEditorWidgets, FieldViewerWidgets


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

    JOIN_SEPARATOR: Final = ", "
    SPLIT_SEPARATOR: Final = ","

    @override
    def make_viewer(self, binding: FieldBinding[list[str]]) -> FieldViewerWidgets:
        label = QLabel(self.__display(binding.value))
        label.setWordWrap(True)
        self.bind_external(binding.changed, lambda value: label.setText(self.__display(value)))
        return FieldViewerWidgets(self.viewer_tab, self.make_label(), label)

    @override
    def make_editor(self, binding: FieldBinding[list[str]]) -> FieldEditorWidgets:
        line_edit = QLineEdit(self.__join(binding.value))
        line_edit.textChanged.connect(lambda text: binding.set_value(self.__split(text)))
        self.bind_external(binding.changed, lambda value: self.__echo(line_edit, value))
        return FieldEditorWidgets(self.editor_tab, self.make_label(), line_edit)

    def __display(self, items: list[str]) -> str:
        """Deduplicate (order-preserving) and join a list for the read-only viewer.

        :param items: the list to render.
        :returns: the deduplicated, comma-joined text.
        """
        return self.__join(list(dict.fromkeys(items)))

    def __join(self, items: list[str]) -> str:
        """Join a list into its comma-separated text form.

        :param items: the list to join.
        :returns: the joined text.
        """
        return self.JOIN_SEPARATOR.join(items)

    def __split(self, text: str) -> list[str]:
        """Split comma-separated text into a list, trimming whitespace and dropping empty entries.

        :param text: the text to split.
        :returns: the parsed list.
        """
        return [item.strip() for item in text.split(self.SPLIT_SEPARATOR) if item.strip()]

    def __echo(self, line_edit: QLineEdit, value: list[str]) -> None:
        """Update the editor from a binding change without re-emitting ``textChanged`` (echo guard).

        :param line_edit: the editor to update.
        :param value: the new value.
        """
        if self.__split(line_edit.text()) != value:
            with QSignalBlocker(line_edit):
                line_edit.setText(self.__join(value))
