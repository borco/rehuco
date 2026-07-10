"""The special `images` field: a lightbox thumbnail strip viewer and a curation editor ([[plugins#field-toolkit]], #27).

Like the ``path`` field, this one is **model-aware** -- its widgets need the resource's screenshot
siblings on disk, which the toolkit's value binding cannot supply -- so its owner (`DocumentWidget`)
constructs it directly with an ``image_files`` callback rather than resolving it generically through the
field list. Its bound value is the list of *hidden* screenshot filenames ([[data-model#image-meanings]]).
"""

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final, override

from rehuco_agent.fields.field import Field, FieldBinding, FieldEditorWidgets, FieldsTab, FieldViewerWidgets
from rehuco_agent.fields.widgets import ImageSelector, ImageStrip

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
    :param image_files: called with no arguments for the resource's current screenshot sibling paths.
    :param label: display label; derived from ``name`` when omitted.
    :param viewer_tab: the surface the strip lands on (keyword-only, required).
    :param editor_tab: the surface the curation editor lands on (keyword-only, required).
    """

    TYPE = "images"

    def __init__(
        self,
        name: str,
        image_files: Callable[[], Sequence[Path]],
        label: str | None = None,
        *,
        viewer_tab: FieldsTab,
        editor_tab: FieldsTab,
    ) -> None:
        super().__init__(name, label, viewer_tab=viewer_tab, editor_tab=editor_tab)
        self.__image_files: Final = image_files

    @override
    def make_viewer(self, binding: FieldBinding[list[str]]) -> FieldViewerWidgets:
        strip = ImageStrip(height=IMAGE_STRIP_HEIGHT)
        self.__fill_strip(strip, binding.value)
        binding.changed.connect(lambda hidden: self.__fill_strip(strip, hidden))
        # no label: the strip is a self-explanatory hero, stacked full-width above the description
        return FieldViewerWidgets(self.viewer_tab, None, strip, vertical=True)

    @override
    def make_editor(self, binding: FieldBinding[list[str]]) -> FieldEditorWidgets:
        selector = ImageSelector()
        selector.setObjectName(self.name)
        selector.set_images(list(self.__image_files()), binding.value)
        selector.hidden_changed.connect(binding.set_value)
        binding.changed.connect(lambda hidden: self.__resync_selector(selector, hidden))
        # no label for the editor tab, since the tab itself is the label
        return FieldEditorWidgets(self.editor_tab, None, selector, vertical=True)

    def __fill_strip(self, strip: ImageStrip, hidden: list[str]) -> None:
        """Show the visible screenshots (all siblings minus ``hidden``) in the strip.

        :param strip: the strip to fill.
        :param hidden: the filenames curated out of the lightbox.
        """
        hidden_names = set(hidden)
        strip.set_images([path for path in self.__image_files() if path.name not in hidden_names])

    def __resync_selector(self, selector: ImageSelector, hidden: list[str]) -> None:
        """Reseed the editor from an *external* hidden-list change (e.g. a revert), skipping its own edits.

        The editor's own toggle already wrote ``hidden`` through the binding, which echoes back here; a
        rebuild in that case would needlessly reset the selection, so it is skipped when the value already
        matches what the selector shows.

        :param selector: the curation editor to reseed.
        :param hidden: the new hidden-filenames list.
        """
        if hidden == selector.hidden_filenames():
            return
        selector.set_images(list(self.__image_files()), hidden)
