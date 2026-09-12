"""Tests for the file browser's row painting: its selection fill, its glyphs and its text (#266).

Painted into an off-screen image and read back, because that is where the claims live: the delegate
draws rather than annotating a style option, so what it drew is what there is to assert. The palette's
roles are set to four colours nothing else here draws, which is what lets a pixel name its source.
"""

from pathlib import Path
from typing import Final

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPalette
from PySide6.QtWidgets import QStyle, QStyleOptionViewItem
from pytest import fixture, mark
from rehuco_agent.documents.files_row_delegate import CHECKSUM_COLUMN_WIDTH, ICON_SIZE, FilesRowDelegate
from rehuco_agent.documents.files_rows import (
    CHECKSUM_COLUMN,
    KIND_COLUMN,
    MODIFIED_COLUMN,
    NAME_COLUMN,
    PARENT_ROW_NAME,
    SIZE_COLUMN,
    FileChecksumState,
    FileRow,
    FilesTableModel,
)
from rehuco_core import FileKind, FileType

DIRECTORY: Final = Path("/fake/library/sculpting")

CELL: Final = QRect(0, 0, 200, 24)
"""The rect a cell is painted into -- one row's worth, wide enough for a glyph and some text."""

INK: Final = QColor("red")
DIM: Final = QColor("blue")
HIGHLIGHT: Final = QColor("green")
HIGHLIGHTED_TEXT: Final = QColor("yellow")


def sample(
    name: str = "lesson01.mp4",
    file_type: FileType = FileType.VIDEO,
    state: FileChecksumState = FileChecksumState.NONE,
    *,
    enabled: bool = True,
) -> FileRow:
    """One row to draw.

    :param name: the file name.
    :param file_type: what it is by shape, which picks the Name column's glyph.
    :param state: what the record claims, which picks the checksum column's.
    :param enabled: whether a reader may act on it.
    :returns: the row, carrying a size and a time so every text column has something to draw.
    """
    return FileRow(
        name=name,
        path=DIRECTORY / name,
        kind=FileKind.CONTENT,
        file_type=file_type,
        checksum_state=state,
        size=14_800_000,
        modified=1_700_000_000.0,
        enabled=enabled,
    )


@fixture(name="palette")
def fixture_palette() -> QPalette:
    """A palette whose four roles are four colours nothing else draws."""
    palette = QPalette()
    palette.setColor(QPalette.ColorGroup.Normal, QPalette.ColorRole.Text, INK)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, DIM)
    palette.setColor(QPalette.ColorRole.Highlight, HIGHLIGHT)
    palette.setColor(QPalette.ColorRole.HighlightedText, HIGHLIGHTED_TEXT)
    return palette


@fixture(name="delegate")
def fixture_delegate(qapp: object) -> FilesRowDelegate:
    """A delegate; takes ``qapp`` because recolouring an SVG needs a `QGuiApplication`.

    :param qapp: the Qt application fixture.
    :returns: the delegate.
    """
    del qapp
    return FilesRowDelegate()


def painted(
    delegate: FilesRowDelegate,
    palette: QPalette,
    row: FileRow | None,
    column: int,
    *,
    selected: bool = False,
) -> QImage:
    """Paint one cell and hand back the image it was drawn into.

    :param delegate: the delegate under test.
    :param palette: the palette to draw with.
    :param row: the row to draw, or ``None`` for a model this delegate cannot read.
    :param column: which column's cell to paint.
    :param selected: whether to paint it as a selected row.
    :returns: the image.
    """
    model = FilesTableModel()
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


# region The selection fill


def test_a_selected_row_is_filled_across_the_whole_cell(delegate: FilesRowDelegate, palette: QPalette) -> None:
    """The defect this painting exists to fix: the style fills a selected row cell by cell, and with no
    grid between them the result reads as a run of separate boxes rather than one selected row.

    **Test steps:**

    * paint a selected cell
    * verify the highlight reaches opposite corners
    """
    image = painted(delegate, palette, sample(), KIND_COLUMN, selected=True)

    assert image.pixelColor(0, 0).name() == HIGHLIGHT.name()
    assert image.pixelColor(CELL.width() - 1, CELL.height() - 1).name() == HIGHLIGHT.name()


def test_a_selected_rows_content_is_drawn_in_the_highlighted_pen(delegate: FilesRowDelegate, palette: QPalette) -> None:
    """Filled and then drawn over, in the colour the palette pairs with that fill -- so the text stays
    legible against it rather than keeping the unselected ink.

    **Test steps:**

    * paint a selected text cell
    * verify its content is the highlighted-text colour and none of the ordinary ink is left
    """
    found = colors(painted(delegate, palette, sample(), KIND_COLUMN, selected=True))

    assert HIGHLIGHTED_TEXT.name() in found
    assert INK.name() not in found


