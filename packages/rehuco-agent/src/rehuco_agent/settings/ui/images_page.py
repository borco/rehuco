"""Images settings page: everything image-shaped, from what counts as one to how it is shown (#47, #160)."""

from typing import Final, NamedTuple

from PySide6.QtWidgets import QRadioButton, QWidget
from rehuco_core import CONTENT_IMAGE_EXTENSIONS

from ...fields.widgets.image_lightbox import ImageViewerMode
from ...string_list_editor_icons import apply_string_list_editor_icons
from ..image_viewer_settings import DEFAULT_MODE, shared_image_viewer_settings
from ..markdown_rendering_settings import shared_markdown_rendering_settings
from ..persistent_settings import persistent_settings
from ..reference_images_settings import normalize_extensions, shared_reference_images_settings
from .images_page_ui import Ui_ImagesPage


class ImageChoices(NamedTuple):
    """Every choice this page holds, in one comparable value ([[appendices.settings-pages#save-drop-actions]]).

    Named rather than a bare tuple because the page compares the staged set against the saved one
    wholesale (:meth:`ImagesPage.is_dirty`) *and* writes each member individually, and five positional
    booleans and ints of the same types are exactly where a swapped pair would go unnoticed.

    :param mode: which surface a maximized screenshot opens on.
    :param strip_visible: whether a maximized viewer starts with its thumbnail row shown.
    :param preview_wrap: whether a document's own image strip wraps its thumbnails (#70).
    :param preview_height: how tall a screenshot is in a document's own image strip.
    :param lightbox_height: how tall a screenshot is in the maximized viewer's own thumbnail row.
    """

    mode: ImageViewerMode
    strip_visible: bool
    preview_wrap: bool
    preview_height: int
    lightbox_height: int


class ImagesPage(QWidget):
    """Every image-shaped setting in one place: what counts as an image, and how one is shown
    (#160, #161, #70).

    Three settings objects meet here, which is the point -- a reader looking for "images" found the
    width cap under Descriptions and the recognized formats under a Reference Images page holding
    nothing else, and had to know which plugin owned which to find either:

    - `ImageViewerSettings` -- the maximized viewer's surface, whether it starts with its thumbnail
      strip shown, whether a document's own strip wraps, and the thumbnail heights either side
      (:class:`ImageChoices`, compared wholesale).
    - `MarkdownRenderingSettings` -- the width cap on an image embedded in a description. Only this
      one field, not the engine or its CSS, which stay on `DescriptionsPage` where the question is
      how a description *renders* rather than how an image is sized.
    - `ReferenceImagesSettings` -- which archive entries a reference-images resource counts as its
      images ([[data-model#resource-scoping]]).

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
        self.__ui: Final = Ui_ImagesPage()
        self.__ui.setupUi(self)
        self.__buttons: Final[dict[ImageViewerMode, QRadioButton]] = {
            ImageViewerMode.DOCUMENT_OVERLAY: self.__ui.document_overlay_radio_button,
            ImageViewerMode.APP_WINDOW_OVERLAY: self.__ui.app_window_overlay_radio_button,
            ImageViewerMode.FULL_SCREEN: self.__ui.full_screen_radio_button,
        }
        self.__ui.extensions_editor.defaults = CONTENT_IMAGE_EXTENSIONS
        apply_string_list_editor_icons(self.__ui.extensions_editor)
        self.drop_changes()

    @property
    def title(self) -> str:
        """This page's category-tree label."""
        return "Images"

    def is_dirty(self) -> bool:
        """Whether any staged choice differs from what its own settings object currently holds."""
        return (
            self.__staged() != self.__saved()
            or self.__ui.max_image_width_spin_box.value() != shared_markdown_rendering_settings().max_image_width
            or self.__ui.extensions_editor.values != shared_reference_images_settings().content_image_extensions
        )

    def save_changes(self) -> None:
        """Push every staged choice into its settings object and persist it.

        Three objects, saved independently -- the width cap belongs to `MarkdownRenderingSettings`
        and the extensions to `ReferenceImagesSettings`, and each is written whole because that is
        the unit its own ``save`` takes. Writing the shared markdown settings here re-persists the
        engine and CSS unchanged: what it holds is already the last-saved pair, so a `DescriptionsPage`
        edit still staged is neither picked up nor clobbered.
        """
        staged = self.__staged()
        settings = shared_image_viewer_settings()
        settings.mode = staged.mode
        settings.strip_visible = staged.strip_visible
        settings.preview_wrap = staged.preview_wrap
        settings.preview_image_height = staged.preview_height
        settings.lightbox_image_height = staged.lightbox_height
        settings.save(persistent_settings())

        rendering = shared_markdown_rendering_settings()
        rendering.max_image_width = self.__ui.max_image_width_spin_box.value()
        rendering.save(persistent_settings())

        reference_images = shared_reference_images_settings()
        reference_images.extensions = normalize_extensions(self.__ui.extensions_editor.values)
        reference_images.save(persistent_settings())
        # refilled from the saved set rather than left as typed: normalization can change it (``JPG``
        # becomes ``.jpg``, blanks and duplicates go, an emptied list restores the shipped formats),
        # and a page still showing what was typed would disagree with what an enumeration matches
        self.__show_saved_extensions()

    def drop_changes(self) -> None:
        """Discard the staged choices, re-seeding every widget from its own settings object."""
        saved = self.__saved()
        self.__buttons[saved.mode].setChecked(True)
        self.__ui.strip_visible_check_box.setChecked(saved.strip_visible)
        self.__ui.wrap_check_box.setChecked(saved.preview_wrap)
        self.__ui.preview_height_spin_box.setValue(saved.preview_height)
        self.__ui.lightbox_height_spin_box.setValue(saved.lightbox_height)
        self.__ui.max_image_width_spin_box.setValue(shared_markdown_rendering_settings().max_image_width)
        self.__show_saved_extensions()

    def __show_saved_extensions(self) -> None:
        """Fill the extensions editor with the set the shared reference-images settings resolve to."""
        self.__ui.extensions_editor.values = shared_reference_images_settings().content_image_extensions

    def __staged(self) -> ImageChoices:
        """The choices currently shown in this page's widgets.

        :returns: the staged surface, strip visibility, strip layout, and the two thumbnail heights.
        """
        return ImageChoices(
            self.__selected_mode(),
            self.__ui.strip_visible_check_box.isChecked(),
            self.__ui.wrap_check_box.isChecked(),
            self.__ui.preview_height_spin_box.value(),
            self.__ui.lightbox_height_spin_box.value(),
        )

    @staticmethod
    def __saved() -> ImageChoices:
        """The same choices as currently held by the shared settings.

        :returns: the saved surface, strip visibility, strip layout, and the two thumbnail heights.
        """
        settings = shared_image_viewer_settings()
        return ImageChoices(
            settings.mode,
            settings.strip_visible,
            settings.preview_wrap,
            settings.preview_image_height,
            settings.lightbox_image_height,
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
