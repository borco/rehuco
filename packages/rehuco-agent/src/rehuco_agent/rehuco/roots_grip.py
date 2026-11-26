"""The drag of a root by its grip in the Roots view (#378, #461)."""

from typing import cast, override
from uuid import UUID

from PySide6.QtCore import QAbstractItemModel, QMimeData

from ..grip_reorder import GripReorderFilter
from .roots_folder_model import ROOT_MIME_TYPE, RootsFolderModel


class RootsGripFilter(GripReorderFilter):
    """Drags a root of the Roots view by its grip, as :class:`~rehuco_agent.grip_reorder.GripReorderFilter` drags a
    row: a drag carries the dragged root's id, and a drop asks the model to move that root.

    Installed on the viewport of the column that lists the roots.
    """

    @override
    def _carries(self, model: QAbstractItemModel, mime: QMimeData, row: int) -> bool:
        """Whether a drag carries the dragged root: a root of another catalog's view is not it.

        :param model: the column's model.
        :param mime: the drag's data.
        :param row: the dragged row.
        :returns: whether the drag names the root at ``row``.
        """
        if not isinstance(model, RootsFolderModel) or not mime.hasFormat(ROOT_MIME_TYPE):
            return False
        try:
            root_id = UUID(bytes(mime.data(ROOT_MIME_TYPE).data()).decode("ascii"))
        except ValueError:
            return False
        root = model.root_at(model.index(row, 0))
        return root is not None and root.root_id == root_id

    @override
    def _move(self, model: QAbstractItemModel, row: int, slot: int) -> None:
        """Ask the roots' model to move the dragged root.

        :param model: the column's model; a drag of ours is a root of it, which :meth:`_carries` has checked.
        :param row: the dragged root's row.
        :param slot: where it lands.
        """
        cast(RootsFolderModel, model).request_root_move(row, slot)
