"""How the Roots view opens an image or a zip: the lightbox, or the system's application (#456).

What the opening entries of an image's or an archive's menu are, which archives are reference packs, and what showing
them in the lightbox takes: the panel owns the actions and the row they act on, and asks this for the entries a row
starts with.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Final, Protocol

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QWidget
from rehuco_core import FileType, RenameCoordinator

from .rehuco_roots_panel_ui import Ui_RehucoRootsPanel
from .roots_folder_model import RootsFolderModel
from .roots_lightbox import RootsLightbox
from .roots_management import PackInfo, PackState, pack_info

EXTERNAL_OPEN_MODIFIERS: Final = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
"""The keys held at a double-click that hand an image or an archive to the system's application instead of the
lightbox. Plain Ctrl and Shift stay the lightbox's own surface choice."""

EXTERNAL_OPEN_TOOLTIP: Final = (
    "Open this file with the application the system associates with it. Ctrl+Alt+double-click does this from the list."
)
""":attr:`~.rehuco_roots_panel_ui.Ui_RehucoRootsPanel.open_file_action`'s tooltip for a row the lightbox also opens."""

PLAIN_OPEN_TOOLTIP: Final = "Open this file with the application the system associates with it."


class TypeSource(Protocol):  # pylint: disable=too-few-public-methods
    """What the cache says of a record: the open catalog."""

    def resource_type(self, record: Path) -> str | None:
        """The type the cache holds for a record, or ``None`` for none."""


class RootsOpening:
    """The opening entries of an image's or an archive's row, and what they do.

    **An image, and a zip the cache knows as reference images**, have **Open** first -- the lightbox -- and the system's
    application after it, named so; any other archive has only the application, as does any other file. The cache is
    asked through ``types`` each time, so a scan that lands changes the next menu.

    :param model: the Roots model.
    :param ui: the panel's actions.
    :param types: the open catalog, which says what type a record is.
    :param coordinator: what the lightbox's archive reads are held under, so they never block a rename.
    :param host: the widget the lightbox covers -- the Roots panel.
    :param notify: told a sentence the user should see, such as an archive with no images.
    """

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        model: RootsFolderModel,
        ui: Ui_RehucoRootsPanel,
        types: TypeSource,
        coordinator: RenameCoordinator,
        host: QWidget,
        notify: Callable[[str], None],
    ) -> None:
        self.__model: Final = model
        self.__ui: Final = ui
        self.__types: Final = types
        self.__lightbox: Final = RootsLightbox(host, coordinator)
        self.__lightbox.nothing_to_show.connect(notify)

    @property
    def lightbox(self) -> RootsLightbox:
        """What opens the lightbox."""
        return self.__lightbox

    def external_requested(self, index: QModelIndex) -> bool:
        """Whether a double-click on a row is to open it in the system's application: **Ctrl+Alt** held, on an image
        or an archive.

        :param index: the row.
        :returns: whether it is.
        """
        held = QApplication.keyboardModifiers() & EXTERNAL_OPEN_MODIFIERS == EXTERNAL_OPEN_MODIFIERS
        return held and self.__model.file_type_of(index) in (FileType.IMAGE, FileType.ARCHIVE)

    def pack_of(self, index: QModelIndex) -> PackInfo | None:
        """Whether an archive row is a reference pack, from the cache.

        :param index: the row.
        :returns: the answer; ``None`` for a row that is not an archive.
        """
        return pack_info(self.__model, index, self.__types.resource_type)

    def shows_in_lightbox(self, index: QModelIndex) -> bool:
        """Whether a file row opens in the lightbox: any image, and an archive that is a reference pack.

        :param index: the row.
        :returns: whether it does.
        """
        file_type = self.__model.file_type_of(index)
        if file_type is FileType.IMAGE:
            return True
        info = self.pack_of(index) if file_type is FileType.ARCHIVE else None
        return info is not None and info.state is PackState.PACK

    def actions(self, index: QModelIndex) -> list[QAction]:
        """The opening entries of a file that is neither a record nor a checksum file: **Open** in the lightbox where
        it has one, and the system's application, said so where there is a lightbox beside it.

        :param index: the file.
        :returns: the actions, the default first.
        """
        ui = self.__ui
        external = self.__model.file_type_of(index) in (FileType.IMAGE, FileType.ARCHIVE)
        ui.open_file_action.setText("Open in external app" if external else "Open")
        ui.open_file_action.setToolTip(EXTERNAL_OPEN_TOOLTIP if external else PLAIN_OPEN_TOOLTIP)
        if self.shows_in_lightbox(index):
            return [ui.open_lightbox_action, ui.open_file_action]
        return [ui.open_file_action]

    def open(self, index: QModelIndex, path: Path) -> None:
        """Show an image with the images beside it, or an archive's images, in the lightbox.

        :param index: the row.
        :param path: its path.
        """
        model = self.__model
        if model.file_type_of(index) is FileType.ARCHIVE:
            self.__lightbox.open_archive(path)
            return
        holder = index.parent()
        images: list[Path] = []
        for row in range(model.rowCount(holder)):
            sibling = model.index(row, 0, holder)
            sibling_path = model.path_of(sibling)
            if sibling_path is not None and model.file_type_of(sibling) is FileType.IMAGE:
                images.append(sibling_path)
        if path in images:
            self.__lightbox.open_images(images, images.index(path))
