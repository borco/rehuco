"""The temporary list of a ``.rehuco``'s roots, until the Roots column view replaces it (#377, #378)."""

from collections.abc import Mapping, Sequence
from typing import Final, override
from uuid import UUID

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QPersistentModelIndex, Qt
from rehuco_core import RehucoRoot

COLUMN_TITLES: Final = ("Label", "Path")

UNREACHABLE_TOOLTIP: Final = "The last scan could not list this folder; its resources are kept as they were."


class RehucoRootsModel(QAbstractTableModel):
    """A read-only table over a ``.rehuco``'s :class:`~rehuco_core.RehucoRoot` entries, in file order.

    Edits go through the file, never through this model: the dock edits the file, saves it, and hands
    the new roots back here.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__roots: list[RehucoRoot] = []
        self.__reachable: dict[UUID, bool | None] = {}

    def set_roots(self, roots: Sequence[RehucoRoot], reachable: Mapping[UUID, bool | None]) -> None:
        """Replace every root.

        :param roots: the ``.rehuco``'s roots, in its order.
        :param reachable: whether each root's last scan could list it (``None`` for never scanned).
        """
        self.beginResetModel()
        self.__roots = list(roots)
        self.__reachable = dict(reachable)
        self.endResetModel()

    def root_at(self, row: int) -> RehucoRoot | None:
        """The root on a row.

        :param row: the row.
        :returns: the root, or ``None`` when ``row`` is out of range.
        """
        return self.__roots[row] if 0 <= row < len(self.__roots) else None

    @override
    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.__roots)

    @override
    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(COLUMN_TITLES)

    @override
    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> str | None:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return COLUMN_TITLES[section]
        return None

    @override
    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        if not index.isValid() or index.row() >= len(self.__roots):
            return None
        root = self.__roots[index.row()]
        if role == Qt.ItemDataRole.ToolTipRole and self.__reachable.get(root.root_id) is False:
            return UNREACHABLE_TOOLTIP
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        return root.label if index.column() == 0 else str(root.path)
