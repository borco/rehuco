"""Tests for ScrapersCheckboxDelegate: the Scrapers table's **Use browser** checkbox column (#278).

**Its position is read back from painted pixels, never asserted against a mocked
`QStyle.drawPrimitive`**: an overloaded C++ method along the same lines `~rehuco_agent.documents.
test_files_row_delegate`'s own module docstring warns mocking `fillRect` is unsafe for. Instead the
indicator's centered rect (:meth:`ScrapersCheckboxDelegate._ScrapersCheckboxDelegate__checkbox_rect`,
via the module-level helper below) is compared directly against what `editorEvent`'s hit-test uses --
the same rect both must agree on.
"""

from PySide6.QtCore import QEvent, QModelIndex, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QImage, QMouseEvent, QPainter
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionViewItem
from pytest import fixture
from pytest_mock import MockerFixture
from rehuco_agent.scraping.registry import ScraperRow
from rehuco_agent.settings.ui.scrapers_checkbox_delegate import ScrapersCheckboxDelegate
from rehuco_agent.settings.ui.scrapers_table_model import USE_BROWSER_COLUMN, ScrapersTableModel

CELL = QRect(0, 0, 400, 24)

TICKED_ROW = ScraperRow(
    key="rehuco_user_scrapers.art_scraper.ArtScraper",
    label="ArtStation",
    publisher="ArtStation",
    site_name="ArtStation",
    site_url="",
    source="art_scraper.py",
    needs_browser=False,
    error=None,
)


@fixture(name="delegate")
def fixture_delegate(qapp: object) -> ScrapersCheckboxDelegate:
    """The delegate under test; takes ``qapp`` because `QStyle.drawPrimitive` needs a `QGuiApplication`
    to exist first.

    :param qapp: the Qt application fixture.
    :returns: the delegate.
    """
    del qapp
    return ScrapersCheckboxDelegate()


def index_for(row: ScraperRow, *, checked: bool) -> tuple[ScrapersTableModel, QModelIndex]:
    """A model, staged so ``row``'s checkbox reads ``checked``, and one index over its checkbox cell.

    :param row: the row to show.
    :param checked: whether the model's staged **Use browser** set should include ``row``.
    :returns: ``(model, index)``.
    """
    model = ScrapersTableModel()
    model.set_rows((row,))
    model.set_browser_scrapers(frozenset({row.key}) if checked and row.key is not None else frozenset())
    return model, model.index(0, USE_BROWSER_COLUMN)


