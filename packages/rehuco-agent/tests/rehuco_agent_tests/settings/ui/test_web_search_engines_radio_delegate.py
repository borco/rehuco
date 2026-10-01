"""Tests for WebSearchEnginesRadioDelegate: the Use column's radio, over the selection band (#383)."""

from PySide6.QtCore import QModelIndex, QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPalette, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QStyle, QStyleOptionViewItem
from pytest import fixture
from rehuco_agent.settings.ui.web_search_engines_radio_delegate import WebSearchEnginesRadioDelegate

CELL = QRect(0, 0, 60, 24)
HIGHLIGHT = QColor("green")
HIGHLIGHTED_TEXT = QColor("yellow")


@fixture(name="delegate")
def fixture_delegate(qapp: object) -> WebSearchEnginesRadioDelegate:
    """The delegate under test; takes ``qapp`` because drawing needs a `QGuiApplication`."""
    del qapp
    return WebSearchEnginesRadioDelegate()


def index_for(state: Qt.CheckState) -> tuple[QStandardItemModel, QModelIndex]:
    """A one-cell model holding ``state``, returned with its index so the model outlives the index."""
    model = QStandardItemModel(1, 1)
    item = QStandardItem()
    item.setCheckable(True)
    item.setCheckState(state)
    model.setItem(0, 0, item)
    return model, model.index(0, 0)


def painted(delegate: WebSearchEnginesRadioDelegate, state: Qt.CheckState, *, selected: bool) -> QImage:
    """Paint the cell and hand back the image.

    :param delegate: the delegate under test.
    :param state: the check state to show.
    :param selected: whether to paint it as part of a selected row.
    :returns: the image.
    """
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Highlight, HIGHLIGHT)
    palette.setColor(QPalette.ColorRole.HighlightedText, HIGHLIGHTED_TEXT)
    option = QStyleOptionViewItem()
    option.rect = CELL
    option.palette = palette
    if selected:
        option.state |= QStyle.StateFlag.State_Selected
    model, index = index_for(state)  # pylint: disable=unused-variable
    image = QImage(CELL.size(), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    try:
        delegate.paint(painter, option, index)
    finally:
        painter.end()
    return image


def test_a_selected_row_fills_the_cell_and_draws_the_radio_in_the_highlighted_pen(
    delegate: WebSearchEnginesRadioDelegate,
) -> None:
    """The style's radio all but vanishes on the highlight, so a selected row draws its own.

    **Test steps:**

    * paint a checked radio on a selected row
    * verify the corner is the highlight and the radio's centre dot is the highlighted-text colour
    """
    image = painted(delegate, Qt.CheckState.Checked, selected=True)

    assert image.pixelColor(0, 0).name() == HIGHLIGHT.name()
    assert image.pixelColor(CELL.width() // 2, CELL.height() // 2).name() == HIGHLIGHTED_TEXT.name()


def test_an_unselected_row_leaves_the_background_alone(delegate: WebSearchEnginesRadioDelegate) -> None:
    """**Test steps:**

    * paint an unselected radio
    * verify the corner is untouched
    """
    assert painted(delegate, Qt.CheckState.Unchecked, selected=False).pixelColor(0, 0).alpha() == 0
