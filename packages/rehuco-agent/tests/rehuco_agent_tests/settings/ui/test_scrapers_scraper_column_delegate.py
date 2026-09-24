"""Tests for ScrapersScraperColumnDelegate: the Scrapers table's Scraper column (#278).

**A link cell's text is read from painted pixels' presence, never mocked `QPainter` calls**: unlike
`~.scrapers_row_delegate`'s plain text, this delegate draws through a `QTextDocument`, whose own
internal calls into `QPainter` are not this module's contract to assert against -- only that *something*
was drawn, and that :meth:`link_at` agrees with where.
"""

from PySide6.QtCore import QEvent, QModelIndex, QPointF, QRect, Qt
from PySide6.QtGui import QImage, QMouseEvent, QPainter, QPalette
from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem
from pytest import fixture
from pytest_mock import MockerFixture
from rehuco_agent.scraping.registry import ScraperRow
from rehuco_agent.settings.ui.scrapers_scraper_column_delegate import ScrapersScraperColumnDelegate
from rehuco_agent.settings.ui.scrapers_table_model import SCRAPER_COLUMN, ScrapersTableModel

CELL = QRect(0, 0, 400, 24)

LINKED_ROW = ScraperRow(
    key="rehuco_user_scrapers.art_scraper.ArtScraper",
    label="ArtStation",
    publisher="ArtStation",
    site_name="ArtStation",
    site_url="https://www.artstation.com",
    source="art_scraper.py",
    needs_browser=False,
    error=None,
)
PLAIN_ROW = ScraperRow(
    key=None, label="", publisher="", site_name="", site_url="", source="broken.py", needs_browser=False, error=None
)


@fixture(name="delegate")
def fixture_delegate(qapp: object) -> ScrapersScraperColumnDelegate:
    """The delegate under test; takes ``qapp`` because painting -- even into an offscreen `QImage` --
    needs a `QGuiApplication` to exist first.

    :param qapp: the Qt application fixture.
    :returns: the delegate.
    """
    del qapp
    return ScrapersScraperColumnDelegate()


def index_for(row: ScraperRow) -> tuple[ScrapersTableModel, QModelIndex]:
    """A model and one index over its Scraper cell, for the delegate to paint.

    **Returns the model too**: a `QModelIndex` keeps only a raw pointer back to its source model, so a
    model built and discarded inside this function leaves the index pointing at a destroyed object.

    :param row: the row to show.
    :returns: ``(model, index)``.
    """
    model = ScrapersTableModel()
    model.set_rows((row,))
    return model, model.index(0, SCRAPER_COLUMN)


def option_for() -> QStyleOptionViewItem:
    """A style option over :data:`CELL`, ready to hand to the delegate."""
    option = QStyleOptionViewItem()
    option.rect = CELL
    return option


