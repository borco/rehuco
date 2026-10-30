"""Tests for `BandTreeView`: a selected row's branch area painted as part of its band, its arrow in the band's text
colour (#572).

Colours are read back from the painted viewport, under a palette of colours no style paints by accident.
"""

from typing import Final

from borco_pyside.widgets import BandTreeView, RowBandDelegate
from PySide6.QtCore import QEvent, QModelIndex, QPointF, QRect
from PySide6.QtGui import QColor, QHoverEvent, QImage, QPalette, QStandardItem, QStandardItemModel
from pytest import fixture
from pytestqt.qtbot import QtBot

HIGHLIGHT: Final = QColor("green")
HIGHLIGHTED_TEXT: Final = QColor("yellow")
TEXT: Final = QColor("red")


@fixture(name="view")
def fixture_view(qtbot: QtBot) -> BandTreeView:
    """A shown tree: a plain row, then a row with a child, then a closed row with a child.

    :param qtbot: pytest-qt fixture.
    :returns: the view.
    """
    model = QStandardItemModel()
    model.appendRow(QStandardItem("plain"))
    for name in ("open", "closed"):
        parent = QStandardItem(name)
        parent.appendRow(QStandardItem("child"))
        model.appendRow(parent)
    view = BandTreeView()
    view.setModel(model)
    # the delegate it is made to go with: the default one paints a panel of its own on the current row
    view.setItemDelegate(RowBandDelegate(view))
    palette = view.palette()
    palette.setColor(QPalette.ColorRole.Highlight, HIGHLIGHT)
    palette.setColor(QPalette.ColorRole.HighlightedText, HIGHLIGHTED_TEXT)
    palette.setColor(QPalette.ColorRole.Text, TEXT)
    view.setPalette(palette)
    view.expand(model.index(1, 0))
    qtbot.addWidget(view)
    view.resize(200, 120)
    view.show()
    return view


def branch_pixels(view: BandTreeView, index: QModelIndex) -> list[QColor]:
    """The colours of a row's branch area: everything left of its first cell.

    :param view: the view.
    :param index: the row.
    :returns: every pixel's colour.
    """
    cell = view.visualRect(index)
    image: QImage = view.viewport().grab().toImage()
    area = QRect(0, cell.top(), cell.left(), cell.height())
    return [
        QColor(image.pixel(x, y))
        for x in range(area.left(), area.right() + 1)
        for y in range(area.top(), area.bottom() + 1)
    ]


def test_a_selected_rows_branch_area_is_the_highlight_and_an_unselected_ones_is_not(view: BandTreeView) -> None:
    """**Test steps:**

    * select the plain row
    * verify its branch area is all highlight, and the next row's has none
    """
    model = view.model()
    view.setCurrentIndex(model.index(0, 0))

    assert all(pixel == HIGHLIGHT for pixel in branch_pixels(view, model.index(0, 0)))
    assert HIGHLIGHT not in branch_pixels(view, model.index(1, 0))


def test_the_arrow_is_drawn_in_the_text_colour_of_its_row(view: BandTreeView) -> None:
    """**Test steps:**

    * select the open row
    * verify its arrow is drawn in the highlighted-text colour and not the text colour
    * verify the closed, unselected row's arrow is drawn in the text colour
    * verify the plain row has no arrow at all
    """
    model = view.model()
    view.setCurrentIndex(model.index(1, 0))

    selected = branch_pixels(view, model.index(1, 0))
    closed = branch_pixels(view, model.index(2, 0))
    assert HIGHLIGHTED_TEXT in selected and TEXT not in selected
    assert TEXT in closed and HIGHLIGHTED_TEXT not in closed
    assert TEXT not in branch_pixels(view, model.index(0, 0))


def test_a_tree_with_no_model_draws_nothing_in_its_branches(qtbot: QtBot) -> None:
    """**Test steps:**

    * show a tree with no model
    * verify painting it raises nothing
    """
    view = BandTreeView()
    qtbot.addWidget(view)
    view.show()

    view.viewport().grab()


def hover(view: BandTreeView, index: QModelIndex | None) -> None:
    """Move the mouse over a row, or off the view.

    :param view: the view.
    :param index: the row, or ``None`` to leave.
    """
    if index is None:
        view.viewportEvent(QEvent(QEvent.Type.HoverLeave))
        return
    point = QPointF(view.visualRect(index).center())
    view.viewportEvent(QHoverEvent(QEvent.Type.HoverMove, point, point, QPointF(-1, -1)))


def right_edge_pixel(view: BandTreeView, index: QModelIndex) -> QColor:
    """The colour at the right edge of a row, past its text.

    :param view: the view.
    :param index: the row.
    :returns: the pixel.
    """
    image = view.viewport().grab().toImage()
    return QColor(image.pixel(view.viewport().width() - 2, view.visualRect(index).center().y()))


def test_the_hovered_row_is_one_band_from_edge_to_edge(view: BandTreeView) -> None:
    """The style hovers the branch area alone; the view fills the whole row.

    **Test steps:**

    * hover the child row, whose branch area is indented
    * verify its branch area and its far right edge are the hover colour, and another row is not
    * move to another row and verify the first is plain again
    * leave the view, by a hover leave and by a plain leave, and verify no row is hovered
    """
    model = view.model()
    child = model.index(0, 0, model.index(1, 0))

    hover(view, child)
    assert all(pixel == view.hover_color for pixel in branch_pixels(view, child))
    assert right_edge_pixel(view, child) == view.hover_color
    assert right_edge_pixel(view, model.index(0, 0)) != view.hover_color

    hover(view, model.index(0, 0))
    assert right_edge_pixel(view, child) != view.hover_color
    assert right_edge_pixel(view, model.index(0, 0)) == view.hover_color

    hover(view, None)
    assert right_edge_pixel(view, model.index(0, 0)) != view.hover_color

    hover(view, model.index(0, 0))
    view.viewportEvent(QEvent(QEvent.Type.Leave))
    assert right_edge_pixel(view, model.index(0, 0)) != view.hover_color


def test_a_selected_row_under_the_mouse_keeps_its_selection_band(view: BandTreeView) -> None:
    """**Test steps:**

    * select a row and hover it, then hover it again
    * verify its branch area is the highlight, not the hover colour
    """
    model = view.model()
    view.setCurrentIndex(model.index(0, 0))

    hover(view, model.index(0, 0))
    hover(view, model.index(0, 0))

    assert all(pixel == HIGHLIGHT for pixel in branch_pixels(view, model.index(0, 0)))
