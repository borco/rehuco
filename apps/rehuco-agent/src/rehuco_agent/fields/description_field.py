"""The `description` field: a rendered-Markdown viewer over a `ScintillaEdit` editor that lives in its
own dock ([[plugins#field-toolkit]], [[plugins#viewer-editor-both]]).
"""

from typing import override

from borco_pyside.widgets import HorizontalLine
from PySide6.QtCore import QSignalBlocker
from pyside6_scintilla import ScintillaEdit

from rehuco_agent.fields.field import Field, FieldBinding, FieldEditorWidgets, FieldViewerWidgets
from rehuco_agent.fields.widgets import MarkdownView
from rehuco_agent.settings.markdown_rendering_settings import (
    MarkdownRenderingSettings,
    shared_markdown_rendering_settings,
)


class DescriptionField(Field[str]):
    """A ``description`` field ([[plugins#field-toolkit]], [[plugins#viewer-editor-both]]): the resource's
    Markdown prose. The **viewer** renders it (`MarkdownView`); the **editor** is a
    :class:`~pyside6_scintilla.ScintillaEdit` placed on its own editor tab, so it can be torn out and
    maximized while writing. Covers the common-core ``description``.
    """

    TYPE = "description"

    @override
    def make_viewer(self, binding: FieldBinding[str]) -> FieldViewerWidgets:
        settings = shared_markdown_rendering_settings()
        viewer = MarkdownView(
            engine=settings.engine,
            css=settings.css_for_current_engine(),
            max_image_width=settings.max_image_width,
        )
        viewer.set_markdown(binding.value)
        binding.changed.connect(viewer.set_markdown)
        self.__wire_rendering_settings(viewer, settings)
        # not fill: in the viewer the description is one row among others (the unknown-field fallbacks
        # follow it), so it keeps its natural height and the trailing stretch sits after them all --
        # unlike the editor, where the description has its own tab and should take the whole height
        return FieldViewerWidgets(self.viewer_tab, HorizontalLine(), viewer, vertical=True)

    @staticmethod
    def __wire_rendering_settings(viewer: MarkdownView, settings: MarkdownRenderingSettings) -> None:
        """Re-render ``viewer`` with the shared Markdown-rendering settings' current values whenever
        any of them changes (#26, #47) -- so a Save on the settings page updates an already-open
        viewer immediately, not just newly-opened ones.

        :param viewer: the viewer to keep in sync.
        :param settings: the shared, live-reactive settings instance to follow.
        """

        def apply_current_settings(*_args: object) -> None:
            viewer.apply_rendering_settings(
                engine=settings.engine,
                css=settings.css_for_current_engine(),
                max_image_width=settings.max_image_width,
            )

        settings.engine_changed.connect(apply_current_settings)
        settings.markdown_css_changed.connect(apply_current_settings)
        settings.mistletoe_css_changed.connect(apply_current_settings)
        settings.max_image_width_changed.connect(apply_current_settings)

    @override
    def make_editor(self, binding: FieldBinding[str]) -> FieldEditorWidgets:
        editor = ScintillaEdit()
        editor.setObjectName(self.name)
        editor.setText(binding.value)
        editor.notifyChange.connect(lambda *_: binding.set_value(self.__text(editor)))
        binding.changed.connect(lambda value: self.__echo(editor, value))
        # no label for the editor tab, since the tab itself is the label
        return FieldEditorWidgets(self.editor_tab, None, editor, vertical=True, fill=True)

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
