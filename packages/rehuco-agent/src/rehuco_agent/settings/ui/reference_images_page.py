"""Reference Images settings page: which archive entries count as content images (#222)."""

from typing import Final

from PySide6.QtWidgets import QWidget
from rehuco_core import CONTENT_IMAGE_EXTENSIONS

from ..persistent_settings import persistent_settings
from ..reference_images_settings import format_extensions, shared_reference_images_settings
from .reference_images_page_ui import Ui_ReferenceImagesPage


class ReferenceImagesPage(QWidget):
    """Choose the image extensions recognized inside a reference-images resource's archive(s) (#222).

    A Default/Custom radio pair: **Default** shows core's set beside it -- written into the label from
    :data:`~rehuco_core.CONTENT_IMAGE_EXTENSIONS` rather than restated in the ``.ui``, and selectable so
    it can be copied into the custom list as a starting point -- and **Custom** holds a comma-separated
    list of the user's own, enabled only while it is the selected choice. Both halves are staged until
    :meth:`save_changes` pushes them into the shared `ReferenceImagesSettings` and persists them; from
    then on the pair's *effective* set (``content_image_extensions``) is what every subsequent
    enumeration reads ([[data-model#resource-scoping]]). Nothing re-counts on its own -- a count is only
    ever filled by an explicit action -- so this page has no live-update wiring to drive.

    The custom text is kept verbatim, saved or dropped alongside the radio choice whether or not Custom
    is selected -- switching back to Default never costs a retyped list. Normalization (dots optional,
    case and whitespace ignored, empties and duplicates dropped, an empty list resolving to the default
    set) happens where the effective set is read, not against the user's typing.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_ReferenceImagesPage()
        self.__ui.setupUi(self)
        self.__ui.default_extensions_label.setText(format_extensions(CONTENT_IMAGE_EXTENSIONS))
        self.__ui.custom_radio_button.toggled.connect(self.__ui.custom_extensions_edit.setEnabled)

        self.drop_changes()

    @property
    def title(self) -> str:
        """This page's category-tree label."""
        return "Reference Images"

    def is_dirty(self) -> bool:
        """Whether the staged choice or the staged custom text differs from the shared settings'."""
        settings = shared_reference_images_settings()
        return (
            self.__ui.custom_radio_button.isChecked() != settings.use_custom_extensions
            or self.__ui.custom_extensions_edit.text() != settings.custom_extensions
        )

    def save_changes(self) -> None:
        """Push the staged choice and custom text into the shared settings object and persist them."""
        settings = shared_reference_images_settings()
        settings.use_custom_extensions = self.__ui.custom_radio_button.isChecked()
        settings.custom_extensions = self.__ui.custom_extensions_edit.text()
        settings.save(persistent_settings())

    def drop_changes(self) -> None:
        """Discard the staged edits, reverting both the radio choice and the custom text -- the custom
        list is restored even while Default is the selected choice."""
        settings = shared_reference_images_settings()
        if settings.use_custom_extensions:
            self.__ui.custom_radio_button.setChecked(True)
        else:
            self.__ui.default_radio_button.setChecked(True)
        self.__ui.custom_extensions_edit.setText(settings.custom_extensions)
        self.__ui.custom_extensions_edit.setEnabled(settings.use_custom_extensions)
