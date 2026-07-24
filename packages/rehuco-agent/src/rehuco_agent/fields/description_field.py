"""The `description` field: a rendered-Markdown viewer over a `MarkdownEdit` editor that lives in its
own dock ([[plugins#field-toolkit]], [[plugins#viewer-editor-both]]).
"""

from typing import Final, Protocol, override

from borco_pyside.widgets import HorizontalLine
from PySide6.QtCore import QSignalBlocker, SignalInstance

from .field import Field, FieldBinding, FieldEditorWidgets, FieldsTab, FieldViewerWidgets
from .image_scanner import ImageScanner
from .widgets import MarkdownEdit, MarkdownView


class DescriptionRenderingSettings(Protocol):
    """The live Markdown-rendering settings a `DescriptionField` viewer follows (#26, #47).

    Engine-agnostic on purpose: the viewer reads the *effective* renderer and stylesheet and re-renders
    on one aggregate signal, never touching the per-engine stylesheet storage or the image-width cap
    directly -- so adding a third rendering engine (or another render-affecting setting) doesn't force
    this contract to grow. The toolkit owns it; the app's settings layer implements it
    (``settings.markdown_rendering_settings.MarkdownRenderingSettings``), so the field stays
    settings-agnostic -- the same inversion the toolkit applies to its model binding (`FieldModel`) and
    its image scanning (`ImageScanner`). The owner injects the shared, process-wide instance
    (`document_fields.build_document_form`) rather than the field reaching for an app singleton.
    """

    @property
    def engine(self) -> str:
        """The selected renderer -- a key of ``markdown_view.RENDERERS``."""
        ...  # pylint: disable=unnecessary-ellipsis

    @property
    def css(self) -> str:
        """The stylesheet for the currently-selected :attr:`engine`."""
        ...  # pylint: disable=unnecessary-ellipsis

    @property
    def description_rendering_changed(self) -> SignalInstance:
        """Fires when the :attr:`engine`, the active stylesheet (:attr:`css`), or the image-width cap
        changes -- i.e. whenever an already-open viewer needs to re-render. The width cap is a
        re-render trigger only (the scanner reads it live), never read through this contract."""
        ...  # pylint: disable=unnecessary-ellipsis


