"""The `description` field: a rendered-Markdown viewer over a `ScintillaEdit` editor that lives in its
own dock ([[plugins#field-toolkit]], [[plugins#viewer-editor-both]]).
"""

from typing import TYPE_CHECKING, Final, override

from borco_pyside.widgets import HorizontalLine
from PySide6.QtCore import QSignalBlocker
from pyside6_scintilla import ScintillaEdit

from rehuco_agent.fields.field import Field, FieldBinding, FieldEditorWidgets, FieldsTab, FieldViewerWidgets
from rehuco_agent.fields.widgets import MarkdownView
from rehuco_agent.settings.markdown_rendering_settings import (
    MarkdownRenderingSettings,
    shared_markdown_rendering_settings,
)

if TYPE_CHECKING:
    from rehuco_agent.documents.image_scanner import ImageScanner


class DescriptionField(Field[str]):
    """A ``description`` field ([[plugins#field-toolkit]], [[plugins#viewer-editor-both]]): the resource's
    Markdown prose. The **viewer** renders it (`MarkdownView`); the **editor** is a
    :class:`~pyside6_scintilla.ScintillaEdit` placed on its own editor tab, so it can be torn out and
    maximized while writing. Covers the common-core ``description``.

    Model-aware like `PathField`/`ImagesField`: an ``image_scanner`` resolves the description's
    embedded ``![...](...)`` references against the resource's own directory
    ([[data-model#image-meanings]]), independent of process CWD -- so it is constructed directly by
    its owner (`document_fields.build_document_form`), not resolved generically through the field list.

    :param name: the field's identifier on its model.
    :param label: display label; derived from ``name`` when omitted.
    :param image_scanner: resolves the description's embedded images; omit for a viewer that can't
        resolve any (e.g. a bare, model-less instance in isolation/tests).
    """

    TYPE = "description"

    def __init__(
        self,
        name: str,
        label: str | None = None,
        image_scanner: ImageScanner | None = None,
        *,
        viewer_tab: FieldsTab,
        editor_tab: FieldsTab,
    ) -> None:
        super().__init__(name, label, viewer_tab=viewer_tab, editor_tab=editor_tab)
        self.__image_scanner: Final = image_scanner

    @override
    def make_viewer(self, binding: FieldBinding[str]) -> FieldViewerWidgets:
        settings = shared_markdown_rendering_settings()
        viewer = MarkdownView(
            image_scanner=self.__image_scanner,
            engine=settings.engine,
            css=settings.css_for_current_engine(),
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

        ``max_image_width_changed`` still triggers a re-render even though it's no longer threaded
        through :meth:`MarkdownView.apply_rendering_settings` explicitly -- the ``ImageScanner`` reads
        the live setting itself on each ``loadResource`` call, so re-rendering (which re-triggers
        ``loadResource`` per image) is all that's needed for an already-open viewer to pick it up.

        :param viewer: the viewer to keep in sync.
        :param settings: the shared, live-reactive settings instance to follow.
        """

        def apply_current_settings(*_args: object) -> None:
            viewer.apply_rendering_settings(engine=settings.engine, css=settings.css_for_current_engine())

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