def test_an_unselected_row_fills_nothing(delegate: FilesRowDelegate, palette: QPalette) -> None:
    """The view's own background shows through, which is what lets the table stay banded.

    **Test steps:**

    * paint an unselected cell
    * verify the corner is untouched and the content is the ordinary ink
    """
    image = painted(delegate, palette, sample(), KIND_COLUMN)

    assert image.pixelColor(0, 0).alpha() == 0
    assert INK.name() in colors(image)


# endregion


# region Where the glyphs go


@mark.parametrize("column", [NAME_COLUMN, CHECKSUM_COLUMN])
def test_a_glyph_is_centred_vertically_in_its_row(delegate: FilesRowDelegate, palette: QPalette, column: int) -> None:
    """Both columns' glyphs sit on one line, which is what the base delegate could not do for the
    checksum column: with no text to be placed relative to, it left the decoration wherever an empty
    string put it.

    **Test steps:**

    * paint each glyph column, with a name of one space so only the glyph draws
    * verify what was drawn is centred in the cell's height, to within a pixel
    """
    image = painted(delegate, palette, sample(" ", state=FileChecksumState.OK), column)
    rows = ink_rows(image)

    assert rows
    assert abs((rows[0] + rows[-1]) / 2 - (CELL.height() - 1) / 2) <= 1


def test_the_checksum_glyph_is_centred_horizontally(delegate: FilesRowDelegate, palette: QPalette) -> None:
    """Its column has no title and no text, so a left-aligned lone glyph would sit under the edge of
    the column beside it.

    **Test steps:**

    * paint the checksum cell
    * verify what was drawn is centred in the cell's width
    """
    columns = ink_columns(painted(delegate, palette, sample(state=FileChecksumState.BAD), CHECKSUM_COLUMN))

    assert columns
    assert abs((columns[0] + columns[-1]) / 2 - (CELL.width() - 1) / 2) <= 1


def test_no_claim_draws_no_glyph(delegate: FilesRowDelegate, palette: QPalette) -> None:
    """An empty cell is the absence of a drawing rather than a drawing of nothing: this record says
    nothing about a sidecar, a folder or another resource's content (#266).

    **Test steps:**

    * paint the checksum cell of a row with no claim
    * verify nothing was drawn
    """
    assert colors(painted(delegate, palette, sample(), CHECKSUM_COLUMN)) == set()


def test_the_name_column_draws_its_glyph_before_its_text(delegate: FilesRowDelegate, palette: QPalette) -> None:
    """The name is inset past the glyph rather than drawn over it, which is the one thing a decoration
    and a text sharing a cell have to agree about.

    **Test steps:**

    * paint the Name cell
    * verify ink appears both inside the glyph's slot and beyond it
    """
    image = painted(delegate, palette, sample(), NAME_COLUMN)

    assert colors(image, QRect(0, 0, ICON_SIZE + 4, CELL.height()))
    assert colors(image, QRect(ICON_SIZE + 8, 0, CELL.width() - ICON_SIZE - 8, CELL.height()))


def test_the_way_out_is_drawn_apart_from_the_folders_it_sits_above(
    delegate: FilesRowDelegate, palette: QPalette
) -> None:
    """``..`` wears the parent-folder glyph the toolbar's Up action does, the two being one act reached
    two ways -- and not the plain folder glyph every real folder row wears, which is what it would be
    confused with.

    Compared as two images rather than by naming a resource path: what matters is that a reader can tell
    the way out from a folder to go into.

    **Test steps:**

    * paint the Name cell of the ``..`` row and of a real folder row, each with no name text
    * verify the two glyphs differ
    """
    parent = sample(PARENT_ROW_NAME, FileType.DIRECTORY)
    folder = sample(" ", FileType.DIRECTORY)
    slot = QRect(0, 0, ICON_SIZE + 4, CELL.height())

    drawn_parent = painted(delegate, palette, parent, NAME_COLUMN).copy(slot)
    drawn_folder = painted(delegate, palette, folder, NAME_COLUMN).copy(slot)

    assert colors(drawn_parent) and colors(drawn_folder)
    assert drawn_parent != drawn_folder


@mark.parametrize(
    "file_type",
    [
        FileType.DIRECTORY,
        FileType.RECORD,
        FileType.MANIFEST,
        FileType.BACKUP,
        FileType.IMAGE,
        FileType.VIDEO,
        FileType.AUDIO,
        FileType.ARCHIVE,
        FileType.GENERIC,
    ],
)
def test_every_file_type_draws_a_glyph(delegate: FilesRowDelegate, palette: QPalette, file_type: FileType) -> None:
    """All nine are present, so no row is drawn with a blank where a type glyph should be -- which is
    how a reader picks a video out of two hundred files.

    **Test steps:**

    * paint the Name cell of a row of each type, with a name of one space so only the glyph draws
    * verify something was drawn in the glyph's slot
    """
    image = painted(delegate, palette, sample(" ", file_type), NAME_COLUMN)

    assert colors(image, QRect(0, 0, ICON_SIZE + 4, CELL.height()))


