"""The wizard that asks where this machine finds the roots of a catalog it has no mapping for (#514)."""

from collections.abc import Sequence
from pathlib import Path
from typing import Final, override
from uuid import UUID

from PySide6.QtCore import QByteArray
from PySide6.QtWidgets import QDialog, QWidget
from rehuco_core import RehucoRoot

from ..settings.map_roots_dialog_settings import MapRootsDialogSettings
from ..settings.persistent_settings import persistent_settings
from .map_root_row import MapRootRow
from .map_roots_dialog_ui import Ui_MapRootsDialog


class MapRootsDialog(QDialog):
    """One :class:`MapRootRow` per root, in a scrolling column; OK keeps what was filled in or skipped, Cancel nothing.

    OK is allowed with any state: a row left empty is neither mapped nor skipped, so it is asked about again at the
    next open. Geometry is restored on construction and saved in :meth:`done`, which every exit path funnels through.

    :param roots: the roots to ask about.
    :param parent: optional Qt parent.
    """

    def __init__(self, roots: Sequence[RehucoRoot], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_MapRootsDialog()
        self.__ui.setupUi(self)
        self.__rows: Final = [MapRootRow(root, self.__ui.rows_widget) for root in roots]
        for row in self.__rows:
            self.__ui.rows_layout.addWidget(row)
        self.__ui.rows_layout.addStretch()

        self.__settings: Final = MapRootsDialogSettings()
        self.__settings.load(persistent_settings())
        if self.__settings.geometry:
            self.restoreGeometry(QByteArray(self.__settings.geometry))

    @override
    def done(self, result: int) -> None:
        """Persist the dialog's geometry before closing, on every exit path.

        :param result: the dialog's result code, passed straight through to :meth:`QDialog.done`.
        """
        self.__settings.geometry = bytes(self.saveGeometry().data())
        self.__settings.save(persistent_settings())
        super().done(result)

    @property
    def mapped(self) -> dict[UUID, Path]:
        """The folder of each root that was given one and not skipped; empty unless the dialog was accepted."""
        if self.result() != QDialog.DialogCode.Accepted:
            return {}
        return {row.root.root_id: folder for row in self.__rows if (folder := row.folder) is not None}

    @property
    def skipped(self) -> list[UUID]:
        """The roots that were skipped; empty unless the dialog was accepted."""
        if self.result() != QDialog.DialogCode.Accepted:
            return []
        return [row.root.root_id for row in self.__rows if row.skipped]
