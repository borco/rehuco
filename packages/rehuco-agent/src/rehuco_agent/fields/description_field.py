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
    def engine(self) -> str:  # pyright: ignore[reportReturnType]
        """The selected renderer -- a key of ``markdown_view.RENDERERS``."""

    @property
    def css(self) -> str:  # pyright: ignore[reportReturnType]
        """The stylesheet for the currently-selected :attr:`engine`."""

    @property
    def description_rendering_changed(self) -> SignalInstance:  # pyright: ignore[reportReturnType]
        """Fires when the :attr:`engine`, the active stylesheet (:attr:`css`), or the image-width cap
        changes -- i.e. whenever an already-open viewer needs to re-render. The width cap is a
        re-render trigger only (the scanner reads it live), never read through this contract."""


class DescriptionEditorViewSettings(Protocol):
    """The live description-editor settings a `DescriptionField` editor follows (#69): line
    numbers, line endings, wrap long lines.

    Mirrors `DescriptionRenderingSettings`'s inversion exactly: the toolkit only ever sees three
    booleans and one aggregate change signal, never the app's settings storage -- a newly-built
    editor seeds from the current values, and every already-open editor re-applies them wholesale
    whenever the signal fires, so a Save on the settings page restyles all open documents at once.
    The app's settings layer implements it
    (``settings.description_editor_settings.DescriptionEditorSettings``), and the owner injects the
    shared, process-wide instance (`document_fields.build_document_form`).
    """

    @property
    def show_line_numbers(self) -> bool:  # pyright: ignore[reportReturnType]
        """Whether the editor shows its line-number margin."""

    @property
    def show_line_endings(self) -> bool:  # pyright: ignore[reportReturnType]
        """Whether the editor draws a visible end-of-line glyph."""

    @property
    def wrap_long_lines(self) -> bool:  # pyright: ignore[reportReturnType]
        """Whether the editor wraps long lines instead of scrolling horizontally."""

    @property
    def description_editor_changed(self) -> SignalInstance:  # pyright: ignore[reportReturnType]
        """Fires when any of the three settings changes -- i.e. whenever an already-open editor
        needs to re-apply them."""


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
    :param editor_settings: the shared, live-reactive description-editor settings (#69) the editor
        seeds from and re-applies on, injected by the owner rather than reached for directly; omit
        for a bare editor that starts with `MarkdownEdit`'s own defaults and does not follow
        settings changes.
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
        editor_settings: DescriptionEditorViewSettings | None = None,
        viewer_tab: FieldsTab,
        editor_tab: FieldsTab,
    ) -> None:
        super().__init__(name, label, viewer_tab=viewer_tab, editor_tab=editor_tab)
        self.__image_scanner: Final = image_scanner
        self.__image_scanner_changed: Final = image_scanner_changed
        self.__rendering_settings: Final = rendering_settings
        self.__editor_settings: Final = editor_settings

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
        settings = self.__editor_settings
        if settings is None:
            editor = MarkdownEdit(image_scanner=self.__image_scanner)
        else:
            editor = MarkdownEdit(
                image_scanner=self.__image_scanner,
                line_numbers=settings.show_line_numbers,
                line_endings_visible=settings.show_line_endings,
                wrap_long_lines=settings.wrap_long_lines,
            )
        editor.setObjectName(self.name)
        editor.setText(binding.value)
        editor.notifyChange.connect(lambda *_: binding.set_value(self.__text(editor)))
        self.bind_external(binding.changed, lambda value: self.__echo(editor, value))
        if self.__image_scanner_changed is not None:
            self.__image_scanner_changed.connect(editor.set_image_scanner)  # type: ignore[attr-defined]
        if settings is not None:
            self.__wire_editor_settings(editor, settings)
        # no label for the editor tab, since the tab itself is the label
        return FieldEditorWidgets(self.editor_tab, None, editor, vertical=True, fill=True)

    def __wire_editor_settings(self, editor: MarkdownEdit, settings: DescriptionEditorViewSettings) -> None:
        """Re-apply the shared description-editor settings' current values to ``editor`` whenever
        they change (#69) -- so a Save on the settings page restyles an already-open editor
        immediately, not just newly-opened ones. One binding to the settings' aggregate
        ``description_editor_changed`` covers all three toggles at once; the editor re-applies them
        wholesale (each `MarkdownEdit` property setter is a no-op for an unchanged value), so it
        never needs to know which of them moved -- :meth:`__wire_rendering_settings`'s exact shape.

        :param editor: the editor to keep in sync.
        :param settings: the shared, live-reactive settings to follow.
        """

        def apply_current_settings(*_args: object) -> None:
            editor.line_numbers = settings.show_line_numbers
            editor.line_endings_visible = settings.show_line_endings
            editor.wrap_long_lines = settings.wrap_long_lines

        # the settings are an app-wide singleton, far longer-lived than this editor -- so route this
        # through bind_external, which the form clears on a rebuild/destroy, rather than a raw connect
        # that would fire into a deleted editor
        self.bind_external(settings.description_editor_changed, apply_current_settings)

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
