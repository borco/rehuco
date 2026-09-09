"""Images / Files settings page: what counts as an image, and what happens to its file on disk
(#222, #291, #294)."""

from typing import Final

from PySide6.QtWidgets import QWidget
from rehuco_core import CONTENT_IMAGE_EXTENSIONS

from ...item_action_icons import apply_item_action_icons
from ..persistent_settings import persistent_settings
from ..reference_images_settings import normalize_extensions, shared_reference_images_settings
from ..screenshot_deletion_settings import shared_screenshot_deletion_settings
from .images_files_page_ui import Ui_ImagesFilesPage


class ImagesFilesPage(QWidget):
    """What an image *is*, on disk -- which archive entries a reference-images resource counts as its
    images, and whether deleting a screenshot from the images editor goes through the Recycle Bin
    (#222, #291, #294).

    A sibling of `ImagesDisplayPage` under the "Images" group: that half answers how an image is
    *shown*, this one what counts as one and what happens to its file. Two settings objects meet here:

    - `ReferenceImagesSettings` -- which archive entries a reference-images resource counts as its
      images ([[data-model#resource-scoping]]).
    - `ScreenshotDeletionSettings` -- whether deleting a screenshot from the images editor goes
      through the Recycle Bin / Trash or unlinks it outright (#291).

    Everything is staged in the widgets until :meth:`save_changes` writes each object and persists it.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_ImagesFilesPage()
        self.__ui.setupUi(self)
        self.__ui.extensions_editor.defaults = CONTENT_IMAGE_EXTENSIONS
        apply_item_action_icons(self.__ui.extensions_editor)
        self.drop_changes()

    def is_dirty(self) -> bool:
        """Whether any staged choice differs from what its own settings object currently holds."""
        return (
            # normalized before the comparison, so a row saving would drop anyway is not yet a change
            # and auto-apply does not tear a fresh insert out from under its open cell (#53)
            normalize_extensions(self.__ui.extensions_editor.values)
            != shared_reference_images_settings().content_image_extensions
            or self.__ui.use_recycle_bin_check_box.isChecked() != shared_screenshot_deletion_settings().use_recycle_bin
        )

    def save_changes(self) -> None:
        """Push every staged choice into its settings object and persist it.

        Two objects, saved independently -- the extensions to `ReferenceImagesSettings` and the
        Recycle Bin choice to `ScreenshotDeletionSettings` -- each written whole because that is the
        unit its own ``save`` takes.
        """
        reference_images = shared_reference_images_settings()
        reference_images.extensions = normalize_extensions(self.__ui.extensions_editor.values)
        reference_images.save(persistent_settings())
        # refilled from the saved set rather than left as typed: normalization can change it (``JPG``
        # becomes ``.jpg``, blanks and duplicates go, an emptied list restores the shipped formats),
        # and a page still showing what was typed would disagree with what an enumeration matches
        self.__show_saved_extensions()

        deletion = shared_screenshot_deletion_settings()
        deletion.use_recycle_bin = self.__ui.use_recycle_bin_check_box.isChecked()
        deletion.save(persistent_settings())

    def drop_changes(self) -> None:
        """Discard the staged choices, re-seeding every widget from its own settings object."""
        self.__show_saved_extensions()
        self.__ui.use_recycle_bin_check_box.setChecked(shared_screenshot_deletion_settings().use_recycle_bin)

    def __show_saved_extensions(self) -> None:
        """Fill the extensions editor with the set the shared reference-images settings resolve to."""
        self.__ui.extensions_editor.values = shared_reference_images_settings().content_image_extensions
