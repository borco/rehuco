"""Images / Display settings page: how a screenshot is shown, not what counts as one (#294)."""

from typing import Final, NamedTuple

from PySide6.QtWidgets import QRadioButton, QWidget

from ...fields.widgets.image_lightbox import ImageViewerMode
from ..image_viewer_settings import DEFAULT_MODE, shared_image_viewer_settings
from ..markdown_rendering_settings import shared_markdown_rendering_settings
from ..persistent_settings import persistent_settings
from .images_display_page_ui import Ui_ImagesDisplayPage


class ImageChoices(NamedTuple):
    """Every choice this page holds, in one comparable value ([[appendices.settings-pages#save-drop-actions]]).

    Named rather than a bare tuple because the page compares the staged set against the saved one
    wholesale (:meth:`ImagesDisplayPage.is_dirty`) *and* writes each member individually, and six
    positional booleans and ints of the same types are exactly where a swapped pair would go unnoticed.

    :param mode: which surface a maximized screenshot opens on.
    :param strip_visible: whether a maximized viewer starts with its thumbnail row shown.
    :param preview_wrap: whether a document's own image strip wraps its thumbnails (#70).
    :param preview_height: how tall a screenshot is in a document's own image strip.
    :param lightbox_height: how tall a screenshot is in the maximized viewer's own thumbnail row.
    :param editor_preview_height: how tall the images editor's preview pane opens (#72).
    """

    mode: ImageViewerMode
    strip_visible: bool
    preview_wrap: bool
    preview_height: int
    lightbox_height: int
    editor_preview_height: int


class ImagesDisplayPage(QWidget):
    """How an image is shown -- the surface a maximized screenshot opens on, a document's own strip,
    the three thumbnail heights, and the width cap on an image embedded in a description (#160, #161,
    #70, #72, #294).

    A sibling of `ImagesFilesPage` under the "Images" group: this half answers how an image is
    *displayed*, that one what counts as one and what happens to its file on disk (#294). Two settings
    objects meet here:

    - `ImageViewerSettings` -- the maximized viewer's surface, whether it starts with its thumbnail
      strip shown, whether a document's own strip wraps, the thumbnail heights either side, and how
      tall the curation editor's preview pane opens (#72) (:class:`ImageChoices`, compared wholesale).
    - `MarkdownRenderingSettings` -- the width cap on an image embedded in a description. Only this
      one field, not the engine or its CSS, which stay on `DescriptionsPage` where the question is
      how a description *renders* rather than how an image is sized.

    Everything is staged in the widgets until :meth:`save_changes` writes each object and persists it.
    The width cap is the one value with a live effect: it relays into
    ``MarkdownRenderingSettings.description_rendering_changed``, so every open viewer re-renders on
    Save -- the wiring for that lives at the settings end, so this page still drives none of its own.

    The strip toggle here is the *starting point* only: a document remembers the strip it was last
    left showing, in its own saved layout, so toggling one inside a viewer never comes back here (#161).

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_ImagesDisplayPage()
        self.__ui.setupUi(self)
        self.__buttons: Final[dict[ImageViewerMode, QRadioButton]] = {
            ImageViewerMode.DOCUMENT_OVERLAY: self.__ui.document_overlay_radio_button,
            ImageViewerMode.APP_WINDOW_OVERLAY: self.__ui.app_window_overlay_radio_button,
            ImageViewerMode.FULL_SCREEN: self.__ui.full_screen_radio_button,
        }
        self.drop_changes()

    def is_dirty(self) -> bool:
        """Whether any staged choice differs from what its own settings object currently holds."""
        return (
            self.__staged() != self.__saved()
            or self.__ui.max_image_width_spin_box.value() != shared_markdown_rendering_settings().max_image_width
        )

    def save_changes(self) -> None:
        """Push every staged choice into its settings object and persist it.

        Two objects, saved independently -- the width cap belongs to `MarkdownRenderingSettings`.
        Writing it here re-persists the engine and CSS unchanged: what it holds is already the
        last-saved pair, so a `DescriptionsPage` edit still staged is neither picked up nor clobbered.
        """
        staged = self.__staged()
        settings = shared_image_viewer_settings()
        settings.mode = staged.mode
        settings.strip_visible = staged.strip_visible
        settings.preview_wrap = staged.preview_wrap
        settings.preview_image_height = staged.preview_height
        settings.lightbox_image_height = staged.lightbox_height
        settings.editor_preview_height = staged.editor_preview_height
        settings.save(persistent_settings())

        rendering = shared_markdown_rendering_settings()
        rendering.max_image_width = self.__ui.max_image_width_spin_box.value()
        rendering.save(persistent_settings())

    def drop_changes(self) -> None:
        """Discard the staged choices, re-seeding every widget from its own settings object."""
        saved = self.__saved()
        self.__buttons[saved.mode].setChecked(True)
        self.__ui.strip_visible_check_box.setChecked(saved.strip_visible)
        self.__ui.wrap_check_box.setChecked(saved.preview_wrap)
        self.__ui.preview_height_spin_box.setValue(saved.preview_height)
        self.__ui.lightbox_height_spin_box.setValue(saved.lightbox_height)
        self.__ui.editor_preview_height_spin_box.setValue(saved.editor_preview_height)
        self.__ui.max_image_width_spin_box.setValue(shared_markdown_rendering_settings().max_image_width)

    def __staged(self) -> ImageChoices:
        """The choices currently shown in this page's widgets.

        :returns: the staged surface, strip visibility, strip layout, and the three image heights.
        """
        return ImageChoices(
            self.__selected_mode(),
            self.__ui.strip_visible_check_box.isChecked(),
            self.__ui.wrap_check_box.isChecked(),
            self.__ui.preview_height_spin_box.value(),
            self.__ui.lightbox_height_spin_box.value(),
            self.__ui.editor_preview_height_spin_box.value(),
        )

    @staticmethod
    def __saved() -> ImageChoices:
        """The same choices as currently held by the shared settings.

        :returns: the saved surface, strip visibility, strip layout, and the three image heights.
        """
        settings = shared_image_viewer_settings()
        return ImageChoices(
            settings.mode,
            settings.strip_visible,
            settings.preview_wrap,
            settings.preview_image_height,
            settings.lightbox_image_height,
            settings.editor_preview_height,
        )

    def __selected_mode(self) -> ImageViewerMode:
        """The mode whose radio button is currently checked.

        :returns: the checked mode; the document overlay when somehow none is checked, matching the
            default a fresh install starts on.
        """
        for mode, button in self.__buttons.items():
            if button.isChecked():
                return mode
        return DEFAULT_MODE
