"""Tests for the checksum dock's row painting: its selection fill, its Status glyph and its text
(#244, #303).

**Fills and icons are read back from a painted image; text is not**, for the reason
`test_files_row_delegate.py`'s own module docstring gives -- an icon font loaded elsewhere in the same
session can turn plain text into tofu, so every text-drawing claim here mocks
:meth:`QPainter.drawText` instead of trusting the glyphs it asks for to actually rasterize.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFontMetricsF, QImage, QPainter, QPalette
from PySide6.QtWidgets import QStyle, QStyleOptionViewItem
from pytest import fixture, mark
from pytest_mock import MockerFixture
from rehuco_agent.documents.checksum_row_delegate import ChecksumRowDelegate
from rehuco_agent.documents.checksum_rows import (
    DATE_COLUMN,
    PATH_COLUMN,
    STATUS_COLUMN,
    ChecksumRow,
    ChecksumTableModel,
    ModelIndex,
)
from rehuco_agent.documents.files_row_delegate import CHECKSUM_COLUMN_WIDTH, ICON_SIZE, TEXT_PADDING
from rehuco_agent.documents.files_rows import FileChecksumState

DIRECTORY: Final = Path("/fake/library/sculpting")

CELL: Final = QRect(0, 0, 200, 24)
"""The rect a cell is painted into -- one row's worth, wide enough for a glyph and some text."""

INK: Final = QColor("red")
HIGHLIGHT: Final = QColor("green")
HIGHLIGHTED_TEXT: Final = QColor("yellow")

STAMP: Final = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)


def sample(
    name: str = "lesson1.mp4", status: str = "matched", state: FileChecksumState = FileChecksumState.OK
) -> ChecksumRow:
    """One row to draw.

    :param name: the file's record-relative name.
    :param status: the raw recorded status.
    :param state: what the Status column's glyph draws.
    :returns: the row.
    """
    return ChecksumRow(name, status, STAMP, state)


@fixture(name="palette")
def fixture_palette() -> QPalette:
    """A palette whose relevant roles are colours nothing else draws."""
    palette = QPalette()
    palette.setColor(QPalette.ColorGroup.Normal, QPalette.ColorRole.Text, INK)
    palette.setColor(QPalette.ColorRole.Highlight, HIGHLIGHT)
    palette.setColor(QPalette.ColorRole.HighlightedText, HIGHLIGHTED_TEXT)
    return palette


@fixture(name="delegate")
def fixture_delegate(qapp: object) -> ChecksumRowDelegate:
    """A delegate; takes ``qapp`` because recolouring an SVG needs a `QGuiApplication`.

    :param qapp: the Qt application fixture.
    :returns: the delegate.
    """
    del qapp
    return ChecksumRowDelegate()