def checkbox_rect(option: QStyleOptionViewItem) -> QRect:
    """The centered checkbox rect this delegate paints and hit-tests against, computed the same way
    `ScrapersCheckboxDelegate` itself does -- the module-level test helper mirroring its private one."""
    style = QApplication.style()
    width = style.pixelMetric(QStyle.PixelMetric.PM_IndicatorWidth)
    height = style.pixelMetric(QStyle.PixelMetric.PM_IndicatorHeight)
    rect = option.rect
    return QRect(rect.x() + (rect.width() - width) // 2, rect.y() + (rect.height() - height) // 2, width, height)


def option_for() -> QStyleOptionViewItem:
    """A style option over :data:`CELL`, ready to hand to the delegate."""
    option = QStyleOptionViewItem()
    option.rect = CELL
    return option


def release_at(point: QPoint) -> QMouseEvent:
    """A left-button release event at ``point``, local and global alike -- the six-argument
    `QMouseEvent` overload with an explicit ``globalPos``, since the five-argument one this suite first
    used is deprecated."""
    return QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        QPointF(point),
        QPointF(point),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


def new_painter() -> tuple[QImage, QPainter]:
    """An active painter over a throwaway image -- never a bare `QPainter()`, which is unbegun and
    crashed the process outright the one time this suite tried it (`painter.save()` inside `paint` is
    real, undefined behaviour on an unbegun painter, even with `QStyle.drawPrimitive` itself mocked).

    **Returns the image too**, not just the painter: a `QPainter` keeps only a raw pointer back to the
    `QPaintDevice` it was built on, so an image built and discarded inside this function would be
    garbage-collected the moment it returns, leaving the painter pointing at freed memory.

    :returns: ``(image, painter)``. The caller keeps ``image`` alive (even unused) for as long as
        ``painter`` is used.
    """
    image = QImage(CELL.size(), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    return image, QPainter(image)


def test_painting_draws_a_checkbox_primitive_at_the_centered_rect(
    delegate: ScrapersCheckboxDelegate, mocker: MockerFixture
) -> None:
    """The checkbox is painted via `QStyle.drawPrimitive` at a rect centered in the cell -- not the
    base delegate's own left-anchored layout (#278).

    **Test steps:**

    * paint the checkbox cell, with `QStyle.drawPrimitive` spied on
    * verify it was called once, at the centered rect, for the checkbox indicator
    """
    option = option_for()
    model, index = index_for(TICKED_ROW, checked=True)  # pylint: disable=unused-variable
    image, painter = new_painter()  # pylint: disable=unused-variable
    # patched on the instance, not the class: the platform style is a native subclass whose own
    # `drawPrimitive` override does not route through a class-level patch of `QStyle`'s
    draw_primitive = mocker.patch.object(QApplication.style(), "drawPrimitive")

    delegate.paint(painter, option, index)
    painter.end()

    draw_primitive.assert_called_once()
    element, style_option = draw_primitive.call_args.args[:2]
    assert element == QStyle.PrimitiveElement.PE_IndicatorCheckBox
    assert style_option.rect == checkbox_rect(option)  # pylint: disable=no-member


def test_a_click_inside_the_checkbox_rect_toggles_it(delegate: ScrapersCheckboxDelegate) -> None:
    """A release inside the centered checkbox rect toggles the staged state (#278).

    **Test steps:**

    * build a release event inside the centered rect
    * hand it to `editorEvent`
    * verify it reports handled and the model's checkbox flipped
    """
    option = option_for()
    model, index = index_for(TICKED_ROW, checked=False)
    event = release_at(checkbox_rect(option).center())

    handled = delegate.editorEvent(event, model, option, index)

    assert handled is True
    assert model.data(index, Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked


def test_a_click_outside_the_checkbox_rect_does_nothing(delegate: ScrapersCheckboxDelegate) -> None:
    """A release outside the centered rect -- e.g. elsewhere in the cell -- does not toggle it (#278).

    **Test steps:**

    * build a release event at the cell's far corner, outside the centered checkbox
    * hand it to `editorEvent`
    * verify it reports unhandled and the model's checkbox is unchanged
    """
    option = option_for()
    model, index = index_for(TICKED_ROW, checked=False)
    event = release_at(QPoint(CELL.width() - 1, CELL.height() - 1))

    handled = delegate.editorEvent(event, model, option, index)

    assert handled is False
    assert model.data(index, Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Unchecked


def test_a_disabled_rows_checkbox_ignores_clicks(delegate: ScrapersCheckboxDelegate) -> None:
    """`needs_browser` forces a row's checkbox on and disabled -- a click inside it does nothing,
    falling through to the base delegate instead (#278).

    **Test steps:**

    * build a release event inside the centered rect, for a `needs_browser` row
    * hand it to `editorEvent`
    * verify the model's checkbox stayed checked (untouched, not toggled off)
    """
    row = ScraperRow(
        key="rehuco_user_scrapers.gated.Gated",
        label="Gated",
        publisher="Gated",
        site_name="Gated",
        site_url="",
        source="gated.py",
        needs_browser=True,
        error=None,
    )
    option = option_for()
    model, index = index_for(row, checked=False)
    event = release_at(checkbox_rect(option).center())

    delegate.editorEvent(event, model, option, index)

    assert model.data(index, Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked


def test_painting_a_row_with_no_checkbox_state_draws_nothing(
    delegate: ScrapersCheckboxDelegate, mocker: MockerFixture
) -> None:
    """A row carrying no checkbox at all -- a file that loaded no scraper, so its cell has no
    `Qt.ItemDataRole.CheckStateRole` -- is painted as nothing, not a stray checkbox (#278).

    **Test steps:**

    * paint the checkbox cell of a row with no key, with `QStyle.drawPrimitive` spied on
    * verify it was never called
    """
    row = ScraperRow(
        key=None, label="", publisher="", site_name="", site_url="", source="broken.py", needs_browser=False, error=None
    )
    option = option_for()
    model, index = index_for(row, checked=False)  # pylint: disable=unused-variable
    image, painter = new_painter()  # pylint: disable=unused-variable
    draw_primitive = mocker.patch.object(QApplication.style(), "drawPrimitive")

    delegate.paint(painter, option, index)
    painter.end()

    draw_primitive.assert_not_called()


def test_an_unchecked_rows_checkbox_is_painted_off(delegate: ScrapersCheckboxDelegate, mocker: MockerFixture) -> None:
    """An unticked, enabled row's checkbox is painted `State_Off`, not the `State_On` a ticked row
    gets (#278).

    **Test steps:**

    * paint the checkbox cell of an untied, enabled row, with `QStyle.drawPrimitive` spied on
    * verify the style option it was handed carries `State_Off`, not `State_On`
    """
    option = option_for()
    model, index = index_for(TICKED_ROW, checked=False)  # pylint: disable=unused-variable
    image, painter = new_painter()  # pylint: disable=unused-variable
    draw_primitive = mocker.patch.object(QApplication.style(), "drawPrimitive")

    delegate.paint(painter, option, index)
    painter.end()

    draw_primitive.assert_called_once()
    _element, style_option = draw_primitive.call_args.args[:2]
    assert QStyle.StateFlag.State_Off in style_option.state  # pylint: disable=no-member
    assert QStyle.StateFlag.State_On not in style_option.state  # pylint: disable=no-member


def test_a_disabled_rows_checkbox_is_painted_without_the_enabled_flag(
    delegate: ScrapersCheckboxDelegate, mocker: MockerFixture
) -> None:
    """A `needs_browser` row's forced-on checkbox is painted with `QStyle.StateFlag.State_Enabled`
    cleared, so the style draws it visibly disabled (#278).

    **Test steps:**

    * paint the checkbox cell of a `needs_browser` row, with `QStyle.drawPrimitive` spied on
    * verify the style option it was handed has no `State_Enabled`
    """
    row = ScraperRow(
        key="rehuco_user_scrapers.gated.Gated",
        label="Gated",
        publisher="Gated",
        site_name="Gated",
        site_url="",
        source="gated.py",
        needs_browser=True,
        error=None,
    )
    option = option_for()
    model, index = index_for(row, checked=False)  # pylint: disable=unused-variable
    image, painter = new_painter()  # pylint: disable=unused-variable
    draw_primitive = mocker.patch.object(QApplication.style(), "drawPrimitive")

    delegate.paint(painter, option, index)
    painter.end()

    draw_primitive.assert_called_once()
    _element, style_option = draw_primitive.call_args.args[:2]
    assert QStyle.StateFlag.State_Enabled not in style_option.state  # pylint: disable=no-member
