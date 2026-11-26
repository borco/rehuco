"""Tests for the grip a row is dragged by (#705): what the shared filter does on its own, before a view says what its
drags carry.

The drag itself is tested through the views that use it: the Roots view
(:mod:`~rehuco_agent_tests.rehuco.test_roots_grip`) and the License dock's list
(:mod:`~rehuco_agent_tests.documents.test_licenses_list_editor`).
"""

from borco_pyside.widgets import ReorderDrag
from PySide6.QtCore import QMimeData, QPoint, Qt
from PySide6.QtGui import QDragEnterEvent, QStandardItemModel
from PySide6.QtWidgets import QAbstractItemView, QApplication, QTableView
from pytestqt.qtbot import QtBot
from rehuco_agent.grip_reorder import GripReorderFilter


def test_a_filter_that_names_no_drag_of_its_own_takes_none(qtbot: QtBot) -> None:
    """A view's drag is the view's to recognize: the shared filter alone recognizes none, so its shadow never moves.

    **Test steps:**

    * install a plain filter on a table of two rows, start a drag of the first, and drag it over the second
    * verify the drag is refused and the shadow stays where the row was
    """
    model = QStandardItemModel(2, 1)
    view = QTableView()
    qtbot.addWidget(view)
    view.setModel(model)
    # a drag reaches only a widget that takes drops, as the views using the filter do
    view.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
    drag = ReorderDrag()
    grip = GripReorderFilter(view, drag)
    view.viewport().installEventFilter(grip)
    drag.begin(0)
    mime = QMimeData()
    enter = QDragEnterEvent(
        QPoint(5, view.rowViewportPosition(1) + 2),
        Qt.DropAction.MoveAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    enter.ignore()

    QApplication.sendEvent(view.viewport(), enter)

    assert not enter.isAccepted()
    assert drag.slot == 0
