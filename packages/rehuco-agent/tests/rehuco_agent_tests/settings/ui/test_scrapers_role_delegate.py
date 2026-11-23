"""Tests for ScrapersRoleDelegate: the Scrapers table's Scraper and Wizard glyph columns (#683)."""

from unittest.mock import Mock

from PySide6.QtCore import QModelIndex, QRect, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPalette
from PySide6.QtWidgets import QStyleOptionViewItem
from pytest import fixture
from pytest_mock import MockerFixture
from rehuco_agent.scraping.registry import ScraperRow
from rehuco_agent.scraping.role_report import RoleState
from rehuco_agent.settings.ui.scrapers_role_delegate import ROLE_ICON_SIZE, ScrapersRoleDelegate
from rehuco_agent.settings.ui.scrapers_table_model import (
    ROLE_ICONS,
    SCRAPER_ROLE_COLUMN,
    WIZARD_ROLE_COLUMN,
    ScrapersTableModel,
)
from rehuco_agent.svg_icon_cache import SvgIconCache

from rehuco_agent_tests.delete_at_teardown import DeleteAtTeardown

CELL = QRect(10, 20, 60, 24)
"""The cell every test paints: wider and taller than a glyph."""

ROW = ScraperRow(
    key=None,
    label="",
    publisher="",
    site_name="Broken",
    site_url="",
    source="broken.py",
    needs_browser=False,
    error="Broken lacks matches",
    scraper=RoleState.ERROR,
)
"""A class that declares itself a scraper, in error, and no wizard."""


@fixture(name="delegate")
def fixture_delegate(qapp: object) -> ScrapersRoleDelegate:
    """The delegate under test.

    :param qapp: the Qt application fixture, which painting needs.
    :returns: the delegate.
    """
    del qapp
    return ScrapersRoleDelegate()


def index_for(delete_at_teardown: DeleteAtTeardown, column: int) -> tuple[ScrapersTableModel, QModelIndex]:
    """A model over :data:`ROW`, and the index of one of its cells.

    :param delete_at_teardown: deletes the model when the test ends.
    :param column: the cell's column.
    :returns: ``(model, index)``; the caller keeps the model alive.
    """
    model = delete_at_teardown(ScrapersTableModel())
    model.set_rows((ROW,))
    return model, model.index(0, column)


def paint(delegate: ScrapersRoleDelegate, index: QModelIndex) -> None:
    """Paint one cell over a throwaway image.

    :param delegate: the delegate.
    :param index: the cell.
    """
    option = QStyleOptionViewItem()
    option.rect = CELL
    image = QImage(100, 60, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    try:
        delegate.paint(painter, option, index)
    finally:
        painter.end()


def test_a_declared_role_s_glyph_is_drawn_centered_in_the_row_s_text_color(
    delegate: ScrapersRoleDelegate, mocker: MockerFixture, delete_at_teardown: DeleteAtTeardown
) -> None:
    """The cell of a role the class declares draws that state's glyph, recolored to the row's text color, in a
    glyph-sized rect in the middle of the cell (#683).

    **Test steps:**

    * paint the Scraper cell of a class in error as a scraper, the icon cache stood in
    * verify the error glyph was asked for in the palette's text color, and painted at the centered rect
    """
    icon = Mock(spec=QIcon)
    cached = mocker.patch.object(SvgIconCache, "icon", return_value=icon)
    model, index = index_for(delete_at_teardown, SCRAPER_ROLE_COLUMN)  # pylint: disable=unused-variable

    paint(delegate, index)

    cached.assert_called_once()
    path, color = cached.call_args.args
    assert path == ROLE_ICONS[RoleState.ERROR]
    assert color == QPalette().color(QPalette.ColorRole.Text)
    icon.paint.assert_called_once()
    assert icon.paint.call_args.args[1] == QRect(32, 24, ROLE_ICON_SIZE, ROLE_ICON_SIZE)


def test_a_role_the_class_does_not_declare_draws_nothing(
    delegate: ScrapersRoleDelegate, mocker: MockerFixture, delete_at_teardown: DeleteAtTeardown
) -> None:
    """The cell of a role the class does not declare stays empty (#683).

    **Test steps:**

    * paint the Wizard cell of a class that declares itself no wizard, the icon cache stood in
    * verify no glyph was asked for
    """
    cached = mocker.patch.object(SvgIconCache, "icon")
    model, index = index_for(delete_at_teardown, WIZARD_ROLE_COLUMN)  # pylint: disable=unused-variable

    paint(delegate, index)

    cached.assert_not_called()


def test_the_glyph_never_outgrows_a_small_cell() -> None:
    """In a cell smaller than a glyph, the glyph shrinks to the cell's smaller side (#683).

    **Test steps:**

    * ask for the glyph's rect in a cell 10 pixels high
    * verify a 10-pixel square centered in it
    """
    cell = QRect(0, 0, 40, 10)

    rect = ScrapersRoleDelegate.icon_rect(cell)

    assert (rect.width(), rect.height()) == (10, 10)
    assert rect.center() == cell.center()
