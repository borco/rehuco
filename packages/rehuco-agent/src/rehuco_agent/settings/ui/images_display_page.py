"""Images / Display settings page: how a screenshot is shown, not what counts as one (#294)."""

from typing import Final, NamedTuple

from PySide6.QtWidgets import QRadioButton, QWidget

from ...fields.widgets.image_lightbox import ImageViewerMode
from ..image_viewer_settings import DEFAULT_MODE, ImageViewerSettings, shared_image_viewer_settings
from ..markdown_rendering_settings import MarkdownRenderingSettings, shared_markdown_rendering_settings
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
    :param lightbox_info_visible: whether a maximized image opens with its info overlay shown (#221).
    :param lightbox_backdrop: the colour behind a maximized image, as ``#rrggbb`` (#221).
    :param lightbox_double_click_closes: whether a double-click on the maximized image closes the
        viewer (#221).
    :param lightbox_select_last_viewed: whether closing a viewer opened from the Content Images dock
        selects the image it was on back in the dock (#221).
    :param content_min_height: the Content Images dock's shortest flush row (#221).
    :param content_max_height: the Content Images dock's tallest flush row (#221).
    :param content_zip_names: whether the Content Images dock banners each archive (#221).
    :param content_folder_names: whether the Content Images dock banners each folder (#221).
    """

    mode: ImageViewerMode
    strip_visible: bool
    preview_wrap: bool
    preview_height: int
    lightbox_height: int
    editor_preview_height: int
    lightbox_info_visible: bool
    lightbox_backdrop: str
    lightbox_double_click_closes: bool
    lightbox_select_last_viewed: bool
    content_min_height: int
    content_max_height: int
    content_zip_names: bool
    content_folder_names: bool


class ImagesDisplayPage(QWidget):
    """How an image is shown -- the surface a maximized screenshot opens on, a document's own strip,
    the three thumbnail heights, the Content Images dock's rows and banners (#221), and the width cap
    on an image embedded in a description (#160, #161, #70, #72, #294).

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
    The info-overlay box and the backdrop colour reach every open viewer on Apply, like the row height
    (#221); the backdrop is picked from a colour dialog, the button being its own swatch.

    The Content Images clamp (#221) is kept consistent **in the widgets**: raising the minimum past the
    maximum pushes the maximum up with it, and lowering the maximum under the minimum pushes the
    minimum down, so ``min <= max`` holds in every staged state rather than being checked at save.
    A push rather than linked bounds, so re-seeding the pair (:meth:`drop_changes`) works in either
    order whatever the pair currently shows.

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
        self.__ui.content_min_height_spin_box.valueChanged.connect(self.__on_content_min_height_changed)
        self.__ui.content_max_height_spin_box.valueChanged.connect(self.__on_content_max_height_changed)
        self.drop_changes()

    @property
    def backdrop(self) -> str:
        """The staged colour behind a maximized image, as ``#rrggbb``."""
        return self.__ui.lightbox_backdrop_button.color()

    def set_backdrop(self, colour: str) -> None:
        """Stage ``colour`` as the backdrop -- what the picker does with the user's choice.

        **The swatch itself holds it** (`ColorSwatchButton`), rather than this page keeping it in an
        attribute beside the button: a value the settings dialog's frame snapshot cannot see is one
        whose frame never tints and whose Apply / Reset never enable, while the change still rides
        along with another frame's Apply (#342).

        :param colour: the colour, as ``#rrggbb``.
        """
        self.__ui.lightbox_backdrop_button.set_color(colour)

    def __on_content_min_height_changed(self, minimum: int) -> None:
        """Push the maximum up when the minimum is raised past it (#221).

        :param minimum: the new minimum row height.
        """
        if minimum > self.__ui.content_max_height_spin_box.value():
            self.__ui.content_max_height_spin_box.setValue(minimum)

    def __on_content_max_height_changed(self, maximum: int) -> None:
        """Push the minimum down when the maximum is lowered under it (#221).

        :param maximum: the new maximum row height.
        """
        if maximum < self.__ui.content_min_height_spin_box.value():
            self.__ui.content_min_height_spin_box.setValue(maximum)

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
        settings.lightbox_info_visible = staged.lightbox_info_visible
        settings.lightbox_backdrop = staged.lightbox_backdrop
        settings.lightbox_double_click_closes = staged.lightbox_double_click_closes
        settings.lightbox_select_last_viewed = staged.lightbox_select_last_viewed
        settings.content_rows_min_height = staged.content_min_height
        settings.content_rows_max_height = staged.content_max_height
        settings.content_zip_names = staged.content_zip_names
        settings.content_folder_names = staged.content_folder_names
        settings.save(persistent_settings())

        rendering = shared_markdown_rendering_settings()
        rendering.max_image_width = self.__ui.max_image_width_spin_box.value()
        rendering.save(persistent_settings())

    def drop_changes(self) -> None:
        """Discard the staged choices, re-seeding every widget from its own settings object."""
        self.__show(self.__saved(), shared_markdown_rendering_settings().max_image_width)

    def seed_defaults(self) -> None:
        """Stage the factory values: what unloaded `ImageViewerSettings` and `MarkdownRenderingSettings`
        hold (#342)."""
        self.__show(self.__choices_of(ImageViewerSettings()), MarkdownRenderingSettings().max_image_width)

    def __show(self, choices: ImageChoices, max_image_width: int) -> None:
        """Fill every widget from ``choices`` and the one rendering value this page also edits.

        :param choices: the image choices to show.
        :param max_image_width: the Markdown image-width cap to show.
        """
        self.__buttons[choices.mode].setChecked(True)
        self.__ui.strip_visible_check_box.setChecked(choices.strip_visible)
        self.__ui.wrap_check_box.setChecked(choices.preview_wrap)
        self.__ui.preview_height_spin_box.setValue(choices.preview_height)
        self.__ui.lightbox_height_spin_box.setValue(choices.lightbox_height)
        self.__ui.editor_preview_height_spin_box.setValue(choices.editor_preview_height)
        self.__ui.lightbox_info_check_box.setChecked(choices.lightbox_info_visible)
        self.set_backdrop(choices.lightbox_backdrop)
        self.__ui.lightbox_double_click_check_box.setChecked(choices.lightbox_double_click_closes)
        self.__ui.lightbox_select_last_check_box.setChecked(choices.lightbox_select_last_viewed)
        self.__ui.content_min_height_spin_box.setValue(choices.content_min_height)
        self.__ui.content_max_height_spin_box.setValue(choices.content_max_height)
        self.__ui.content_zip_names_check_box.setChecked(choices.content_zip_names)
        self.__ui.content_folder_names_check_box.setChecked(choices.content_folder_names)
        self.__ui.max_image_width_spin_box.setValue(max_image_width)

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
            self.__ui.lightbox_info_check_box.isChecked(),
            self.backdrop,
            self.__ui.lightbox_double_click_check_box.isChecked(),
            self.__ui.lightbox_select_last_check_box.isChecked(),
            self.__ui.content_min_height_spin_box.value(),
            self.__ui.content_max_height_spin_box.value(),
            self.__ui.content_zip_names_check_box.isChecked(),
            self.__ui.content_folder_names_check_box.isChecked(),
        )

    @staticmethod
    def __saved() -> ImageChoices:
        """The same choices as currently held by the shared settings.

        :returns: the saved surface, strip visibility, strip layout, and the three image heights.
        """
        return ImagesDisplayPage.__choices_of(shared_image_viewer_settings())

    @staticmethod
    def __choices_of(settings: ImageViewerSettings) -> ImageChoices:
        """The choices ``settings`` holds, in this page's comparable shape.

        :param settings: the shared object, or a fresh one for the factory values (#342).
        :returns: its surface, strip visibility, strip layout, and the three image heights.
        """
        return ImageChoices(
            settings.mode,
            settings.strip_visible,
            settings.preview_wrap,
            settings.preview_image_height,
            settings.lightbox_image_height,
            settings.editor_preview_height,
            settings.lightbox_info_visible,
            settings.lightbox_backdrop,
            settings.lightbox_double_click_closes,
            settings.lightbox_select_last_viewed,
            settings.content_rows_min_height,
            settings.content_rows_max_height,
            settings.content_zip_names,
            settings.content_folder_names,
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
