"""Adding roots from the Roots view: ask, add, show and scan them (#378, #542, #578)."""

from collections.abc import Callable
from typing import Final

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QMessageBox, QWidget
from rehuco_core import RootCandidate

from ..settings.root_catalog_settings import shared_root_catalog_settings
from .root_catalog import RootCatalog
from .roots_column_view import RootsColumnView
from .roots_folder_model import RootsFolderModel


class RootsAdding(QObject):
    """Drives *Add Roots*: asks for the roots -- the dialog plans them, off the GUI thread -- adds them, saving the
    file once, makes the first one current, and scans each one this machine reaches when *Scan after adding* is on
    (#542).

    :param catalog: the open catalog the roots join.
    :param model: the Roots view's model, which finds the first new root's row.
    :param view: the Roots view, whose current row the first new root becomes.
    :param ask: asks for the roots -- ``None`` or none when cancelled; the owner's modal, which a test replaces.
    :param owner: the widget a refusal is shown over; also this object's parent.
    """

    def __init__(
        self,
        catalog: RootCatalog,
        model: RootsFolderModel,
        view: RootsColumnView,
        ask: Callable[[], tuple[RootCandidate, ...] | None],
        owner: QWidget,
    ) -> None:
        super().__init__(owner)
        self.__catalog: Final = catalog
        self.__model: Final = model
        self.__view: Final = view
        self.__ask: Final = ask
        self.__owner: Final = owner

    def start(self) -> None:
        """Ask for the roots, and add them."""
        file = self.__catalog.file
        if file is None or file.lock_reason is not None:
            return
        candidates = self.__ask()
        if not candidates or file is not self.__catalog.file:
            return
        added = self.__catalog.add_roots(candidates)
        if added is None:
            QMessageBox.warning(self.__owner, "Add Roots", self.__catalog.save_error)
            return
        self.__view.setCurrentIndex(self.__model.index_for(added[0], ()))
        if shared_root_catalog_settings().scan_after_adding:
            for root_id in added:
                self.__catalog.scan_root(root_id)
