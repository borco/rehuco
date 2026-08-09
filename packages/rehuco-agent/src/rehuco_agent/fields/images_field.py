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
from .image_organizer import ImageOrganizer
from .image_scanner import ImageScanner
from .widgets import ImageSelector, ImageStrip
from .widgets.image_selector import PREVIEW_HEIGHT

IMAGE_STRIP_HEIGHT: Final = 150
"""The lightbox strip viewer's pixel height when its owner names none (#27). The user's own choice
reaches this field from the owner ("Viewers > Images", #161); the number lives next to the widget it
sizes, and the settings section reads it from here as its default."""


class ImagesField(Field[list[str]], QObject):  # pylint: disable=too-many-instance-attributes
    """The special ``images`` field ([[plugins#field-toolkit]], [[data-model#image-meanings]], #27): the
    resource's curated lightbox set.

    Its bound value is the list of **hidden** screenshot filenames -- the lightbox shows every screenshot
    sibling by default, so only the hidden exceptions are stored.

    **Viewer** -- an :class:`~rehuco_agent.fields.widgets.ImageStrip` of the *visible* screenshots (all
    siblings minus the hidden ones), fixed to :data:`IMAGE_STRIP_HEIGHT` and stacked full-width above the
    description.

    **Editor** -- an :class:`~rehuco_agent.fields.widgets.ImageSelector`: every screenshot as a checkable
    row (checked = visible) under a sized preview, on its own editor tab. That preview answers the
    app-wide previews toggle too (#71), so the keystroke that clears screenshots off screen clears
    them here as well. Given an ``image_organizer`` it also **rearranges** the set (#72): moving or
    deleting a screenshot renames files, since a resource's screenshot order is its numbering -- so
    those edits land on disk immediately rather than waiting for a Save, and the strip is sent back
    to the directory afterwards.

    :param name: the field's identifier on its model (the bound ``hidden_images`` list).
    :param image_scanner: resolves the resource's current screenshot siblings; seeds both widgets.
    :param image_scanner_changed: fires when ``image_scanner`` changes (e.g. a `.tc` -> `.rehu`
        conversion, [[acquisition-tooling#tc-to-rehu]]), forwarded into each widget's own scanner.
    :param image_organizer: rearranges the resource's screenshots on disk (#72); ``None`` leaves the
        curation editor read-only, with its move and delete buttons disabled.
    :param label: display label; derived from ``name`` when omitted.
    :param viewer_tab: the surface the strip lands on (keyword-only, required).
    :param editor_tab: the surface the curation editor lands on (keyword-only, required).
    :param strip_height: the strip's fixed pixel height (keyword-only); the owner passes the user's
        configured height, and :data:`IMAGE_STRIP_HEIGHT` stands in when it names none.
    :param strip_height_changed: fires with a new configured height, forwarded into the strip so an
        applied settings change resizes the one already on screen (keyword-only, #161) -- the same
        value-plus-its-signal shape ``image_scanner``/``image_scanner_changed`` already uses.
    :param strip_wrap: whether the strip wraps its thumbnails instead of keeping them on one row
        (keyword-only, #70); the owner passes the user's configured choice.
    :param strip_wrap_changed: fires with a new configured choice, forwarded into the strip so an
        applied settings change re-lays out the one already on screen (keyword-only, #70) -- the same
        shape as ``strip_height``/``strip_height_changed`` beside it.
    :param previews_visible: whether the strip and the editor's preview pane start out shown
        (keyword-only, #71, #72); the owner passes the grave-accent toggle's
        (``Ctrl+Shift+``, backtick) current state.
    :param previews_visible_changed: fires when that toggle changes, forwarded into the strip's own
        :meth:`~rehuco_agent.fields.widgets.image_strip.ImageStrip.set_requested_visible` and the
        selector's :meth:`~rehuco_agent.fields.widgets.image_selector.ImageSelector.set_previews_visible`,
        so every open document's screenshots hide or reappear together, editor included
        (keyword-only, #71, #72) -- the same value-plus-its-signal shape
        ``strip_wrap``/``strip_wrap_changed`` beside it uses.
    :param selector_preview_height: the curation editor's preview-pane height on a document with no
        split of its own remembered yet (keyword-only, #72); the owner passes the user's configured
        height, and :data:`~rehuco_agent.fields.widgets.image_selector.PREVIEW_HEIGHT` stands in.
    :param selector_preview_height_changed: fires with a new configured height, forwarded into the
        selector so an applied settings change re-splits the one already on screen (keyword-only,
        #72) -- the same shape as ``strip_height``/``strip_height_changed`` above.
    """

    TYPE = "images"

    image_activated: Signal = Signal(Path)
    """Fires with the screenshot a user clicked in the strip, for the **owner to open** (the
    `ImageActivator` contract, #160). Forwarded straight from the strip: this field decides nothing
    about the maximized surface, which is the owner's call and the user's setting."""

    screenshots_changed: Signal = Signal()
    """Fires when the curation editor's screenshot rows are rebuilt -- most importantly after it has
    *renamed* files to reorder or delete one (#72). The viewer's strip reads the same directory
    through its own scanner and has no way to notice that on its own, so this is what sends it back
    to disk instead of leaving it painting thumbnails under names that no longer exist."""

    curated_images_changed: Signal = Signal(list)
    """Fires with the resource's curated screenshot set ([[data-model#image-meanings]]) whenever it is
    rebuilt -- a curation edit here, or a scanner swap ([[acquisition-tooling#tc-to-rehu]]). The other
    half of the `ImageActivator` contract (#161): the activation names *where* to start, this keeps an
    already-open viewer on the same live set the strip itself shows."""

    # every argument is one value-plus-its-signal pair the owner has to pass through, and each is
    # simply stashed for whichever of the two widgets reads it -- there is no logic here to extract
    def __init__(  # pylint: disable=too-many-arguments,too-many-locals
        self,
        name: str,
        image_scanner: ImageScanner | None,
        image_scanner_changed: SignalInstance | None = None,
        image_organizer: ImageOrganizer | None = None,
        label: str | None = None,
        *,
        viewer_tab: FieldsTab,
        editor_tab: FieldsTab,
        strip_height: int = IMAGE_STRIP_HEIGHT,
        strip_height_changed: SignalInstance | None = None,
        strip_wrap: bool = False,
        strip_wrap_changed: SignalInstance | None = None,
        previews_visible: bool = True,
        previews_visible_changed: SignalInstance | None = None,
        selector_preview_height: int = PREVIEW_HEIGHT,
        selector_preview_height_changed: SignalInstance | None = None,
    ) -> None:
        super().__init__(name, label, viewer_tab=viewer_tab, editor_tab=editor_tab)
        self.__image_scanner: Final = image_scanner
        self.__image_scanner_changed: Final = image_scanner_changed
        self.__image_organizer: Final = image_organizer
        self.__strip_height: Final = strip_height
        self.__strip_height_changed: Final = strip_height_changed
        self.__strip_wrap: Final = strip_wrap
        self.__strip_wrap_changed: Final = strip_wrap_changed
        self.__previews_visible: Final = previews_visible
        self.__previews_visible_changed: Final = previews_visible_changed
        self.__selector_preview_height: Final = selector_preview_height
        self.__selector_preview_height_changed: Final = selector_preview_height_changed

    @override
    def make_viewer(self, binding: FieldBinding[list[str]]) -> FieldViewerWidgets:
        strip = ImageStrip(height=self.__strip_height, wrap=self.__strip_wrap)
        strip.set_requested_visible(self.__previews_visible)
        # wired before it is seeded, not after: seeding is itself a rebuild, and the owner needs that
        # first curated set as much as any later one -- it is what a thumbnail click opens against (#161)
        strip.image_activated.connect(self.image_activated)
        strip.images_changed.connect(self.curated_images_changed)
        strip.image_scanner = self.__image_scanner
        # bind_external, not a raw connect: this field outlives any one strip, so a form rebuild has
        # to be able to sever it -- the same reason the settings-driven bindings below use it
        self.bind_external(self.screenshots_changed, strip.refresh)  # type: ignore[arg-type]
        strip.set_hidden(binding.value)
        binding.changed.connect(strip.set_hidden)
        if self.__image_scanner_changed is not None:
            self.__image_scanner_changed.connect(strip.set_image_scanner)  # type: ignore[attr-defined]
        if self.__strip_height_changed is not None:
            # through bind_external, not a raw connect: the settings outlive this strip, so the owner
            # has to be able to sever it deterministically when a form rebuild destroys the widget
            self.bind_external(self.__strip_height_changed, strip.set_height)
        if self.__strip_wrap_changed is not None:
            # through bind_external for the same reason the height above is: the settings outlive the strip
            self.bind_external(self.__strip_wrap_changed, strip.set_wrap)
        if self.__previews_visible_changed is not None:
            # through bind_external for the same reason the two above are: the toggle outlives the strip
            self.bind_external(self.__previews_visible_changed, strip.set_requested_visible)
        # no label: the strip is a self-explanatory hero, stacked full-width above the description
        return FieldViewerWidgets(self.viewer_tab, None, strip, vertical=True)

    @override
    def make_editor(self, binding: FieldBinding[list[str]]) -> FieldEditorWidgets:
        selector = ImageSelector(preview_height=self.__selector_preview_height)
        selector.set_previews_visible(self.__previews_visible)
        selector.image_organizer = self.__image_organizer
        selector.setObjectName(self.name)
        selector.image_scanner = self.__image_scanner
        # the initial seed always builds, unlike set_hidden -- its echo-guard would otherwise skip
        # populating a brand-new, empty selector whenever the initial hidden list happens to be empty too
        selector.set_images(list(self.__image_scanner.files()) if self.__image_scanner else [], binding.value)
        selector.hidden_changed.connect(binding.set_value)
        # a rearrangement renames files, which no viewer over the same directory can see coming --
        # relayed through the field so the strip (and, through it, an open maximized viewer) re-reads
        # the disk rather than painting thumbnails from names that no longer exist (#72)
        selector.screenshots_changed.connect(self.screenshots_changed)
        binding.changed.connect(selector.set_hidden)
        if self.__image_scanner_changed is not None:
            self.__image_scanner_changed.connect(selector.set_image_scanner)  # type: ignore[attr-defined]
        if self.__selector_preview_height_changed is not None:
            # through bind_external for the same reason the strip's height is: the settings outlive
            # the selector, so a form rebuild has to be able to sever this deterministically
            self.bind_external(self.__selector_preview_height_changed, selector.set_preview_height)
        if self.__previews_visible_changed is not None:
            # the same toggle the viewer's strip answers, reaching the editor's preview pane too, so
            # one keystroke clears screenshots off screen everywhere rather than everywhere-but-here
            self.bind_external(self.__previews_visible_changed, selector.set_previews_visible)
        # no label for the editor tab, since the tab itself is the label; fills its dedicated tab
        return FieldEditorWidgets(self.editor_tab, None, selector, vertical=True, fill=True)
