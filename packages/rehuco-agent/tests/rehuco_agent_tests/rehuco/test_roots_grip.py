"""Tests for the band a root is dragged by in the Roots view, and what it shows while one is dragged (#378, #461)."""

import gc
from collections.abc import Generator
from pathlib import Path
from typing import Any, Final
from uuid import uuid4

import shiboken6
from borco_pyside.widgets import ReorderDrag
from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QHelpEvent,
    QImage,
    QMouseEvent,
    QPainter,
)
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractItemView, QApplication, QStyle, QStyleOptionViewItem, QWidget
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco.root_row_delegate import RootRowDelegate
from rehuco_agent.rehuco.roots_column_view import RootsColumnView
from rehuco_agent.rehuco.roots_folder_model import NodeListing, RootsFolderModel
from rehuco_agent.rehuco.roots_grip import GRIP_TOOLTIP, GRIP_WIDTH, RootsGripFilter, paint_grip
from rehuco_agent.rehuco.roots_item_delegate import RootsItemDelegate
from rehuco_core import RehucoRoot, RootFolderLister, RootStorage

WAIT_TIMEOUT_MS: Final = 10_000

ON_GRIP: Final = QPoint(GRIP_WIDTH // 2, 8)
OFF_GRIP: Final = QPoint(GRIP_WIDTH + 60, 8)


@fixture(name="roots")
def fixture_roots(qtbot: QtBot, tmp_path: Path) -> Generator[tuple[RootsColumnView, RootsFolderModel]]:
    """A shown column view over three roots, the first with a folder in it, with reordering on.

    :param qtbot: pytest-qt fixture.
    :param tmp_path: pytest's temporary directory.
    :yields: the view and its model.
    """
    (tmp_path / "a" / "sub").mkdir(parents=True)
    (tmp_path / "b").mkdir()
    (tmp_path / "c").mkdir()
    roots = [RehucoRoot(uuid4(), tmp_path / name, name, RootStorage.LOCAL) for name in ("a", "b", "c")]
    model = RootsFolderModel()
    view = RootsColumnView()
    view.setModel(model)
    qtbot.addWidget(view)
    model.set_roots(roots, RootFolderLister(roots))
    model.set_reorderable(True)
    view.resize(520, 260)
    view.show()
    qtbot.waitExposed(view)
    for row in range(3):
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


def test_only_the_column_of_roots_takes_a_drop_and_the_views_own_drag_stays_off(
    qtbot: QtBot, roots: tuple[RootsColumnView, RootsFolderModel]
) -> None:
    """The first column takes the drop of a dragged root and draws no drop line; the drag itself is the grip's, so the
    view's own stays off. A folder column takes neither.

    **Test steps:**

    * open the first root so a folder column exists
    * verify the roots column's drop and drag settings, and the folder column's
    """
    view, model = roots
    view.setCurrentIndex(model.index(0, 0))
    qtbot.wait(50)

    first, second = first_column(view), second_column(view)

    assert first.acceptDrops()
    assert not first.showDropIndicator()
    assert first.dragDropMode() == QAbstractItemView.DragDropMode.DropOnly
    assert not first.dragEnabled()
    assert not second.acceptDrops()
    assert not second.dragEnabled()


def the_drag(view: RootsColumnView) -> ReorderDrag:
    """The drag the roots column paints its rows from.

    :param view: the column view.
    :returns: the roots column's drag.
    """
    delegate = first_column(view).itemDelegate()
    assert isinstance(delegate, RootRowDelegate)
    drag = delegate._RootsItemDelegate__drag  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert isinstance(drag, ReorderDrag)
    return drag


def shown(view: RootsColumnView) -> list[int | None]:
    """What the roots column shows, row by row: a root's row, or ``None`` for the shadow.

    :param view: the column view.
    :returns: one entry per row.
    """
    drag = the_drag(view)
    return [drag.source_at(row) for row in range(first_column(view).model().rowCount())]


def row_point(view: RootsColumnView, row: int, where: str) -> QPoint:
    """A point of a row of the roots column, off its grip.

    :param view: the column view.
    :param row: the row.
    :param where: ``"top"``, ``"middle"`` or ``"bottom"`` of the row.
    :returns: the point, in the viewport's coordinates.
    """
    rect = first_column(view).visualRect(first_column(view).model().index(row, 0))
    y = {"top": rect.top() + 2, "middle": rect.center().y(), "bottom": rect.bottom() - 2}[where]
    return QPoint(GRIP_WIDTH + 30, y)


def press_and_move(viewport: QWidget, start: QPoint) -> None:
    """Press the left button at ``start`` and move well past the drag distance, as a hand starting a drag does.

    :param viewport: the column's viewport.
    :param start: where the button goes down.
    """
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    end = QPointF(start + QPoint(0, 3 * QApplication.startDragDistance()))
    move = QMouseEvent(
        QEvent.Type.MouseMove,
        end,
        viewport.mapToGlobal(end),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(viewport, move)


def test_pressing_and_moving_a_grip_drags_its_root_whose_place_is_the_shadow_meanwhile(
    mocker: MockerFixture, roots: tuple[RootsColumnView, RootsFolderModel]
) -> None:
    """A grip starts a drag of its root, carrying the root's id; for as long as the drag runs, the root's own place is
    the shadow, as a dragged card's is; after it, the column shows every root again.

    **Test steps:**

    * replace ``QDrag`` so the drag records what the column shows instead of blocking
    * press and move the second root's grip
    * verify one move drag carrying the second root, the column showing the shadow at its place meanwhile, and the
      roots back in order afterwards
    """
    view, model = roots
    viewport = first_column(view).viewport()
    during: list[list[int | None]] = []
    drag_class = mocker.patch("rehuco_agent.rehuco.roots_grip.QDrag")
    drag_class.return_value.exec.side_effect = lambda *_args: during.append(shown(view))
    grip = QPoint(GRIP_WIDTH // 2, row_point(view, 1, "middle").y())

    press_and_move(viewport, grip)

    started = drag_class.return_value
    started.exec.assert_called_once_with(Qt.DropAction.MoveAction)
    (mime,) = started.setMimeData.call_args.args
    assert bytes(mime.data("application/x-rehuco-root").data()) == bytes(
        model.mimeData([model.index(1, 0)]).data("application/x-rehuco-root").data()
    )
    assert during == [[0, None, 2]]
    assert shown(view) == [0, 1, 2]


def test_a_press_off_the_grip_or_while_reordering_is_off_starts_no_drag(
    mocker: MockerFixture, roots: tuple[RootsColumnView, RootsFolderModel]
) -> None:
    """Only the band at the left of a root drags it: a click-and-move anywhere else on the row just selects, and a
    read-only catalog has no grip.

    **Test steps:**

    * with ``QDrag`` replaced, press and move off the grip; then turn reordering off and press and move the grip
    * verify no drag was started
    """
    view, model = roots
    viewport = first_column(view).viewport()
    drag_class = mocker.patch("rehuco_agent.rehuco.roots_grip.QDrag")

    press_and_move(viewport, OFF_GRIP)
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, OFF_GRIP)
    model.set_reorderable(False)
    press_and_move(viewport, ON_GRIP)

    drag_class.assert_not_called()


def test_a_press_that_has_not_moved_far_enough_starts_no_drag_yet(
    mocker: MockerFixture, roots: tuple[RootsColumnView, RootsFolderModel]
) -> None:
    """As with a card's grip, a press on a grip becomes a drag only once the pointer has moved the drag distance.

    **Test steps:**

    * with ``QDrag`` replaced, press a grip and move one pixel with the button down
    * verify no drag was started
    """
    view, _model = roots
    viewport = first_column(view).viewport()
    drag_class = mocker.patch("rehuco_agent.rehuco.roots_grip.QDrag")
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, ON_GRIP)
    nudge = QPointF(ON_GRIP + QPoint(0, 1))

    QApplication.sendEvent(
        viewport,
        QMouseEvent(
            QEvent.Type.MouseMove,
            nudge,
            viewport.mapToGlobal(nudge),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )

    drag_class.assert_not_called()
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, ON_GRIP)


def drag_event(
    view: RootsColumnView, kind: QEvent.Type, point: QPoint, mime: QMimeData | None = None
) -> tuple[QMimeData, Any]:
    """An unaccepted drag event over the roots column, carrying the dragged root unless told otherwise.

    :param view: the column view.
    :param kind: ``DragEnter``, ``DragMove`` or ``Drop``.
    :param point: where the pointer is, in the viewport's coordinates.
    :param mime: what is dragged; the dragged root when ``None``.
    :returns: what is dragged, which the caller keeps alive beside the event, and the event.
    """
    model = first_column(view).model()
    data = mime if mime is not None else model.mimeData([model.index(the_drag(view).dragged, 0)])
    if kind == QEvent.Type.Drop:
        event: Any = QDropEvent(
            QPointF(point), Qt.DropAction.MoveAction, data, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
        )
    else:
        cls = QDragEnterEvent if kind == QEvent.Type.DragEnter else QDragMoveEvent
        event = cls(point, Qt.DropAction.MoveAction, data, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    # the platform hands a widget an event nobody has accepted yet
    event.ignore()
    return data, event


def send(view: RootsColumnView, kind: QEvent.Type, point: QPoint, mime: QMimeData | None = None) -> bool:
    """Send a drag event to the roots column.

    :param view: the column view.
    :param kind: ``DragEnter``, ``DragMove`` or ``Drop``.
    :param point: where the pointer is.
    :param mime: what is dragged; the dragged root when ``None``.
    :returns: whether the column accepted it.
    """
    data, event = drag_event(view, kind, point, mime)
    QApplication.sendEvent(first_column(view).viewport(), event)
    del data
    return bool(event.isAccepted())


def test_one_shadow_follows_the_pointer_and_the_other_roots_close_up_around_it(
    roots: tuple[RootsColumnView, RootsFolderModel],
) -> None:
    """While the first root is dragged: over its own place the shadow is where it was; over the bottom of the last row
    the shadow is last and the others have moved up; back at the top the shadow is first again -- one shadow at a time.

    **Test steps:**

    * begin a drag of the first root, as its grip does
    * move it over its own row, the bottom of the last row, and the top of the first row
    * verify what the column shows after each
    """
    view, _model = roots
    the_drag(view).begin(0)

    assert send(view, QEvent.Type.DragEnter, row_point(view, 0, "middle"))
    assert shown(view) == [None, 1, 2]
    assert send(view, QEvent.Type.DragMove, row_point(view, 2, "bottom"))
    assert shown(view) == [1, 2, None]
    assert send(view, QEvent.Type.DragMove, row_point(view, 0, "top"))
    assert shown(view) == [None, 1, 2]


def test_leaving_puts_the_shadow_back_where_the_root_was(roots: tuple[RootsColumnView, RootsFolderModel]) -> None:
    """A drag that leaves the column leaves the shadow at the root's own place until it ends, as a card list's does.

    **Test steps:**

    * drag the first root to the bottom of the last row, then leave
    * verify the shadow is back at the first row
    """
    view, _model = roots
    the_drag(view).begin(0)
    send(view, QEvent.Type.DragEnter, row_point(view, 2, "bottom"))

    QApplication.sendEvent(first_column(view).viewport(), QDragLeaveEvent())

    assert shown(view) == [None, 1, 2]


def test_leaving_with_nothing_to_move_back_changes_nothing(roots: tuple[RootsColumnView, RootsFolderModel]) -> None:
    """A leave while no root is dragged, or while the shadow is already at the root's place, leaves things as they are.

    **Test steps:**

    * leave with no drag; then begin one and leave without moving the shadow
    * verify the column shows every root, then the shadow at the dragged root's place
    """
    view, _model = roots
    viewport = first_column(view).viewport()

    QApplication.sendEvent(viewport, QDragLeaveEvent())
    assert shown(view) == [0, 1, 2]
    the_drag(view).begin(1)
    QApplication.sendEvent(viewport, QDragLeaveEvent())

    assert shown(view) == [0, None, 2]


def test_a_drop_that_is_not_of_the_dragged_root_is_refused_by_the_grip_filter(
    roots: tuple[RootsColumnView, RootsFolderModel],
) -> None:
    """Qt never delivers a drop to a column that turned its drag away, but should one reach the filter, it is refused
    and the drag goes on.

    **Test steps:**

    * begin a drag of the first root and hand the filter a drop of the second root directly
    * verify it was taken from the view, not accepted, and the shadow is still at the first row
    """
    view, model = roots
    column = first_column(view)
    grip_filter = next(child for child in column.children() if isinstance(child, RootsGripFilter))
    the_drag(view).begin(0)
    data, drop = drag_event(view, QEvent.Type.Drop, row_point(view, 2, "bottom"), model.mimeData([model.index(1, 0)]))

    assert grip_filter.eventFilter(column.viewport(), drop)

    assert not drop.isAccepted()
    assert shown(view) == [None, 1, 2]
    del data


def test_the_drop_moves_the_root_to_the_shadow_and_a_drop_on_its_own_place_moves_nothing(
    roots: tuple[RootsColumnView, RootsFolderModel],
) -> None:
    """The drop asks the model for the shadow's place, and the drag is over; dropped where it was, nothing is asked.

    **Test steps:**

    * drag the first root to the bottom of the last row and drop it there
    * drag the second root over its own row and drop it there
    * verify one move of the first root to the last row was asked for, and the column shows every root again
    """
    view, model = roots
    asked: list[tuple[object, int]] = []
    model.root_move_requested.connect(lambda root_id, to: asked.append((root_id, to)))
    first_root = model.root_at(model.index(0, 0))
    assert first_root is not None

    the_drag(view).begin(0)
    send(view, QEvent.Type.DragEnter, row_point(view, 2, "bottom"))
    assert send(view, QEvent.Type.Drop, row_point(view, 2, "bottom"))
    the_drag(view).begin(1)
    send(view, QEvent.Type.DragEnter, row_point(view, 1, "middle"))
    assert send(view, QEvent.Type.Drop, row_point(view, 1, "middle"))

    assert asked == [(first_root.root_id, 2)]
    assert shown(view) == [0, 1, 2]


def test_the_roots_changing_under_a_drag_abandons_it(
    qtbot: QtBot, tmp_path: Path, roots: tuple[RootsColumnView, RootsFolderModel]
) -> None:
    """A scan's end or a relist can add or remove a root mid-drag; the shadow must not name a row that is gone, so the
    drag is abandoned and its drop refused -- as a card list refuses a drop once its rows changed. A folder's rows
    changing is no such thing.

    **Test steps:**

    * drag the first root to the bottom, then list a folder under the first root
    * verify the drag is still on
    * add a fourth root
    * verify the column shows every root again and a drop of the drag is refused
    """
    view, model = roots
    the_drag(view).begin(0)
    send(view, QEvent.Type.DragEnter, row_point(view, 2, "bottom"))
    assert shown(view) == [1, 2, None]

    first = model.index(0, 0)
    model.relist(first)
    qtbot.waitUntil(lambda: model.rowCount(first) == 1, timeout=WAIT_TIMEOUT_MS)
    assert the_drag(view).active

    (tmp_path / "d").mkdir()
    more = [
        *(model.root_at(model.index(row, 0)) for row in range(3)),
        RehucoRoot(uuid4(), tmp_path / "d", "d", RootStorage.LOCAL),
    ]
    model.set_roots(
        [root for root in more if root is not None], RootFolderLister([root for root in more if root is not None])
    )

    assert not the_drag(view).active
    assert shown(view) == [0, 1, 2, 3]
    data, drop = drag_event(view, QEvent.Type.Drop, row_point(view, 2, "bottom"), model.mimeData([model.index(0, 0)]))
    QApplication.sendEvent(first_column(view).viewport(), drop)
    assert not drop.isAccepted()
    del data


def test_a_drag_this_column_did_not_start_is_not_taken(roots: tuple[RootsColumnView, RootsFolderModel]) -> None:
    """Text from elsewhere, a root while no drag of this column runs, another root's id and a damaged id are refused,
    and none of them moves the shadow.

    **Test steps:**

    * with no drag running, offer the first root; then begin a drag of it and offer text, another root and a damaged id
    * verify each was refused and the shadow stayed at the first row
    """
    view, model = roots
    root = model.mimeData([model.index(0, 0)])
    text = QMimeData()
    text.setText("not a root")
    other = model.mimeData([model.index(1, 0)])
    damaged = QMimeData()
    damaged.setData("application/x-rehuco-root", b"not an id")
    point = row_point(view, 2, "bottom")

    assert not send(view, QEvent.Type.DragEnter, point, root)
    the_drag(view).begin(0)
    for mime in (text, other, damaged):
        assert not send(view, QEvent.Type.DragEnter, point, mime)
        assert not send(view, QEvent.Type.Drop, point, mime)

    assert shown(view) == [None, 1, 2]


def painted_rows(column: QAbstractItemView, content: Any) -> dict[int, tuple[int, bool]]:
    """What each row of a column was painted with, read off a spy on the delegate's ``paint_content``.

    :param column: the column.
    :param content: the spy.
    :returns: for each painted row, the row of the root painted there and whether it was painted selected.
    """
    painted: dict[int, tuple[int, bool]] = {}
    for call in content.call_args_list:
        _delegate, _painter, option, index, rect, _color = call.args
        row = column.indexAt(QPoint(GRIP_WIDTH + 30, rect.center().y())).row()
        painted[row] = (index.row(), bool(option.state & QStyle.StateFlag.State_Selected))
    return painted


def test_the_shadow_row_paints_the_shadow_and_the_others_paint_the_root_shown_there(
    mocker: MockerFixture, roots: tuple[RootsColumnView, RootsFolderModel]
) -> None:
    """While a root is dragged, each row of the column paints what the drag says is there: the shadow in the shadow's
    row, the card list's own; the root that has closed up into each other row, selected if that root is.

    **Test steps:**

    * select the third root, drag the first to the bottom of the last row, and repaint the column
    * verify the shadow was painted once, in the last row's rect, and the first two rows painted the second and third
      roots, the second of them selected
    """
    view, model = roots
    column = first_column(view)
    # selected as a click selects it: in the column, whose own selection its rows are painted from
    column.setCurrentIndex(model.index(2, 0))
    assert column.selectionModel().isSelected(model.index(2, 0))
    ghost = mocker.patch("rehuco_agent.rehuco.roots_item_delegate.paint_drag_ghost")
    content = mocker.spy(RootRowDelegate, "paint_content")
    the_drag(view).begin(0)
    send(view, QEvent.Type.DragEnter, row_point(view, 2, "bottom"))

    column.viewport().repaint()

    _painter, rect, _palette = ghost.call_args.args
    assert ghost.call_count == 1
    assert rect.toRect() == column.visualRect(model.index(2, 0))
    assert painted_rows(column, content) == {0: (1, False), 1: (2, True)}


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


def test_hovering_the_grip_says_what_it_is_for(
    mocker: MockerFixture, roots: tuple[RootsColumnView, RootsFolderModel]
) -> None:
    """The grip's tooltip is the card list's, so the two handles read alike, and it is asked for only over a grip.

    **Test steps:**

    * ask for a tooltip over the grip of the first root, with the tooltip call captured
    * verify the card list's wording, shown with a rect that is the grip's band
    * ask for one off the grip and verify none was shown by the grip
    """
    view, _model = roots
    first = first_column(view)
    viewport = first.viewport()
    show = mocker.patch("rehuco_agent.rehuco.roots_grip.QToolTip.showText")

    QApplication.sendEvent(viewport, QHelpEvent(QEvent.Type.ToolTip, ON_GRIP, viewport.mapToGlobal(ON_GRIP)))

    assert GRIP_TOOLTIP == "Drag to reorder"
    show.assert_called_once()
    _position, text, _widget, band = show.call_args.args
    assert text == GRIP_TOOLTIP
    assert band.width() == GRIP_WIDTH
    assert band.contains(ON_GRIP)

    show.reset_mock()
    QApplication.sendEvent(viewport, QHelpEvent(QEvent.Type.ToolTip, OFF_GRIP, viewport.mapToGlobal(OFF_GRIP)))

    show.assert_not_called()


def through_window(window: QWidget, kind: QEvent.Type, point: QPoint, buttons: Qt.MouseButton) -> None:
    """Deliver a mouse event to a top-level window, which hands it to the widget under the point, as real input
    arrives -- so no wrapper of any widget on the way is fetched, kept, or registered by the test.

    :param window: the top-level window.
    :param kind: the mouse event's type.
    :param point: where, in the window's coordinates.
    :param buttons: the buttons down.
    """
    local = QPointF(point)
    button = Qt.MouseButton.LeftButton if kind != QEvent.Type.MouseMove else Qt.MouseButton.NoButton
    QApplication.sendEvent(
        window.windowHandle(),
        QMouseEvent(kind, local, window.mapToGlobal(local), button, buttons, Qt.KeyboardModifier.NoModifier),
    )


def test_the_grip_keeps_working_after_the_columns_wrapper_is_invalidated(
    mocker: MockerFixture, qtbot: QtBot, roots: tuple[RootsColumnView, RootsFolderModel]
) -> None:
    """Shiboken can invalidate the wrapper of an object Qt made -- the column is one -- while the object lives
    (#459, #461): after adding and deleting a location, every hover over a grip raised "already deleted". A hover, a
    tooltip and a drag still work after it, with the input arriving through the window as real input does.

    **Test steps:**

    * note where the first grip is in the window, then invalidate the column's wrapper and collect garbage
    * hover the grip, ask for its tooltip, and press and move it -- all through the window -- with ``QDrag`` replaced
    * verify nothing raised, the tooltip and the hand cursor showed, and one drag started
    """
    view, _model = roots
    grip = first_column(view).viewport().mapTo(view, ON_GRIP)
    drag_class = mocker.patch("rehuco_agent.rehuco.roots_grip.QDrag")
    tooltip = mocker.patch("rehuco_agent.rehuco.roots_grip.QToolTip.showText")
    shiboken6.invalidate(first_column(view))
    gc.collect()

    with qtbot.capture_exceptions() as raised:
        through_window(view, QEvent.Type.MouseMove, grip, Qt.MouseButton.NoButton)
        viewport = QApplication.widgetAt(view.mapToGlobal(grip))
        assert viewport is not None
        QApplication.sendEvent(viewport, QHelpEvent(QEvent.Type.ToolTip, ON_GRIP, view.mapToGlobal(grip)))
        through_window(view, QEvent.Type.MouseButtonPress, grip, Qt.MouseButton.LeftButton)
        away = grip + QPoint(0, 3 * QApplication.startDragDistance())
        through_window(view, QEvent.Type.MouseMove, away, Qt.MouseButton.LeftButton)

    assert not raised
    assert viewport.cursor().shape() == Qt.CursorShape.OpenHandCursor
    tooltip.assert_called_once()
    drag_class.return_value.exec.assert_called_once_with(Qt.DropAction.MoveAction)
