"""Tests for ScrapersTableView: the `~rehuco_agent.settings.ui.settings_frame_filter.ValueControl`
promotion that gives the Scrapers table's **Use browser** column dirty highlighting and an
Apply/Reset/Defaults header (#278, #342), and the Scraper column's hover cursor."""

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from pytestqt.qtbot import QtBot
from rehuco_agent.scraping.registry import ScraperRow
from rehuco_agent.settings.ui.scrapers_scraper_column_delegate import ScrapersScraperColumnDelegate
from rehuco_agent.settings.ui.scrapers_table_model import SCRAPER_COLUMN, SOURCE_COLUMN, ScrapersTableModel
from rehuco_agent.settings.ui.scrapers_table_view import ScrapersTableView

KEY = "rehuco_user_scrapers.foo.Foo"
ROW = ScraperRow(
    key=KEY,
    label="Foo",
    publisher="Foo Co",
    site_name="Foo",
    site_url="https://foo.example.com",
    source="foo.py",
    needs_browser=False,
    error=None,
)
PLAIN_ROW = ScraperRow(
    key=None, label="", publisher="", site_name="", site_url="", source="broken.py", needs_browser=False, error=None
)


def move_to(view: ScrapersTableView, point: QPoint) -> None:
    """Deliver a mouse-move event at ``point`` (viewport coordinates) directly to ``view``.

    :param view: the view under test.
    :param point: the point, in the view's viewport coordinates.
    """
    position = QPointF(point)
    event = QMouseEvent(
        QEvent.Type.MouseMove,
        position,
        position,
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    view.mouseMoveEvent(event)


def test_settings_value_reads_the_models_staged_set(qtbot: QtBot) -> None:
    """The view's value is exactly `ScrapersTableModel.browser_scrapers`.

    **Test steps:**

    * build a view over a model with one row ticked
    * verify `settings_value` matches
    """
    view = ScrapersTableView()
    qtbot.addWidget(view)
    model = ScrapersTableModel()
    model.set_rows((ROW,))
    model.set_browser_scrapers(frozenset({KEY}))
    view.setModel(model)

    assert view.settings_value() == frozenset({KEY})


def test_set_settings_value_writes_back_into_the_model(qtbot: QtBot) -> None:
    """Writing a value back stages it on the model, the inverse of `settings_value` (#278).

    **Test steps:**

    * build a view over an untouched model
    * write a set back through the view
    * verify the model now holds it
    """
    view = ScrapersTableView()
    qtbot.addWidget(view)
    model = ScrapersTableModel()
    model.set_rows((ROW,))
    view.setModel(model)

    view.set_settings_value(frozenset({KEY}))

    assert model.browser_scrapers() == frozenset({KEY})


def test_settings_value_with_no_model_answers_an_empty_set(qtbot: QtBot) -> None:
    """A view with no model set (e.g. before `ScrapersPage.__init__` calls `setModel`) answers
    plainly, never raising (#278).

    **Test steps:**

    * build a bare view
    * verify `settings_value` is an empty set
    """
    view = ScrapersTableView()
    qtbot.addWidget(view)

    assert view.settings_value() == frozenset()


def test_set_settings_value_with_no_model_does_nothing(qtbot: QtBot) -> None:
    """Writing to a bare view is a no-op rather than a crash (#278)."""
    view = ScrapersTableView()
    qtbot.addWidget(view)

    view.set_settings_value(frozenset({"a.B"}))  # must not raise


def build_view(qtbot: QtBot, row: ScraperRow) -> ScrapersTableView:
    """A view over one row, its Scraper column delegated and wide enough for a deterministic hover
    target.

    :param qtbot: the widget-owning fixture.
    :param row: the row to show.
    :returns: the view, model already set.
    """
    view = ScrapersTableView()
    qtbot.addWidget(view)
    model = ScrapersTableModel()
    model.set_rows((row,))
    view.setModel(model)
    view.setItemDelegateForColumn(SCRAPER_COLUMN, ScrapersScraperColumnDelegate(view))
    view.setColumnWidth(SCRAPER_COLUMN, 200)
    view.setRowHeight(0, 24)
    return view


def test_hovering_the_link_shows_a_pointing_hand_cursor(qtbot: QtBot) -> None:
    """Moving the mouse over a Scraper cell's drawn link shows a pointing-hand cursor (#278).

    **Test steps:**

    * build a view whose one row carries a `site_url`
    * move the mouse to a point just inside the cell, where the short label is drawn
    * verify the viewport's cursor is the pointing hand
    """
    view = build_view(qtbot, ROW)
    rect = view.visualRect(view.model().index(0, SCRAPER_COLUMN))

    move_to(view, rect.topLeft() + QPoint(10, rect.height() // 2))

    assert view.viewport().cursor().shape() == Qt.CursorShape.PointingHandCursor


def test_hovering_past_the_link_shows_the_arrow_cursor(qtbot: QtBot) -> None:
    """Moving the mouse past where the short label ends -- still inside the cell -- shows the
    ordinary arrow cursor (#278).

    **Test steps:**

    * build a view whose one row carries a `site_url`
    * move the mouse to the cell's far right, well past "Foo"
    * verify the viewport's cursor is the ordinary arrow
    """
    view = build_view(qtbot, ROW)
    rect = view.visualRect(view.model().index(0, SCRAPER_COLUMN))

    move_to(view, rect.topRight() + QPoint(-2, rect.height() // 2))

    assert view.viewport().cursor().shape() == Qt.CursorShape.ArrowCursor


def test_hovering_a_row_with_no_site_url_shows_the_arrow_cursor(qtbot: QtBot) -> None:
    """A row with no `site_url` -- a file that loaded no scraper -- never shows the pointing hand,
    even at the same point a linked row would (#278).

    **Test steps:**

    * build a view whose one row carries no `site_url`
    * move the mouse into its Scraper cell
    * verify the viewport's cursor is the ordinary arrow
    """
    view = build_view(qtbot, PLAIN_ROW)
    rect = view.visualRect(view.model().index(0, SCRAPER_COLUMN))

    move_to(view, rect.topLeft() + QPoint(10, rect.height() // 2))

    assert view.viewport().cursor().shape() == Qt.CursorShape.ArrowCursor


def test_hovering_outside_the_scraper_column_shows_the_arrow_cursor(qtbot: QtBot) -> None:
    """A point over the Source column -- not the Scraper one -- never shows the pointing hand, even
    with the mouse otherwise positioned exactly as it would be over a link (#278).

    **Test steps:**

    * build a view whose one row carries a `site_url`
    * move the mouse into its Source cell
    * verify the viewport's cursor is the ordinary arrow
    """
    view = build_view(qtbot, ROW)
    rect = view.visualRect(view.model().index(0, SOURCE_COLUMN))

    move_to(view, rect.topLeft() + QPoint(10, rect.height() // 2))

    assert view.viewport().cursor().shape() == Qt.CursorShape.ArrowCursor


def test_hovering_with_no_delegate_on_the_scraper_column_shows_the_arrow_cursor(qtbot: QtBot) -> None:
    """A view whose Scraper column was never given `ScrapersScraperColumnDelegate` -- as a bare
    `ScrapersTableView` never is, until `~.scrapers_page.ScrapersPage` wires one up -- never shows
    the pointing hand, since there is no delegate to ask where its link is (#278).

    **Test steps:**

    * build a view over a linked row, with no delegate set for the Scraper column
    * move the mouse into its Scraper cell
    * verify the viewport's cursor is the ordinary arrow
    """
    view = ScrapersTableView()
    qtbot.addWidget(view)
    model = ScrapersTableModel()
    model.set_rows((ROW,))
    view.setModel(model)
    view.setColumnWidth(SCRAPER_COLUMN, 200)
    view.setRowHeight(0, 24)
    rect = view.visualRect(model.index(0, SCRAPER_COLUMN))

    move_to(view, rect.topLeft() + QPoint(10, rect.height() // 2))

    assert view.viewport().cursor().shape() == Qt.CursorShape.ArrowCursor
