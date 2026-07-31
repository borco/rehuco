"""Reference Images settings page: which archive entries count as content images (#222)."""

from typing import Final

from PySide6.QtWidgets import QWidget
from rehuco_core import CONTENT_IMAGE_EXTENSIONS

from ...string_list_editor_icons import apply_string_list_editor_icons
from ..persistent_settings import persistent_settings
from ..reference_images_settings import normalize_extensions, shared_reference_images_settings
from .reference_images_page_ui import Ui_ReferenceImagesPage


class ReferenceImagesPage(QWidget):
    """Choose the image extensions recognized inside a reference-images resource's archive(s) (#222).

    One `StringListEditor` and nothing else (#231). It replaced a Default/Custom radio pair, and the
    reason the pair could go is that the empty-list fallback already says what Default said: a list naming
    nothing resolves to :data:`~rehuco_core.CONTENT_IMAGE_EXTENSIONS`, and Reset fills the list with that
    same set when the user wants it as a starting point. Two controls for one question, where one of them
    only ever greyed the other out, is what the pair actually amounted to. The page is now shaped exactly
    like its neighbour `ExcludedFilesPage`, which is the point of sharing the widget.

    Edits are staged in the editor until :meth:`save_changes` pushes them into the shared
    `ReferenceImagesSettings` and persists them; from then on that set is what every subsequent
    enumeration reads ([[data-model#resource-scoping]]). Nothing re-counts on save -- a count is only ever
    filled by an explicit action -- so this page has no live-update wiring to drive.

    Saving normalizes: a leading dot is optional, case and surrounding whitespace are ignored, blanks and
    duplicates are dropped, and an emptied list resolves to the shipped set. That rule lives in
    `ReferenceImagesSettings`, not in the editor, which holds whatever was typed; the page reloads itself
    from the saved result afterwards, so what it shows is always what an enumeration would actually match.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_ReferenceImagesPage()
        self.__ui.setupUi(self)
        self.__ui.extensions_editor.defaults = CONTENT_IMAGE_EXTENSIONS
        apply_string_list_editor_icons(self.__ui.extensions_editor)

        self.drop_changes()

    @property
    def title(self) -> str:
        """This page's category-tree label."""
        return "Reference Images"

    def is_dirty(self) -> bool:
        """Whether the staged list differs from the set the shared settings resolve to."""
        return self.__ui.extensions_editor.values != shared_reference_images_settings().content_image_extensions

    def save_changes(self) -> None:
        """Push the staged list into the shared settings object, persist it, and show the result.

        The editor is refilled from the saved set afterwards rather than left as typed: normalization can
        change it -- ``JPG`` becomes ``.jpg``, a blank or duplicated entry is dropped, and emptying the
        list restores the shipped formats -- and a page still showing what was typed would disagree with
        what every enumeration matches.
        """
        settings = shared_reference_images_settings()
        settings.extensions = normalize_extensions(self.__ui.extensions_editor.values)
        settings.save(persistent_settings())
        self.drop_changes()

    def drop_changes(self) -> None:
        """Discard the staged edits, refilling the editor from the shared settings' effective set."""
        self.__ui.extensions_editor.values = shared_reference_images_settings().content_image_extensions
