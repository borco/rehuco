"""Images settings page: which surface a maximized screenshot opens on (#47, #160)."""

from typing import Final, NamedTuple

from PySide6.QtWidgets import QRadioButton, QWidget

from ...fields.widgets.image_lightbox import ImageViewerMode
from ..image_viewer_settings import DEFAULT_MODE, shared_image_viewer_settings
from ..persistent_settings import persistent_settings
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
    """Configure how screenshots are presented, in the strip and maximized (#160, #161, #70).

    Five choices (:class:`ImageChoices`) -- the maximized viewer's surface, whether it starts with its
    thumbnail strip shown, whether a document's own strip wraps its thumbnails, and the strip thumbnail
    heights either side -- staged in the widgets until :meth:`save_changes` writes them into the shared
    `ImageViewerSettings` and persists them. Nothing already on screen has to follow the change from
    here (every value is read afresh where it is needed, and the reactive ones are subscribed to at the
    other end, see `ImageViewerSettings`), so unlike `DescriptionsPage` this page has no live-update
    wiring to drive.

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
        self.drop_changes()

    @property
    def title(self) -> str:
        """This page's category-tree label."""
        return "Images"

    def is_dirty(self) -> bool:
        """Whether any staged choice differs from the shared settings' current one."""
        return self.__staged() != self.__saved()

    def save_changes(self) -> None:
        """Push every staged choice into the shared settings and persist them."""
        staged = self.__staged()
        settings = shared_image_viewer_settings()
        settings.mode = staged.mode
        settings.strip_visible = staged.strip_visible
        settings.preview_wrap = staged.preview_wrap
        settings.preview_image_height = staged.preview_height
        settings.lightbox_image_height = staged.lightbox_height
        settings.save(persistent_settings())

    def drop_changes(self) -> None:
        """Discard the staged choices, re-seeding every widget from the shared settings."""
        saved = self.__saved()
        self.__buttons[saved.mode].setChecked(True)
        self.__ui.strip_visible_check_box.setChecked(saved.strip_visible)
        self.__ui.wrap_check_box.setChecked(saved.preview_wrap)
        self.__ui.preview_height_spin_box.setValue(saved.preview_height)
        self.__ui.lightbox_height_spin_box.setValue(saved.lightbox_height)

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
