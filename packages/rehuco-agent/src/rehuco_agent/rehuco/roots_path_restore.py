"""The Root Catalog's current row across a restart ([[plugins#session-restore]], #576)."""

from typing import Final

from PySide6.QtCore import QAbstractItemModel, QObject, QTimer
from PySide6.QtWidgets import QAbstractItemView
from rehuco_core import RehucoFile

from ..settings.catalog_state_store import CatalogStateStore
from .root_catalog import RootCatalog
from .roots_folder_model import RootsFolderModel
from .roots_node import NodeListing


class RootsPathRestore(QObject):
    """Remembers the Roots view's current row with the catalog, and walks back to it as the listings arrive.

    A folder's rows are not there until it is listed, off the GUI thread, so the walk makes the deepest row on the way
    current, which lists it, and goes on from there at the next change of the rows. **It waits rather than gives up**: a
    root that is offline ends the walk on the root's row, and the path is kept, both to go on when the root answers and
    to be saved again, so a run with the share down costs nothing. It ends when the row is reached, when a folder listed
    has no such name in it, or when the reader moves.

    :param catalog: the open catalog, whose opening and closing are when the row is read and written.
    :param model: the Roots model.
    :param view: the Roots view.
    :param store: where a catalog's state is kept.
    :param parent: the Qt parent, which owns this.
    """

    def __init__(
        self,
        catalog: RootCatalog,
        model: RootsFolderModel,
        view: QAbstractItemView,
        store: CatalogStateStore,
        parent: QObject,
    ) -> None:
        super().__init__(parent)
        self.__model: Final = model
        self.__view: Final = view
        self.__store: Final = store
        self.__held: tuple[object, tuple[str, ...]] | None = None
        self.__walking = False
        self.__timer: Final = QTimer(self)
        self.__timer.setSingleShot(True)
        self.__timer.setInterval(0)
        self.__timer.timeout.connect(self.__walk)
        catalog.opened.connect(self.__on_opened)
        catalog.closing.connect(self.__on_closing)
        catalog.roots_changed.connect(self.__timer.start)
        source: QAbstractItemModel = model
        source.rowsInserted.connect(self.__timer.start)
        source.dataChanged.connect(self.__timer.start)

    @property
    def held(self) -> bool:
        """Whether a remembered row is still being walked to."""
        return self.__held is not None

    @property
    def walking(self) -> bool:
        """Whether the current row is being moved by this, not by the reader: the preview does not follow it."""
        return self.__walking

    def let_go(self) -> None:
        """Stop walking: the reader has moved, and where they are now is what is remembered."""
        self.__held = None

    def __on_opened(self, file: RehucoFile) -> None:
        """Hold the row the catalog remembers until its roots are shown.

        :param file: the catalog just opened.
        """
        self.__held = self.__store.load(file.rehuco_id).roots_current

    def __on_closing(self, file: RehucoFile) -> None:
        """Remember the current row, or the row still walked to.

        :param file: the catalog being let go.
        """
        current = self.__held if self.__held is not None else self.__model.key(self.__view.currentIndex())
        self.__store.save_roots_current(file.rehuco_id, current)  # type: ignore[arg-type]
        self.__held = None
        self.__timer.stop()

    def __walk(self) -> None:
        """Go as far down the path as is listed, and stop holding it once there is nothing further to wait for."""
        if self.__held is None:
            return
        root_id, names = self.__held
        model = self.__model
        index = model.index_for(root_id, names)  # type: ignore[arg-type]
        if not index.isValid():
            self.__held = None
            return
        self.__walking = True
        try:
            self.__view.setCurrentIndex(index)
        finally:
            self.__walking = False
        if model.key(index) == self.__held or model.listing_state(index) is NodeListing.LISTED:
            self.__held = None