@mark.parametrize(
    "state",
    [
        FileChecksumState.MISSING,
        FileChecksumState.OK,
        FileChecksumState.BAD,
        FileChecksumState.OLD_OK,
        FileChecksumState.OLD_BAD,
    ],
)
def test_every_checksum_verdict_draws_a_glyph(
    delegate: FilesRowDelegate, palette: QPalette, state: FileChecksumState
) -> None:
    """The five the column can report, each drawn -- a verdict with no glyph would read as no verdict.

    **Test steps:**

    * paint the checksum cell of a row carrying each state
    * verify something was drawn
    """
    assert colors(painted(delegate, palette, sample(state=state), CHECKSUM_COLUMN))


# endregion


# region The disabled row


def test_a_disabled_rows_content_is_drawn_in_the_disabled_pen(delegate: FilesRowDelegate, palette: QPalette) -> None:
    """A row a reader may not act on dims -- glyph and text together, because both take the row's own
    pen and the pen is chosen from the row's flags (#266).

    **Test steps:**

    * paint the Name cell of a disabled row
    * verify everything drawn is the disabled colour
    """
    assert colors(painted(delegate, palette, sample(enabled=False), NAME_COLUMN)) == {DIM.name()}


def test_a_disabled_row_still_reads_as_selected_when_it_is(delegate: FilesRowDelegate, palette: QPalette) -> None:
    """Selection wins over the dimming: a caller that selects a disabled row must not get a row filled
    with highlight and drawn in a colour chosen against the unselected background.

    **Test steps:**

    * paint a selected, disabled cell
    * verify the fill and the highlighted pen were used and the dim colour was not
    """
    found = colors(painted(delegate, palette, sample(enabled=False), KIND_COLUMN, selected=True))

    assert HIGHLIGHT.name() in found
    assert HIGHLIGHTED_TEXT.name() in found
    assert DIM.name() not in found


# endregion


# region Text and sizing


def test_the_size_column_is_right_aligned(delegate: FilesRowDelegate, palette: QPalette) -> None:
    """Digits line up on their units, which is the point of a size column; every other text column
    starts at the left.

    **Test steps:**

    * paint the Size cell and the Kind cell
    * verify the size's ink sits in the cell's right half and the kind's starts in its left
    """
    size = ink_columns(painted(delegate, palette, sample(), SIZE_COLUMN))
    kind = ink_columns(painted(delegate, palette, sample(), KIND_COLUMN))

    assert size and kind
    assert size[-1] > CELL.width() // 2
    assert kind[0] < CELL.width() // 2


def test_a_name_too_long_for_its_cell_is_elided_rather_than_clipped(
    delegate: FilesRowDelegate, palette: QPalette
) -> None:
    """A truncated name ends in an ellipsis the reader can see, not at whatever pixel the cell ran out
    at.

    **Test steps:**

    * paint a name far longer than the cell
    * verify the ink stops inside the cell rather than running to its edge
    """
    long_name = "ArtStation_-_100_MultiPurpose_Imperfection_-_VOL_04.part1.rar" * 3
    columns = ink_columns(painted(delegate, palette, sample(long_name), NAME_COLUMN))

    assert columns
    assert columns[-1] < CELL.width() - 1


def test_the_checksum_column_is_sized_for_its_glyph(delegate: FilesRowDelegate) -> None:
    """Its title is deliberately empty, so there is nothing for it to be sized for but the glyph --
    unlike the task queue's State column, which had to be sized for its header (#248).

    **Test steps:**

    * ask for the checksum cell's hint and the Modified cell's
    * verify only the first is the fixed glyph width
    """
    model = FilesTableModel()
    model.set_rows((sample(),))
    option = QStyleOptionViewItem()

    checksum = delegate.sizeHint(option, model.index(0, CHECKSUM_COLUMN))
    modified = delegate.sizeHint(option, model.index(0, MODIFIED_COLUMN))

    assert checksum.width() == CHECKSUM_COLUMN_WIDTH
    assert modified.width() != CHECKSUM_COLUMN_WIDTH


def test_the_name_column_asks_for_room_for_its_glyph_as_well(delegate: FilesRowDelegate) -> None:
    """The base measures the text alone, and a hint that forgot the glyph would size the column to
    elide every name by exactly one icon's width.

    **Test steps:**

    * ask for the Name cell's hint and the Kind cell's over the same text
    * verify the Name hint is wider by at least the glyph
    """
    model = FilesTableModel()
    model.set_rows((sample("content"),))
    option = QStyleOptionViewItem()

    name = delegate.sizeHint(option, model.index(0, NAME_COLUMN))
    kind = delegate.sizeHint(option, model.index(0, KIND_COLUMN))

    assert name.width() > kind.width() + ICON_SIZE


def test_a_foreign_model_is_left_to_the_base_delegate(delegate: FilesRowDelegate, palette: QPalette) -> None:
    """The deference every delegate here shows a model it may not own: a row it cannot read is drawn by
    the style rather than half-drawn by this.

    **Test steps:**

    * paint a cell of a model holding no rows at all
    * verify none of this delegate's own ink appeared
    """
    assert INK.name() not in colors(painted(delegate, palette, None, NAME_COLUMN))


# endregion
