"""Tests for ScrapersRowDelegate: the Scrapers table's Source/Error painting and `sizeHint` fix (#278)."""

from math import ceil

from PySide6.QtCore import QModelIndex, QRect, Qt
from PySide6.QtGui import QFontMetricsF, QPalette
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem
from pytest import fixture
from pytest_mock import MockerFixture
from rehuco_agent.scraping.registry import ScraperRow
from rehuco_agent.settings.ui.scrapers_row_delegate import TEXT_PADDING, ScrapersRowDelegate
from rehuco_agent.settings.ui.scrapers_table_model import (
    ERROR_COLUMN,
    SCRAPER_COLUMN,
    SOURCE_COLUMN,
    ScrapersTableModel,
)

CELL = QRect(0, 0, 400, 24)

ROW = ScraperRow(
    key="rehuco_user_scrapers.art_scraper.ArtScraper",
    label="ArtStation",
    publisher="ArtStation Inc",
    site_name="ArtStation",
    site_url="",
    source="art_scraper.py",
    needs_browser=False,
    error="a broken row's error message" * 3,
)


@fixture(name="delegate")
def fixture_delegate(qapp: object) -> ScrapersRowDelegate:
    """The delegate under test; takes ``qapp`` because measuring fonts needs a `QGuiApplication` to
    exist first.

    :param qapp: the Qt application fixture.
    :returns: the delegate.
    """
    del qapp
    return ScrapersRowDelegate()


def index_for(row: ScraperRow, column: int) -> tuple[ScrapersTableModel, QModelIndex]:
    """A model and one index over it, for the delegate to measure.

    **Returns the model too**: a `QModelIndex` keeps only a raw pointer back to its source model, so a
    model built and discarded inside this function leaves the index pointing at a destroyed object.

    :param row: the row to show.
    :param column: which column's index to return.
    :returns: ``(model, index)``.
    """
    model = ScrapersTableModel()
    model.set_rows((row,))
    return model, model.index(0, column)


def option_for(palette: QPalette, *, hovered: bool = False) -> QStyleOptionViewItem:
    """A style option over :data:`CELL`, ready to hand to the delegate.

    :param palette: the palette to draw with.
    :param hovered: whether to mark it as under the mouse.
    :returns: the option.
    """
    option = QStyleOptionViewItem()
    option.rect = CELL
    option.palette = palette
    if hovered:
        option.state |= QStyle.StateFlag.State_MouseOver
    return option


def test_every_text_columns_hint_covers_what_it_draws(delegate: ScrapersRowDelegate) -> None:
    """The hint leaves at least the text's own measured width once the delegate's own padding is taken
    back off it -- the same invariant `FilesRowDelegate`'s own sizing tests check, and for the same
    reason: the base class measures against the *style*'s margin, not this delegate's own inset (#278).

    **Test steps:**

    * ask for the Scraper, Source and Error cells' hints
    * verify each covers its own text width plus the delegate's padding
    """
    option = option_for(QPalette())
    for column in (SCRAPER_COLUMN, SOURCE_COLUMN, ERROR_COLUMN):
        model, index = index_for(ROW, column)  # pylint: disable=unused-variable
        text = str(index.data(Qt.ItemDataRole.DisplayRole))

        hint = delegate.sizeHint(option, index)

        available = hint.width() - 2 * TEXT_PADDING
        assert available >= ceil(QFontMetricsF(option.font).horizontalAdvance(text))


def test_a_hovered_cell_is_painted_with_no_hover_highlight(
    delegate: ScrapersRowDelegate, mocker: MockerFixture
) -> None:
    """A hovered Source or Error cell is painted with `QStyle.StateFlag.State_MouseOver` stripped, so
    the base delegate draws no hover-highlight box -- this table has no concept of "hovering a row", and
    the flag is only live at all because `~.scrapers_table_view.ScrapersTableView` needs mouse tracking
    for the Scraper column's link cursor (#278).

    **Test steps:**

    * paint a hovered Source cell, with the base delegate's own paint spied on to read the option it
      actually received
    * verify that option no longer carries the hover flag, even though the one this delegate was handed
      did
    """
    base_paint = mocker.patch.object(QStyledItemDelegate, "paint")
    model, index = index_for(ROW, SOURCE_COLUMN)  # pylint: disable=unused-variable
    hovered_option = option_for(QPalette(), hovered=True)

    delegate.paint(None, hovered_option, index)  # type: ignore[arg-type]

    base_paint.assert_called_once()
    _painter, passed_option, _index = base_paint.call_args.args
    assert QStyle.StateFlag.State_MouseOver in hovered_option.state
    assert QStyle.StateFlag.State_MouseOver not in passed_option.state
