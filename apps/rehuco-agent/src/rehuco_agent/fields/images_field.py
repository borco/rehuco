"""The special `images` field: a lightbox thumbnail strip viewer and a curation editor ([[plugins#field-toolkit]], #27).

Like the ``path`` field, this one is **model-aware** -- its widgets need the resource's screenshot
siblings on disk, which the toolkit's value binding cannot supply -- so its owner (`DocumentWidget`)
constructs it directly with an ``image_scanner`` rather than resolving it generically through the
field list. Its bound value is the list of *hidden* screenshot filenames ([[data-model#image-meanings]]).
Pure wiring only: `ImageStrip`/`ImageSelector` each hold their own `image_scanner` and know how to
re-fetch and rebuild themselves, so this field never touches a screenshot path list directly.
"""

from typing import TYPE_CHECKING, Final, override

from PySide6.QtCore import SignalInstance

from rehuco_agent.fields.field import Field, FieldBinding, FieldEditorWidgets, FieldsTab, FieldViewerWidgets
from rehuco_agent.fields.widgets import ImageSelector, ImageStrip

if TYPE_CHECKING:
    from rehuco_agent.documents.image_scanner import ImageScanner

IMAGE_STRIP_HEIGHT: Final = 150
"""The lightbox strip viewer's fixed pixel height (#27). A constant for now; a future preferences slice
makes it configurable in the settings ([[appendices.open-questions#still-open]])."""


class ImagesField(Field[list[str]]):
    """The special ``images`` field ([[plugins#field-toolkit]], [[data-model#image-meanings]], #27): the
    resource's curated lightbox set.

    Its bound value is the list of **hidden** screenshot filenames -- the lightbox shows every screenshot
    sibling by default, so only the hidden exceptions are stored.

    **Viewer** -- an :class:`~rehuco_agent.fields.widgets.ImageStrip` of the *visible* screenshots (all
    siblings minus the hidden ones), fixed to :data:`IMAGE_STRIP_HEIGHT` and stacked full-width above the
    description.

    **Editor** -- an :class:`~rehuco_agent.fields.widgets.ImageSelector`: every screenshot as a checkable
    row (checked = visible) beside a sized preview, on its own editor tab.

    :param name: the field's identifier on its model (the bound ``hidden_images`` list).
    :param image_scanner: resolves the resource's current screenshot siblings; seeds both widgets.
    :param image_scanner_changed: fires when ``image_scanner`` changes (e.g. a `.tc` -> `.rehu`
        conversion, [[acquisition-tooling#tc-to-rehu]]), forwarded into each widget's own scanner.
    :param label: display label; derived from ``name`` when omitted.
    :param viewer_tab: the surface the strip lands on (keyword-only, required).
    :param editor_tab: the surface the curation editor lands on (keyword-only, required).
    """

    TYPE = "images"

    def __init__(  # pylint: disable=too-many-arguments
        self,
        name: str,
        image_scanner: ImageScanner | None,
        image_scanner_changed: SignalInstance | None = None,
        label: str | None = None,
        *,
        viewer_tab: FieldsTab,
        editor_tab: FieldsTab,
    ) -> None:
        super().__init__(name, label, viewer_tab=viewer_tab, editor_tab=editor_tab)
        self.__image_scanner: Final = image_scanner
        self.__image_scanner_changed: Final = image_scanner_changed

    @override
    def make_viewer(self, binding: FieldBinding[list[str]]) -> FieldViewerWidgets:
        strip = ImageStrip(height=IMAGE_STRIP_HEIGHT)
        strip.image_scanner = self.__image_scanner
        strip.set_hidden(binding.value)
        binding.changed.connect(strip.set_hidden)
        if self.__image_scanner_changed is not None:
            self.__image_scanner_changed.connect(strip.set_image_scanner)  # type: ignore[attr-defined]
        # no label: the strip is a self-explanatory hero, stacked full-width above the description
        return FieldViewerWidgets(self.viewer_tab, None, strip, vertical=True)

    @override
    def make_editor(self, binding: FieldBinding[list[str]]) -> FieldEditorWidgets:
        selector = ImageSelector()
        selector.setObjectName(self.name)
        selector.image_scanner = self.__image_scanner
        # the initial seed always builds, unlike set_hidden -- its echo-guard would otherwise skip
        # populating a brand-new, empty selector whenever the initial hidden list happens to be empty too
        selector.set_images(list(self.__image_scanner.files()) if self.__image_scanner else [], binding.value)
        selector.hidden_changed.connect(binding.set_value)
        binding.changed.connect(selector.set_hidden)
        if self.__image_scanner_changed is not None:
            self.__image_scanner_changed.connect(selector.set_image_scanner)  # type: ignore[attr-defined]
        # no label for the editor tab, since the tab itself is the label; fills its dedicated tab
        return FieldEditorWidgets(self.editor_tab, None, selector, vertical=True, fill=True)