def new_painter() -> tuple[QImage, QPainter]:
    """An active painter over a throwaway image -- never a bare `QPainter()`, which is unbegun and
    crashed the process outright the one time this suite tried it.

    **Returns the image too**, not just the painter: a `QPainter` keeps only a raw pointer back to the
    `QPaintDevice` it was built on, so an image built and discarded inside this function would be
    garbage-collected the moment it returns, leaving the painter pointing at freed memory.

    :returns: ``(image, painter)``. The caller keeps ``image`` alive (even unused) for as long as
        ``painter`` is used.
    """
    image = QImage(CELL.size(), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    return image, QPainter(image)


def release_at(point: QPointF) -> QMouseEvent:
    """A left-button release event at ``point``, local and global alike -- the six-argument
    `QMouseEvent` overload with an explicit ``globalPos``, since the five-argument one is deprecated."""
    return QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        point,
        point,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


def test_a_non_link_row_is_left_to_the_base_delegate(
    delegate: ScrapersScraperColumnDelegate, mocker: MockerFixture
) -> None:
    """A row with no `site_url` -- a file that loaded no scraper -- is painted by the base delegate,
    not this one's own `QTextDocument` path (#278).

    **Test steps:**

    * paint the Scraper cell of a row with no `site_url`, with the base delegate's own paint spied on
    * verify the base delegate was reached
    """
    base_paint = mocker.patch.object(QStyledItemDelegate, "paint")
    image, painter = new_painter()  # pylint: disable=unused-variable
    model, index = index_for(PLAIN_ROW)  # pylint: disable=unused-variable

    delegate.paint(painter, option_for(), index)
    painter.end()

    base_paint.assert_called_once()


def test_a_linked_row_draws_something_and_never_reaches_the_base_delegate(
    delegate: ScrapersScraperColumnDelegate, mocker: MockerFixture
) -> None:
    """A row with a `site_url` is drawn by this delegate's own `QTextDocument` path -- some non-transparent
    pixel lands in the cell, and the base delegate is never reached (#278).

    **Test steps:**

    * paint the Scraper cell of a row with a `site_url`, with the base delegate's own paint spied on
    * verify the base delegate was never reached, and something was actually drawn
    """
    base_paint = mocker.patch.object(QStyledItemDelegate, "paint")
    image, painter = new_painter()
    model, index = index_for(LINKED_ROW)  # pylint: disable=unused-variable

    delegate.paint(painter, option_for(), index)
    painter.end()

    base_paint.assert_not_called()
    assert any(image.pixelColor(x, CELL.height() // 2).alpha() > 0 for x in range(CELL.width()))


def test_link_at_finds_the_anchor_under_the_drawn_text(delegate: ScrapersScraperColumnDelegate) -> None:
    """`link_at` reports the row's `site_url` for a point actually over the drawn text (#278).

    **Test steps:**

    * ask `link_at` for a point in the middle-left of the cell, where the short label was drawn
    * verify it reports the row's `site_url`
    """
    option = option_for()
    model, index = index_for(LINKED_ROW)  # pylint: disable=unused-variable

    link = delegate.link_at(option, index, QPointF(20, CELL.height() / 2))

    assert link == LINKED_ROW.site_url


def test_link_at_finds_nothing_past_the_texts_end(delegate: ScrapersScraperColumnDelegate) -> None:
    """`link_at` reports nothing for a point in the cell but past where the short label ends (#278).

    **Test steps:**

    * ask `link_at` for a point at the cell's far right, well past "ArtStation"
    * verify it reports no link
    """
    option = option_for()
    model, index = index_for(LINKED_ROW)  # pylint: disable=unused-variable

    link = delegate.link_at(option, index, QPointF(CELL.width() - 2, CELL.height() / 2))

    assert link == ""


def test_link_at_finds_nothing_for_a_non_link_row(delegate: ScrapersScraperColumnDelegate) -> None:
    """`link_at` reports nothing at all for a row with no `site_url` (#278).

    **Test steps:**

    * ask `link_at` for a point over a plain row's cell
    * verify it reports no link
    """
    option = option_for()
    model, index = index_for(PLAIN_ROW)  # pylint: disable=unused-variable

    link = delegate.link_at(option, index, QPointF(20, CELL.height() / 2))

    assert link == ""


def test_a_release_over_the_link_emits_link_activated(delegate: ScrapersScraperColumnDelegate) -> None:
    """A release over the drawn link emits `link_activated` with the row's `site_url`, and reports the
    event handled (#278).

    **Test steps:**

    * build a release event over the drawn text
    * hand it to `editorEvent`, with `link_activated` connected to a spy
    * verify it reports handled and the spy received the URL
    """
    option = option_for()
    model, index = index_for(LINKED_ROW)
    received: list[str] = []
    delegate.link_activated.connect(received.append)
    event = release_at(QPointF(20, CELL.height() / 2))

    handled = delegate.editorEvent(event, model, option, index)

    assert handled is True
    assert received == [LINKED_ROW.site_url]


def test_a_release_past_the_link_does_nothing(delegate: ScrapersScraperColumnDelegate) -> None:
    """A release past where the link's text ends does not emit `link_activated` (#278).

    **Test steps:**

    * build a release event at the cell's far right
    * hand it to `editorEvent`, with `link_activated` connected to a spy
    * verify it reports unhandled and the spy received nothing
    """
    option = option_for()
    model, index = index_for(LINKED_ROW)
    received: list[str] = []
    delegate.link_activated.connect(received.append)
    event = release_at(QPointF(CELL.width() - 2, CELL.height() / 2))

    handled = delegate.editorEvent(event, model, option, index)

    assert handled is False
    assert not received


def test_the_link_is_drawn_in_the_palettes_link_color(delegate: ScrapersScraperColumnDelegate) -> None:
    """The link is colored from the palette's own link role, not a hardcoded one -- consistent with
    `~borco_pyside.widgets.ElidedLabel`'s own rich-text links, and correct across a theme change (#278).

    **Test steps:**

    * give the option a distinct link color
    * paint the linked row's cell
    * verify some drawn pixel is that exact color
    """
    option = option_for()
    option.palette.setColor(QPalette.ColorRole.Link, Qt.GlobalColor.red)  # pylint: disable=no-member
    model, index = index_for(LINKED_ROW)  # pylint: disable=unused-variable
    image, painter = new_painter()

    delegate.paint(painter, option, index)
    painter.end()

    colors = {image.pixelColor(x, y).name() for x in range(CELL.width()) for y in range(CELL.height())}
    assert "#ff0000" in colors


def test_a_non_release_event_falls_through_to_the_base_delegate(
    delegate: ScrapersScraperColumnDelegate, mocker: MockerFixture
) -> None:
    """An event other than a mouse-button release -- e.g. a mouse move, hit while hovering a link cell
    -- is left to the base delegate's own `editorEvent`, not treated as a click (#278).

    **Test steps:**

    * build a move event over the linked row's cell, with the base delegate's own `editorEvent` spied on
    * hand it to `editorEvent`
    * verify the base delegate was reached
    """
    base_event = mocker.patch.object(QStyledItemDelegate, "editorEvent", return_value=False)
    option = option_for()
    model, index = index_for(LINKED_ROW)
    event = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(20, CELL.height() / 2),
        QPointF(20, CELL.height() / 2),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )

    handled = delegate.editorEvent(event, model, option, index)

    base_event.assert_called_once()
    assert handled is False