# the painting/pixel-reading harness below is `test_files_row_delegate.py`'s own, near-verbatim over a
# different row type -- kept as a separate copy rather than shared, this codebase's fake-filesystem
# convention (`test_checksum_rows.py`'s `FakeDisk` is the other instance of it)
# pylint: disable=duplicate-code
def painted(
    delegate: ChecksumRowDelegate, palette: QPalette, row: ChecksumRow | None, column: int, *, selected: bool = False
) -> QImage:
    """Paint one cell and hand back the image it was drawn into.

    :param delegate: the delegate under test.
    :param palette: the palette to draw with.
    :param row: the row to draw, or ``None`` for a model this delegate cannot read.
    :param column: which column's cell to paint.
    :param selected: whether to paint it as a selected row.
    :returns: the image.
    """
    model = ChecksumTableModel()
    if row is not None:
        model.set_rows((row,))
    image = QImage(CELL.size(), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    option = QStyleOptionViewItem()
    option.rect = CELL
    option.palette = palette
    if selected:
        option.state |= QStyle.StateFlag.State_Selected
    painter = QPainter(image)
    try:
        delegate.paint(painter, option, model.index(0, column))
    finally:
        painter.end()
    return image


def colors(image: QImage, rect: QRect | None = None) -> set[str]:
    """Every colour drawn in an image, or in part of one.

    :param image: the painted image.
    :param rect: the part to read, or ``None`` for all of it.
    :returns: the colours as ``#rrggbb`` names; an untouched pixel contributes nothing.
    """
    area = rect or QRect(0, 0, image.width(), image.height())
    return {
        image.pixelColor(x, y).name()
        for y in range(area.top(), area.bottom() + 1)
        for x in range(area.left(), area.right() + 1)
        if image.pixelColor(x, y).alpha() > 0
    }


def ink_columns(image: QImage) -> list[int]:
    """Which columns of an image have anything drawn in them.

    :param image: the painted image.
    :returns: the x positions, ascending.
    """
    return [x for x in range(image.width()) if colors(image, QRect(x, 0, 1, image.height()))]


def ink_rows(image: QImage) -> list[int]:
    """Which rows of an image have anything drawn in them.

    :param image: the painted image.
    :returns: the y positions, ascending.
    """
    return [y for y in range(image.height()) if colors(image, QRect(0, y, image.width(), 1))]


def option_for(palette: QPalette, *, selected: bool = False) -> QStyleOptionViewItem:
    """A style option over :data:`CELL`, ready to hand to the delegate.

    :param palette: the palette to draw with.
    :param selected: whether to mark it as a selected row.
    :returns: the option.
    """
    option = QStyleOptionViewItem()
    option.rect = CELL
    option.palette = palette
    if selected:
        option.state |= QStyle.StateFlag.State_Selected
    return option


def index_for(row: ChecksumRow, column: int) -> tuple[ChecksumTableModel, ModelIndex]:
    """A model and one index over it, for the delegate to paint.

    **Returns the model too**, not just the index -- the same reason
    `test_files_row_delegate.py`'s own ``index_for`` does: a discarded model leaves the index pointing
    at a destroyed C++ object.

    :param row: the row to show.
    :param column: which column's index to return.
    :returns: ``(model, index)``.
    """
    model = ChecksumTableModel()
    model.set_rows((row,))
    return model, model.index(0, column)


def spy_on_draw_text(mocker: MockerFixture, painter: QPainter) -> list[tuple[QColor, QRect, Qt.AlignmentFlag, str]]:
    """Capture every :meth:`QPainter.drawText` call this delegate makes.

    :param mocker: pytest-mock fixture.
    :param painter: the painter the delegate will draw into.
    :returns: the calls made so far, appended to in place -- ``(pen color, rect, flags, text)`` per call.
    """
    calls: list[tuple[QColor, QRect, Qt.AlignmentFlag, str]] = []
    mocker.patch.object(
        QPainter,
        "drawText",
        side_effect=lambda rect, flags, text: calls.append((painter.pen().color(), rect, flags, text)),
    )
    return calls


# pylint: enable=duplicate-code


# region The selection fill


def test_a_selected_row_is_filled_across_the_whole_cell(delegate: ChecksumRowDelegate, palette: QPalette) -> None:
    """The defect this painting exists to fix: the style fills a selected row cell by cell, and with no
    grid between them the result reads as a run of separate boxes rather than one selected row.

    **Test steps:**

    * paint a selected cell
    * verify the highlight reaches opposite corners
    """
    image = painted(delegate, palette, sample(), PATH_COLUMN, selected=True)

    assert image.pixelColor(0, 0).name() == HIGHLIGHT.name()
    assert image.pixelColor(CELL.width() - 1, CELL.height() - 1).name() == HIGHLIGHT.name()


# these two mirror `test_files_row_delegate.py`'s pair near-verbatim -- the same convention as the
# painting harness above, over a row with no disabled state to fold in
# pylint: disable=duplicate-code
def test_a_selected_rows_content_is_drawn_in_the_highlighted_pen(
    delegate: ChecksumRowDelegate, palette: QPalette, mocker: MockerFixture
) -> None:
    """Filled and then drawn over, in the colour the palette pairs with that fill.

    **Test steps:**

    * paint a selected text cell, capturing the pen live at the moment text is drawn
    * verify the pen was the highlighted-text colour, never the ordinary ink
    """
    image = QImage(CELL.size(), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    calls = spy_on_draw_text(mocker, painter)

    model, index = index_for(sample(), PATH_COLUMN)  # pylint: disable=unused-variable
    delegate.paint(painter, option_for(palette, selected=True), index)
    painter.end()

    pens = [pen for pen, *_ in calls]
    assert pens == [HIGHLIGHTED_TEXT]
    assert INK not in pens


def test_an_unselected_row_fills_nothing(
    delegate: ChecksumRowDelegate, palette: QPalette, mocker: MockerFixture
) -> None:
    """The view's own background shows through, which is what lets the table stay banded.

    **Test steps:**

    * paint an unselected cell, capturing the pen its text was drawn with
    * verify the corner stayed untouched and the text's pen was the ordinary ink
    """
    image = QImage(CELL.size(), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    calls = spy_on_draw_text(mocker, painter)

    model, index = index_for(sample(), PATH_COLUMN)  # pylint: disable=unused-variable
    delegate.paint(painter, option_for(palette), index)
    painter.end()

    assert image.pixelColor(0, 0).alpha() == 0
    assert [pen for pen, *_ in calls] == [INK]


# pylint: enable=duplicate-code


# endregion


# region The Status glyph


def test_the_status_glyph_is_centred_vertically(delegate: ChecksumRowDelegate, palette: QPalette) -> None:
    """What the base delegate could not do for a column with no text to place a decoration relative to.

    **Test steps:**

    * paint the Status cell
    * verify what was drawn is centred in the cell's height, to within a pixel
    """
    rows = ink_rows(painted(delegate, palette, sample(), STATUS_COLUMN))

    assert rows
    assert abs((rows[0] + rows[-1]) / 2 - (CELL.height() - 1) / 2) <= 1


def test_the_status_glyph_is_centred_horizontally(delegate: ChecksumRowDelegate, palette: QPalette) -> None:
    """Its column has no title and no text, so a left-aligned lone glyph would sit under the edge of
    the column beside it.

    **Test steps:**

    * paint the Status cell
    * verify what was drawn is centred in the cell's width
    """
    columns = ink_columns(painted(delegate, palette, sample(), STATUS_COLUMN))

    assert columns
    assert abs((columns[0] + columns[-1]) / 2 - (CELL.width() - 1) / 2) <= 1


def test_no_claim_draws_no_glyph(delegate: ChecksumRowDelegate, palette: QPalette) -> None:
    """An unreadable record leaves every row with no claim at all, which is an empty cell rather than a
    drawing of nothing -- the same answer the file browser gives (#303).

    **Test steps:**

    * paint the Status cell of a row with no claim
    * verify nothing was drawn
    """
    assert colors(painted(delegate, palette, sample(state=FileChecksumState.NONE), STATUS_COLUMN)) == set()


@mark.parametrize(
    "state",
    [
        FileChecksumState.MISSING,
        FileChecksumState.OK,
        FileChecksumState.BAD,
        FileChecksumState.OLD_OK,
        FileChecksumState.OLD_BAD,
        FileChecksumState.UNEXPECTED,
        FileChecksumState.MALFORMED,
    ],
)
def test_every_checksum_state_draws_a_glyph(
    delegate: ChecksumRowDelegate, palette: QPalette, state: FileChecksumState
) -> None:
    """The seven the column can draw -- the same set the file browser's own checksum column reports
    (#303) -- each drawn, so a verdict with no glyph would read as no verdict.

    **Test steps:**

    * paint the Status cell of a row carrying each state
    * verify something was drawn
    """
    assert colors(painted(delegate, palette, sample(state=state), STATUS_COLUMN))


# endregion


# region Text and sizing


def test_the_path_column_draws_its_name(
    delegate: ChecksumRowDelegate, palette: QPalette, mocker: MockerFixture
) -> None:
    """The File column is plain text -- no glyph of its own, unlike the browser's Name column.

    **Test steps:**

    * paint the File cell, capturing what it was drawn with
    * verify the row's name was drawn, left-aligned
    """
    image = QImage(CELL.size(), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    calls = spy_on_draw_text(mocker, painter)

    model, index = index_for(sample("lesson1.mp4"), PATH_COLUMN)  # pylint: disable=unused-variable
    delegate.paint(painter, option_for(palette), index)
    painter.end()

    assert len(calls) == 1
    _pen, _rect, flags, text = calls[0]
    assert text == "lesson1.mp4"
    assert flags & Qt.AlignmentFlag.AlignLeft


def test_a_name_too_long_for_its_cell_is_elided_rather_than_clipped(
    delegate: ChecksumRowDelegate, palette: QPalette, mocker: MockerFixture
) -> None:
    """A truncated name ends in an ellipsis the reader can see, not at whatever pixel the cell ran out
    at.

    **Test steps:**

    * paint a name far longer than the cell, capturing the string it was actually drawn with
    * verify that string is shorter than the original
    """
    long_name = "extras/ArtStation_-_100_MultiPurpose_Imperfection_-_VOL_04.part1.rar" * 3
    image = QImage(CELL.size(), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    calls = spy_on_draw_text(mocker, painter)

    model, index = index_for(sample(long_name), PATH_COLUMN)  # pylint: disable=unused-variable
    delegate.paint(painter, option_for(palette), index)
    painter.end()

    assert len(calls) == 1
    _pen, _rect, _flags, elided = calls[0]
    assert elided != long_name
    assert len(elided) < len(long_name)


def test_the_status_column_is_sized_for_its_glyph(delegate: ChecksumRowDelegate) -> None:
    """Its title is deliberately empty, so there is nothing for it to be sized for but the glyph.

    **Test steps:**

    * ask for the Status cell's hint and the Checked cell's
    * verify only the first is the fixed glyph width
    """
    model = ChecksumTableModel()
    model.set_rows((sample(),))
    option = QStyleOptionViewItem()

    status = delegate.sizeHint(option, model.index(0, STATUS_COLUMN))
    date = delegate.sizeHint(option, model.index(0, DATE_COLUMN))

    assert status.width() == CHECKSUM_COLUMN_WIDTH
    assert status.height() == ICON_SIZE
    assert date.width() != CHECKSUM_COLUMN_WIDTH


@mark.parametrize(("column", "text"), [(PATH_COLUMN, "lesson1.mp4"), (DATE_COLUMN, None)], ids=["path", "date"])
def test_every_text_column_asks_for_the_padding_it_draws_with(
    delegate: ChecksumRowDelegate, column: int, text: str | None
) -> None:
    """The regression this guards, the same one `test_files_row_delegate.py`'s own version of this test
    documents: the base class sizes text against the *style*'s margin while this delegate insets it by
    :data:`~rehuco_agent.documents.files_row_delegate.TEXT_PADDING` a side.

    **Test steps:**

    * ask for each text column's hint over a row whose text is known
    * verify the hint minus the padding still covers what that text measures
    """
    model, index = index_for(sample("lesson1.mp4"), column)  # pylint: disable=unused-variable
    option = QStyleOptionViewItem()
    drawn = text if text is not None else str(index.data())
    assert drawn

    hint = delegate.sizeHint(option, index)

    available = hint.width() - 2 * TEXT_PADDING
    assert available >= QFontMetricsF(option.font).horizontalAdvance(drawn)


def test_the_checked_columns_hint_does_not_depend_on_the_row_shown(delegate: ChecksumRowDelegate) -> None:
    """Unlike File, whose width follows what is actually in the table, Checked's is a property of the
    *format* -- the same fix :class:`~rehuco_agent.documents.files_row_delegate.FilesRowDelegate`'s own
    Modified column carries, reused rather than reimplemented here.

    **Test steps:**

    * ask for the hint against two rows with different recorded timestamps
    * verify the two hints are identical
    """
    early = sample()
    late = ChecksumRow("lesson1.mp4", "matched", datetime(2020, 1, 1, 0, 0, tzinfo=UTC), FileChecksumState.OK)
    option = QStyleOptionViewItem()

    model = ChecksumTableModel()
    model.set_rows((early,))
    first = delegate.sizeHint(option, model.index(0, DATE_COLUMN))
    model.set_rows((late,))
    second = delegate.sizeHint(option, model.index(0, DATE_COLUMN))

    assert first == second


def test_a_foreign_model_is_left_to_the_base_delegate(delegate: ChecksumRowDelegate, palette: QPalette) -> None:
    """The deference this delegate shows a model it may not own: a row it cannot read is drawn by the
    style rather than half-drawn by this.

    **Test steps:**

    * paint a cell of a model holding no rows at all
    * verify none of this delegate's own ink appeared
    """
    assert INK.name() not in colors(painted(delegate, palette, None, PATH_COLUMN))


# endregion
