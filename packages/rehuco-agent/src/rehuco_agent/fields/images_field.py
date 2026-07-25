"""The special `images` field: a lightbox thumbnail strip viewer and a curation editor ([[plugins#field-toolkit]], #27).

Like the ``path`` field, this one is **model-aware** -- its widgets need the resource's screenshot
siblings on disk, which the toolkit's value binding cannot supply -- so its owner (`DocumentWidget`)
constructs it directly with an ``image_scanner`` rather than resolving it generically through the
field list. Its bound value is the list of *hidden* screenshot filenames ([[data-model#image-meanings]]).
Pure wiring only: `ImageStrip`/`ImageSelector` each hold their own `image_scanner` and know how to
re-fetch and rebuild themselves, so this field never touches a screenshot path list directly.
"""

from pathlib import Path
from typing import Final, override

from PySide6.QtCore import QObject, Signal, SignalInstance

from .field import Field, FieldBinding, FieldEditorWidgets, FieldsTab, FieldViewerWidgets
from .image_scanner import ImageScanner
from .widgets import ImageSelector, ImageStrip

IMAGE_STRIP_HEIGHT: Final = 150
"""The lightbox strip viewer's pixel height when its owner names none (#27). The user's own choice
reaches this field from the owner ("Viewers > Images", #161); the number lives next to the widget it
sizes, and the settings section reads it from here as its default."""


class ImagesField(Field[list[str]], QObject):
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
    :param strip_height: the strip's fixed pixel height (keyword-only); the owner passes the user's
        configured height, and :data:`IMAGE_STRIP_HEIGHT` stands in when it names none.
    :param strip_height_changed: fires with a new configured height, forwarded into the strip so an
        applied settings change resizes the one already on screen (keyword-only, #161) -- the same
        value-plus-its-signal shape ``image_scanner``/``image_scanner_changed`` already uses.
    """

    TYPE = "images"

    image_activated: Signal = Signal(Path)
    """Fires with the screenshot a user clicked in the strip, for the **owner to open** (the
    `ImageActivator` contract, #160). Forwarded straight from the strip: this field decides nothing
    about the maximized surface, which is the owner's call and the user's setting."""

    curated_images_changed: Signal = Signal(list)
    """Fires with the resource's curated screenshot set ([[data-model#image-meanings]]) whenever it is
    rebuilt -- a curation edit here, or a scanner swap ([[acquisition-tooling#tc-to-rehu]]). The other
    half of the `ImageActivator` contract (#161): the activation names *where* to start, this keeps an
    already-open viewer on the same live set the strip itself shows."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        name: str,
        image_scanner: ImageScanner | None,
        image_scanner_changed: SignalInstance | None = None,
        label: str | None = None,
        *,
        viewer_tab: FieldsTab,
        editor_tab: FieldsTab,
        strip_height: int = IMAGE_STRIP_HEIGHT,
        strip_height_changed: SignalInstance | None = None,
    ) -> None:
        super().__init__(name, label, viewer_tab=viewer_tab, editor_tab=editor_tab)
        self.__image_scanner: Final = image_scanner
        self.__image_scanner_changed: Final = image_scanner_changed
        self.__strip_height: Final = strip_height
        self.__strip_height_changed: Final = strip_height_changed

    @override
    def make_viewer(self, binding: FieldBinding[list[str]]) -> FieldViewerWidgets:
        strip = ImageStrip(height=self.__strip_height)
        # wired before it is seeded, not after: seeding is itself a rebuild, and the owner needs that
        # first curated set as much as any later one -- it is what a thumbnail click opens against (#161)
        strip.image_activated.connect(self.image_activated)
        strip.images_changed.connect(self.curated_images_changed)
        strip.image_scanner = self.__image_scanner
        strip.set_hidden(binding.value)
        binding.changed.connect(strip.set_hidden)
        if self.__image_scanner_changed is not None:
            self.__image_scanner_changed.connect(strip.set_image_scanner)  # type: ignore[attr-defined]
        if self.__strip_height_changed is not None:
            # through bind_external, not a raw connect: the settings outlive this strip, so the owner
            # has to be able to sever it deterministically when a form rebuild destroys the widget
            self.bind_external(self.__strip_height_changed, strip.set_height)
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