class DescriptionField(Field[str]):
    """A ``description`` field ([[plugins#field-toolkit]], [[plugins#viewer-editor-both]]): the resource's
    Markdown prose. The **viewer** renders it (`MarkdownView`); the **editor** is a `MarkdownEdit`
    placed on its own editor tab, so it can be torn out and maximized while writing. Covers the
    common-core ``description``.

    Model-aware like `PathField`/`ImagesField`: an ``image_scanner`` resolves the description's
    embedded ``![...](...)`` references against the resource's own directory
    ([[data-model#image-meanings]]), independent of process CWD -- so it is constructed directly by
    its owner (`document_fields.build_document_form`), not resolved generically through the field list.

    :param name: the field's identifier on its model.
    :param label: display label; derived from ``name`` when omitted.
    :param image_scanner: resolves the description's embedded images for the viewer, and this
        resource's own image filenames offered by the editor's autocomplete (#74); omit for a
        viewer/editor that can't resolve any (e.g. a bare, model-less instance in isolation/tests).
    :param image_scanner_changed: fires when ``image_scanner`` changes (e.g. a `.tc` -> `.rehu`
        conversion, [[acquisition-tooling#tc-to-rehu]]), so the viewer and editor can pick up the
        new scanner.
    :param rendering_settings: the shared, live-reactive Markdown-rendering settings the viewer seeds
        from and re-renders on (#26, #47), injected by the owner rather than reached for directly;
        omit for a bare viewer that renders with the defaults and does not follow settings changes.
    """

    TYPE = "description"

    def __init__(  # pylint: disable=too-many-arguments
        self,
        name: str,
        label: str | None = None,
        image_scanner: ImageScanner | None = None,
        image_scanner_changed: SignalInstance | None = None,
        *,
        rendering_settings: DescriptionRenderingSettings | None = None,
        viewer_tab: FieldsTab,
        editor_tab: FieldsTab,
    ) -> None:
        super().__init__(name, label, viewer_tab=viewer_tab, editor_tab=editor_tab)
        self.__image_scanner: Final = image_scanner
        self.__image_scanner_changed: Final = image_scanner_changed
        self.__rendering_settings: Final = rendering_settings

    @override
    def make_viewer(self, binding: FieldBinding[str]) -> FieldViewerWidgets:
        settings = self.__rendering_settings
        if settings is None:
            viewer = MarkdownView(image_scanner=self.__image_scanner)
        else:
            viewer = MarkdownView(
                image_scanner=self.__image_scanner,
                engine=settings.engine,
                css=settings.css,
            )
        viewer.set_markdown(binding.value)
        binding.changed.connect(viewer.set_markdown)
        if self.__image_scanner_changed is not None:
            self.__image_scanner_changed.connect(viewer.set_image_scanner)  # type: ignore[attr-defined]
        if settings is not None:
            self.__wire_rendering_settings(viewer, settings)
        # not fill: in the viewer the description is one row among others (the unknown-field fallbacks
        # follow it), so it keeps its natural height and the trailing stretch sits after them all --
        # unlike the editor, where the description has its own tab and should take the whole height
        return FieldViewerWidgets(self.viewer_tab, HorizontalLine(), viewer, vertical=True)

    def __wire_rendering_settings(self, viewer: MarkdownView, settings: DescriptionRenderingSettings) -> None:
        """Re-render ``viewer`` with the shared Markdown-rendering settings' current values whenever
        they change (#26, #47) -- so a Save on the settings page updates an already-open viewer
        immediately, not just newly-opened ones. One binding to the settings' aggregate
        ``description_rendering_changed`` covers the engine, the active stylesheet, and the image-width
        cap at once; the field re-renders wholesale, so it never needs to know which of them moved.

        The image-width cap is covered by re-rendering alone even though it isn't threaded through
        :meth:`MarkdownView.apply_rendering_settings` -- the ``ImageScanner`` reads the live setting
        itself on each ``loadResource`` call, so re-rendering (which re-triggers ``loadResource`` per
        image) is all an already-open viewer needs to pick it up.

        :param viewer: the viewer to keep in sync.
        :param settings: the shared, live-reactive settings to follow.
        """

        def apply_current_settings(*_args: object) -> None:
            viewer.apply_rendering_settings(engine=settings.engine, css=settings.css)

        # the settings are an app-wide singleton, far longer-lived than this viewer -- so route this
        # through bind_external, which the form clears on a rebuild/destroy, rather than a raw connect
        # that would fire into a deleted viewer
        self.bind_external(settings.description_rendering_changed, apply_current_settings)

    @override
    def make_editor(self, binding: FieldBinding[str]) -> FieldEditorWidgets:
        editor = MarkdownEdit(image_scanner=self.__image_scanner)
        editor.setObjectName(self.name)
        editor.setText(binding.value)
        editor.notifyChange.connect(lambda *_: binding.set_value(self.__text(editor)))
        self.bind_external(binding.changed, lambda value: self.__echo(editor, value))
        if self.__image_scanner_changed is not None:
            self.__image_scanner_changed.connect(editor.set_image_scanner)  # type: ignore[attr-defined]
        # no label for the editor tab, since the tab itself is the label
        return FieldEditorWidgets(self.editor_tab, None, editor, vertical=True, fill=True)

    @staticmethod
    def __text(editor: MarkdownEdit) -> str:
        """Read the editor's full text as a string.

        :param editor: the Scintilla editor.
        :returns: the editor's UTF-8 text.
        """
        return bytes(editor.getText(editor.length() + 1).data()).decode("utf-8")

    @staticmethod
    def __echo(editor: MarkdownEdit, value: str) -> None:
        """Update the editor from a binding change without re-emitting a change notification (echo guard).

        `ScintillaEdit.setText` also resets the caret, so echoing the editor's own edit back into it
        unguarded would move the caret on every keystroke -- the text-equality check avoids that.

        :param editor: the editor to update.
        :param value: the new value.
        """
        if DescriptionField.__text(editor) != value:
            with QSignalBlocker(editor):
                editor.setText(value)
