"""Images / Sidecar Extensions settings page: which files count as one of a resource's sidecar
images (#222, #294)."""

from typing import Final

from PySide6.QtWidgets import QWidget
from rehuco_core import CONTENT_IMAGE_EXTENSIONS

from ...item_action_icons import apply_item_action_icons
from ..persistent_settings import persistent_settings
from ..reference_images_settings import normalize_extensions, shared_reference_images_settings
from .images_files_page_ui import Ui_ImagesFilesPage


class ImagesFilesPage(QWidget):
    """What an image *is*, on disk -- which archive entries a reference-images resource counts as its
    images (#222, #294).

    A sibling of `ImagesDisplayPage` under the "Images" group: that half answers how an image is
    *shown*, this one what counts as one. Wraps `ReferenceImagesSettings`
    ([[data-model#resource-scoping]]); the Recycle Bin choice that used to sit beside it on this page
    moved to `FilesPage` once it started governing more than one image's delete (#298).

    Staged in the widget until :meth:`save_changes` writes it and persists it.

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
        """Whether the staged extension list differs from what the shared settings currently hold."""
        # normalized before the comparison, so a row saving would drop anyway is not yet a change
        # and auto-apply does not tear a fresh insert out from under its open cell (#53)
        return (
            normalize_extensions(self.__ui.extensions_editor.values)
            != shared_reference_images_settings().content_image_extensions
        )

    def save_changes(self) -> None:
        """Push the staged extension list into the shared settings object and persist it."""
        reference_images = shared_reference_images_settings()
        reference_images.extensions = normalize_extensions(self.__ui.extensions_editor.values)
        reference_images.save(persistent_settings())
        # refilled from the saved set rather than left as typed: normalization can change it (``JPG``
        # becomes ``.jpg``, blanks and duplicates go, an emptied list restores the shipped formats),
        # and a page still showing what was typed would disagree with what an enumeration matches
        self.__show_saved_extensions()

    def drop_changes(self) -> None:
        """Discard the staged extension list, re-seeding the editor from the shared settings object."""
        self.__show_saved_extensions()

    def __show_saved_extensions(self) -> None:
        """Fill the extensions editor with the set the shared reference-images settings resolve to."""
        self.__ui.extensions_editor.values = shared_reference_images_settings().content_image_extensions
