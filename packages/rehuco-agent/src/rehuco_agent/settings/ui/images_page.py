"""Images settings page: which surface a maximized screenshot opens on (#47, #160)."""

from typing import Final

from PySide6.QtWidgets import QRadioButton, QWidget

from ...fields.widgets.image_lightbox import ImageViewerMode
from ..image_viewer_settings import DEFAULT_MODE, shared_image_viewer_settings
from ..persistent_settings import persistent_settings
from .images_page_ui import Ui_ImagesPage


class ImagesPage(QWidget):
    """Configure where a screenshot clicked in a document's image strip opens (#160).

    One choice, staged in the radio buttons until :meth:`save_changes` writes it into the shared
    `ImageViewerSettings` and persists it. Nothing already on screen has to follow the change -- the
    mode is read afresh each time a viewer opens -- so, unlike `DescriptionsPage`, this page has no
    live-update wiring to drive.

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
        """Whether the selected mode differs from the shared settings' current one."""
        return self.__selected_mode() != shared_image_viewer_settings().mode

    def save_changes(self) -> None:
        """Push the selected mode into the shared settings and persist it."""
        settings = shared_image_viewer_settings()
        settings.mode = self.__selected_mode()
        settings.save(persistent_settings())

    def drop_changes(self) -> None:
        """Discard the staged choice, re-checking the shared settings' current mode."""
        self.__buttons[shared_image_viewer_settings().mode].setChecked(True)

    def __selected_mode(self) -> ImageViewerMode:
        """The mode whose radio button is currently checked.

        :returns: the checked mode; the document overlay when somehow none is checked, matching the
            default a fresh install starts on.
        """
        for mode, button in self.__buttons.items():
            if button.isChecked():
                return mode
        return DEFAULT_MODE
