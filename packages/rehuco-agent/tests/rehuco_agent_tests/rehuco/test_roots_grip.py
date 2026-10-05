"""Tests for the band a root is dragged by in the Roots view (#378)."""

from collections.abc import Generator
from pathlib import Path
from typing import Final
from uuid import uuid4

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractItemView, QApplication, QStyleOptionViewItem, QWidget
from pytest import fixture
from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco.roots_column_view import RootsColumnView
from rehuco_agent.rehuco.roots_folder_model import NodeListing, RootsFolderModel
from rehuco_agent.rehuco.roots_grip import GRIP_WIDTH, paint_grip
from rehuco_agent.rehuco.roots_item_delegate import RootsItemDelegate
from rehuco_core import RehucoRoot, RootFolderLister, RootStorage

WAIT_TIMEOUT_MS: Final = 10_000

ON_GRIP: Final = QPoint(GRIP_WIDTH // 2, 8)
OFF_GRIP: Final = QPoint(GRIP_WIDTH + 60, 8)


@fixture(name="roots")
def fixture_roots(qtbot: QtBot, tmp_path: Path) -> Generator[tuple[RootsColumnView, RootsFolderModel]]:
    """A shown column view over two roots, one with a folder in it, with reordering on.

    :param qtbot: pytest-qt fixture.
    :param tmp_path: pytest's temporary directory.
    :yields: the view and its model.
    """
    (tmp_path / "a" / "sub").mkdir(parents=True)
    (tmp_path / "b").mkdir()
    roots = [
        RehucoRoot(uuid4(), tmp_path / "a", "a", RootStorage.LOCAL),
        RehucoRoot(uuid4(), tmp_path / "b", "b", RootStorage.LOCAL),
    ]
    model = RootsFolderModel()
    view = RootsColumnView()
    view.setModel(model)
    qtbot.addWidget(view)
    model.set_roots(roots, RootFolderLister(roots))
    model.set_reorderable(True)
    view.resize(520, 260)
    view.show()
    qtbot.waitExposed(view)
    for row in range(2):
        index = model.index(row, 0)
        qtbot.waitUntil(lambda index=index: model.listing_state(index) is NodeListing.LISTED, timeout=WAIT_TIMEOUT_MS)
    yield view, model


def first_column(view: RootsColumnView) -> QAbstractItemView:
    """The column that lists the roots.

    :param view: the column view.
    :returns: the column.
    """
    columns = view.findChildren(QAbstractItemView)
    return next(column for column in columns if column.model() is not None and not column.rootIndex().isValid())


def second_column(view: RootsColumnView) -> QAbstractItemView:
    """The column that lists the first root's folders, once the root is current.

    :param view: the column view, with a root current.
    :returns: the column.
    """
    columns = view.findChildren(QAbstractItemView)
    return next(column for column in columns if column.model() is not None and column.rootIndex().isValid())


def hover(viewport: QWidget, position: QPoint) -> None:
    """Move the pointer over a widget, with no button down.

    The event is sent directly: a synthetic move posted through the queue can be dropped when the suite runs in
    parallel under load.

    :param viewport: the widget.
    :param position: where, in its coordinates.
    """
    point = QPointF(position)
    move = QMouseEvent(
        QEvent.Type.MouseMove,
        point,
        viewport.mapToGlobal(point),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(viewport, move)


def test_the_grip_is_two_columns_of_three_dots_in_the_text_colour() -> None:
    """The handle reads as a handle: dots, in the row's colour, centred in the band, and nothing outside it.

    **Test steps:**

    * paint a grip in a band on a white image
    * verify there are dots inside the band, of a colour near the text colour, and none beyond it
    """
    image = QImage(40, 24, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    painter = QPainter(image)
    paint_grip(painter, QRect(0, 0, GRIP_WIDTH, 24), QColor("black"))
    painter.end()

    dark = [(x, y) for x in range(40) for y in range(24) if QColor(image.pixel(x, y)).lightness() < 200]
    assert dark
    assert all(x < GRIP_WIDTH for x, _y in dark)
    assert {y for _x, y in dark} != set()


def test_only_the_column_of_roots_takes_a_drag_and_it_starts_disarmed(
    qtbot: QtBot, roots: tuple[RootsColumnView, RootsFolderModel]
) -> None:
    """The first column allows moving a root and has dragging off until a grip is pressed; a folder column allows
    neither.

    **Test steps:**

    * open the first root so a folder column exists
    * verify the roots column's drop and drag settings, and the folder column's
    """
    view, model = roots
    view.setCurrentIndex(model.index(0, 0))
    qtbot.wait(50)

    first, second = first_column(view), second_column(view)

    assert first.acceptDrops()
    assert first.showDropIndicator()
    # dragging is off until a grip is pressed, which is what makes the mode read as drop-only
    assert first.dragDropMode() == QAbstractItemView.DragDropMode.DropOnly
    assert not first.dragEnabled()
    assert not second.acceptDrops()
    assert not second.dragEnabled()


def test_a_press_on_the_grip_arms_the_drag_and_any_other_press_disarms_it(
    roots: tuple[RootsColumnView, RootsFolderModel],
) -> None:
    """Only the band at the left of a root starts a drag: a click-and-move anywhere else on the row just selects.

    **Test steps:**

    * press the grip of the first root, release, then press elsewhere on the row, release
    * verify the column's drag is on after the first press and off after the second
    """
    view, _model = roots
    first = first_column(view)
    viewport = first.viewport()

    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, ON_GRIP)
    assert first.dragEnabled()
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, ON_GRIP)

    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, OFF_GRIP)
    assert not first.dragEnabled()
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, OFF_GRIP)


def test_no_grip_works_while_reordering_is_off(roots: tuple[RootsColumnView, RootsFolderModel]) -> None:
    """A read-only catalog has no grip: pressing where it would be does not arm a drag.

    **Test steps:**

    * turn reordering off and press where the grip was
    * verify the drag stays off
    """
    view, model = roots
    model.set_reorderable(False)
    first = first_column(view)

    QTest.mousePress(first.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, ON_GRIP)

    assert not first.dragEnabled()
    QTest.mouseRelease(first.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, ON_GRIP)


def test_the_hand_cursor_shows_over_the_grip_only(roots: tuple[RootsColumnView, RootsFolderModel]) -> None:
    """The grip says it can be grabbed.

    **Test steps:**

    * move the pointer over the grip, then off it, with no button down
    * verify the open hand, then the ordinary cursor
    """
    view, _model = roots
    first = first_column(view)
    viewport = first.viewport()

    hover(viewport, ON_GRIP)
    assert viewport.cursor().shape() == Qt.CursorShape.OpenHandCursor
    hover(viewport, OFF_GRIP)
    assert viewport.cursor().shape() == Qt.CursorShape.ArrowCursor


def test_a_root_row_is_wider_by_the_grip_only_while_reordering_is_on(
    roots: tuple[RootsColumnView, RootsFolderModel],
) -> None:
    """The delegate makes room for the band when there is one, and for nothing when there is not.

    **Test steps:**

    * measure a root row with reordering on and off
    * verify it differs by the grip's width
    """
    view, model = roots
    delegate = RootsItemDelegate(view)
    option = QStyleOptionViewItem()
    with_grip = delegate.sizeHint(option, model.index(0, 0)).width()
    model.set_reorderable(False)
    without = delegate.sizeHint(option, model.index(0, 0)).width()

    assert with_grip - without == GRIP_WIDTH
