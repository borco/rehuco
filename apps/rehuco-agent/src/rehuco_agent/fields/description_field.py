"""The `description` field: a rendered-Markdown viewer over a `ScintillaEdit` editor that lives in its
own dock ([[plugins#field-toolkit]], [[plugins#viewer-editor-both]]).
"""

from typing import override

from borco_pyside.widgets import HorizontalLine
from PySide6.QtCore import QSignalBlocker
from pyside6_scintilla import ScintillaEdit

from rehuco_agent.fields.field import Field, FieldBinding, FieldEditorWidgets, FieldViewerWidgets
from rehuco_agent.fields.widgets import MarkdownView


class DescriptionField(Field[str]):
    """A ``description`` field ([[plugins#field-toolkit]], [[plugins#viewer-editor-both]]): the resource's
    Markdown prose. The **viewer** renders it (`MarkdownView`); the **editor** is a
    :class:`~pyside6_scintilla.ScintillaEdit` placed on its own editor tab, so it can be torn out and
    maximized while writing. Covers the common-core ``description``.
    """

    TYPE = "description"

    @override
    def make_viewer(self, binding: FieldBinding[str]) -> FieldViewerWidgets:
        viewer = MarkdownView()
        viewer.set_markdown(binding.value)
        binding.changed.connect(viewer.set_markdown)
        return FieldViewerWidgets(self.viewer_tab, HorizontalLine(), viewer, vertical=True)

    @override
    def make_editor(self, binding: FieldBinding[str]) -> FieldEditorWidgets:
        editor = ScintillaEdit()
        editor.setObjectName(self.name)
        editor.setText(binding.value)
        editor.notifyChange.connect(lambda *_: binding.set_value(self.__text(editor)))
        binding.changed.connect(lambda value: self.__echo(editor, value))
        # no label for the editor tab, since the tab itself is the label
        return FieldEditorWidgets(self.editor_tab, None, editor, vertical=True)

    @staticmethod
    def __text(editor: ScintillaEdit) -> str:
        """Read the editor's full text as a string.

        :param editor: the Scintilla editor.
        :returns: the editor's UTF-8 text.
        """
        return bytes(editor.getText(editor.length() + 1).data()).decode("utf-8")

    @staticmethod
    def __echo(editor: ScintillaEdit, value: str) -> None:
        """Update the editor from a binding change without re-emitting a change notification (echo guard).

        `ScintillaEdit.setText` also resets the caret, so echoing the editor's own edit back into it
        unguarded would move the caret on every keystroke -- the text-equality check avoids that.

        :param editor: the editor to update.
        :param value: the new value.
        """
        if DescriptionField.__text(editor) != value:
            with QSignalBlocker(editor):
                editor.setText(value)
