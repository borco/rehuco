"""Tests for ScrapersTableModel: the Scrapers page's read-only table (#269)."""

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtGui import QBrush, QColor
from pytest import fixture
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.colors import ERROR_COLOR
from rehuco_agent.scraping.registry import LoadedScraperModule
from rehuco_agent.scraping.results import Page, ScrapeResult
from rehuco_agent.settings.ui.scrapers_table_model import (
    COLUMN_COUNT,
    COLUMN_TITLES,
    ERROR_COLUMN,
    FILE_COLUMN,
    NO_SCRAPERS_TEXT,
    SCRAPERS_COLUMN,
    ScrapersTableModel,
)


@dataclass
class FakeScraper:  # pylint: disable=missing-function-docstring
    """A `SiteScraper` with only what the table reads: a label and a publisher."""

    label: str
    publisher: str
    needs_browser: bool = False

    def matches(self, url: str) -> bool:
        del url
        return True

    def scrape_page(self, page: Page) -> ScrapeResult:
        del page
        raise NotImplementedError


LOADED = LoadedScraperModule(
    path=Path("/fake/scrapers/art_scraper.py"),
    scrapers=(FakeScraper("ArtStation", "ArtStation Inc"), FakeScraper("Marketplace", "ArtStation Inc")),
    error=None,
)
EMPTY = LoadedScraperModule(path=Path("/fake/scrapers/helpers.py"), scrapers=(), error=None)
BROKEN = LoadedScraperModule(path=Path("/fake/scrapers/broken.py"), scrapers=(), error="SyntaxError: bad")


@fixture
def model(qtbot: QtBot) -> ScrapersTableModel:
    """A model holding one loaded, one empty and one broken row."""
    del qtbot
    built = ScrapersTableModel()
    built.set_modules((LOADED, EMPTY, BROKEN))
    return built


def test_set_modules_resets_to_the_new_rows(qtbot: QtBot) -> None:
    """Replacing the rows is one model reset carrying the new count (#269).

    **Test steps:**

    * build an empty model and verify it has no rows and the fixed column count
    * set three rows inside a reset and verify the count
    """
    built = ScrapersTableModel()
    assert built.rowCount() == 0
    assert built.columnCount() == COLUMN_COUNT

    with qtbot.waitSignal(built.modelReset):
        built.set_modules((LOADED, EMPTY, BROKEN))

    assert built.rowCount() == 3
    assert built.rowCount(built.index(0, 0)) == 0
    assert built.columnCount(built.index(0, 0)) == 0


def test_headers_are_the_column_titles_and_nothing_else(model: ScrapersTableModel) -> None:
    """Horizontal display headers read the titles; anything else is `None` (#269).

    **Test steps:**

    * read every horizontal header, a vertical one, a non-display role and an out-of-range section
    """
    horizontal = Qt.Orientation.Horizontal
    assert [model.headerData(column, horizontal) for column in range(COLUMN_COUNT)] == list(COLUMN_TITLES)
    assert model.headerData(0, Qt.Orientation.Vertical) is None
    assert model.headerData(0, horizontal, Qt.ItemDataRole.ToolTipRole) is None
    assert model.headerData(COLUMN_COUNT, horizontal) is None


def test_cells_show_the_file_the_scrapers_and_the_error(model: ScrapersTableModel) -> None:
    """Each column reads its own fact off the row: the file name, ``label (publisher)`` per scraper
    comma-joined or a dash for none, and the error or nothing (#269).

    **Test steps:**

    * read the three columns of the loaded, the empty and the broken row
    """

    def cell(row: int, column: int) -> object:
        return model.data(model.index(row, column))

    assert cell(0, FILE_COLUMN) == "art_scraper.py"
    assert cell(0, SCRAPERS_COLUMN) == "ArtStation (ArtStation Inc), Marketplace (ArtStation Inc)"
    assert cell(0, ERROR_COLUMN) == ""
    assert cell(1, SCRAPERS_COLUMN) == NO_SCRAPERS_TEXT
    assert cell(2, ERROR_COLUMN) == "SyntaxError: bad"


def test_only_an_error_cell_is_tinted(model: ScrapersTableModel) -> None:
    """The error column of a broken row is drawn in the error color; every other cell, and every other
    role, answers nothing (#269).

    **Test steps:**

    * read the foreground of the broken row's error cell, a clean row's error cell and another column
    * read an unrelated role and an invalid index
    """
    foreground = Qt.ItemDataRole.ForegroundRole
    assert model.data(model.index(2, ERROR_COLUMN), foreground) == QBrush(QColor(ERROR_COLOR))
    assert model.data(model.index(0, ERROR_COLUMN), foreground) is None
    assert model.data(model.index(2, FILE_COLUMN), foreground) is None
    assert model.data(model.index(0, FILE_COLUMN), Qt.ItemDataRole.ToolTipRole) is None
    assert model.data(QModelIndex()) is None
