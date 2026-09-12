"""Tests for the file browser's row painting: its selection fill, its glyphs and its text (#266).

**Fills and icons are read back from a painted image; text is not.** A fill (``fillRect``, a solid
colour) and an SVG icon (rasterized vector paths) render the same regardless of which fonts happen to
be loaded, so those claims are checked by painting into an off-screen image and reading its pixels back,
the same way `test_the_way_out_is_drawn_apart_from_the_folders_it_sits_above` compares two whole images.

A font glyph is not so reliable a witness. ``borco_pyside``'s theming tests load a real icon font into
the offscreen platform's font database, which starts out empty -- and once that happens, that icon font
becomes the *fallback* for ordinary Latin text too, for the rest of the process
(``borco_pyside_tests/theming/conftest.py``'s own warning on ``real_font_family``, unfixable and
untestable in isolation). An icon font's glyph table has no reason to define ``a``-``z``, so plain text
can render as nothing at all once some other package's test in the same session has loaded one -- which
`test_task_row_delegate.py` hit first and fixed the same way this file now does: never read pixels back
for *text*. Every text-drawing claim here mocks :meth:`QPainter.drawText` instead and asserts on what it
was called with -- the pen at the moment of the call, the rect, the alignment, the string -- which is
true whether or not that string could ever actually be rasterized in whatever font this test happened to
run after.
"""

from pathlib import Path
from typing import Final

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFontMetricsF, QImage, QPainter, QPalette
from PySide6.QtWidgets import QStyle, QStyleOptionViewItem
from pytest import fixture, mark
from pytest_mock import MockerFixture
from rehuco_agent.documents.files_row_delegate import (
    CHECKSUM_COLUMN_WIDTH,
    ICON_SIZE,
    TEXT_PADDING,
    FilesRowDelegate,
)
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
    ModelIndex,
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


def index_for(row: FileRow, column: int) -> tuple[FilesTableModel, ModelIndex]:
    """A model and one index over it, for the delegate to paint.

    **Returns the model too**, not just the index: a ``QModelIndex`` keeps only a raw pointer back to
    its source model, so a model built and discarded inside this function would be garbage-collected the
    moment it returns, leaving the index pointing at a destroyed C++ object -- confirmed the hard way, as
    an access violation the very next time anything touched it. The caller keeps ``model`` alive by
    holding the tuple, or at least its first element, for as long as the index is used.

    :param row: the row to show.
    :param column: which column's index to return.
    :returns: ``(model, index)``.
    """
    model = FilesTableModel()
    model.set_rows((row,))
    return model, model.index(0, column)


def spy_on_draw_text(mocker: MockerFixture, painter: QPainter) -> list[tuple[QColor, QRect, Qt.AlignmentFlag, str]]:
    """Capture every :meth:`QPainter.drawText` call this delegate makes, instead of trusting the glyphs
    it asks for to actually rasterize.

    :param mocker: pytest-mock fixture.
    :param painter: the painter the delegate will draw into.
    :returns: the calls made so far, appended to in place -- ``(pen color, rect, flags, text)`` per call,
        the pen read **at the moment of the call**, since :meth:`~FilesRowDelegate.__paint_background`
        sets it beforehand and this is the only way to see what it was set to.
    """
    calls: list[tuple[QColor, QRect, Qt.AlignmentFlag, str]] = []
    mocker.patch.object(
        QPainter,
        "drawText",
        side_effect=lambda rect, flags, text: calls.append((painter.pen().color(), rect, flags, text)),
    )
    return calls


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


def test_a_selected_rows_content_is_drawn_in_the_highlighted_pen(
    delegate: FilesRowDelegate, palette: QPalette, mocker: MockerFixture
) -> None:
    """Filled and then drawn over, in the colour the palette pairs with that fill -- so the text stays
    legible against it rather than keeping the unselected ink.

    **Test steps:**

    * paint a selected text cell, capturing the pen live at the moment text is drawn
    * verify the pen was the highlighted-text colour, never the ordinary ink
    """
    image = QImage(CELL.size(), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    calls = spy_on_draw_text(mocker, painter)

    model, index = index_for(sample(), KIND_COLUMN)  # pylint: disable=unused-variable
    delegate.paint(painter, option_for(palette, selected=True), index)
    painter.end()

    pens = [pen for pen, *_ in calls]
    assert pens == [HIGHLIGHTED_TEXT]
    assert INK not in pens


def test_an_unselected_row_fills_nothing(delegate: FilesRowDelegate, palette: QPalette, mocker: MockerFixture) -> None:
    """The view's own background shows through, which is what lets the table stay banded.

    A plain rect fill is safe to read back from the painted image -- it draws a solid colour regardless
    of which fonts are loaded -- so the "no fill happened" half of this claim is still a pixel check;
    only the text half goes through the draw-call spy (see the module docstring). Mocking ``fillRect``
    itself, rather than merely reading its effect, crashed the process outright -- an overloaded C++
    method, unlike ``drawText``, is not safe to replace this way.

    **Test steps:**

    * paint an unselected cell, capturing the pen its text was drawn with
    * verify the corner stayed untouched and the text's pen was the ordinary ink
    """
    image = QImage(CELL.size(), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    calls = spy_on_draw_text(mocker, painter)

    model, index = index_for(sample(), KIND_COLUMN)  # pylint: disable=unused-variable
    delegate.paint(painter, option_for(palette), index)
    painter.end()

    assert image.pixelColor(0, 0).alpha() == 0
    assert [pen for pen, *_ in calls] == [INK]


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


def test_the_name_column_draws_its_glyph_before_its_text(
    delegate: FilesRowDelegate, palette: QPalette, mocker: MockerFixture
) -> None:
    """The name is inset past the glyph rather than drawn over it, which is the one thing a decoration
    and a text sharing a cell have to agree about.

    The glyph's slot is checked from the painted image -- an SVG icon rasterizes regardless of which
    fonts happen to be loaded -- while the text is checked from the call it was drawn with instead of
    from pixels, since text is exactly the part that cannot be trusted to render (see the module
    docstring).

    **Test steps:**

    * paint the Name cell, capturing the rect its text was drawn into
    * verify ink appears in the glyph's slot, and the text's rect starts beyond it
    """
    image = QImage(CELL.size(), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    calls = spy_on_draw_text(mocker, painter)

    model, index = index_for(sample(), NAME_COLUMN)  # pylint: disable=unused-variable
    delegate.paint(painter, option_for(palette), index)
    painter.end()

    assert colors(image, QRect(0, 0, ICON_SIZE + 4, CELL.height()))
    assert len(calls) == 1
    _pen, rect, _flags, text = calls[0]
    assert text == "lesson01.mp4"
    assert rect.left() >= ICON_SIZE + 4


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


def test_a_disabled_rows_content_is_drawn_in_the_disabled_pen(
    delegate: FilesRowDelegate, palette: QPalette, mocker: MockerFixture
) -> None:
    """A row a reader may not act on dims -- glyph and text together, because both take the row's own
    pen and the pen is chosen from the row's flags (#266).

    **Test steps:**

    * paint the Name cell of a disabled row
    * verify the glyph is drawn in the disabled colour and so is the text's pen
    """
    image = QImage(CELL.size(), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    calls = spy_on_draw_text(mocker, painter)

    model, index = index_for(sample(enabled=False), NAME_COLUMN)  # pylint: disable=unused-variable
    delegate.paint(painter, option_for(palette), index)
    painter.end()

    assert colors(image, QRect(0, 0, ICON_SIZE + 4, CELL.height())) == {DIM.name()}
    assert [pen for pen, *_ in calls] == [DIM]


def test_a_disabled_row_still_reads_as_selected_when_it_is(
    delegate: FilesRowDelegate, palette: QPalette, mocker: MockerFixture
) -> None:
    """Selection wins over the dimming: a caller that selects a disabled row must not get a row filled
    with highlight and drawn in a colour chosen against the unselected background.

    **Test steps:**

    * paint a selected, disabled cell
    * verify the fill reached the corner and the text was drawn in the highlighted pen, never the dim one
    """
    image = QImage(CELL.size(), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    calls = spy_on_draw_text(mocker, painter)

    model, index = index_for(sample(enabled=False), KIND_COLUMN)  # pylint: disable=unused-variable
    delegate.paint(painter, option_for(palette, selected=True), index)
    painter.end()

    assert image.pixelColor(0, 0).name() == HIGHLIGHT.name()
    pens = [pen for pen, *_ in calls]
    assert pens == [HIGHLIGHTED_TEXT]
    assert DIM not in pens


# endregion


# region Text and sizing


def test_the_size_column_is_right_aligned(delegate: FilesRowDelegate, palette: QPalette, mocker: MockerFixture) -> None:
    """Digits line up on their units, which is the point of a size column; every other text column
    starts at the left.

    **Test steps:**

    * paint the Size cell and the Kind cell, capturing the alignment each was drawn with
    * verify the size's carries AlignRight and the kind's does not
    """
    image = QImage(CELL.size(), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    calls = spy_on_draw_text(mocker, painter)

    size_model, size_index = index_for(sample(), SIZE_COLUMN)  # pylint: disable=unused-variable
    kind_model, kind_index = index_for(sample(), KIND_COLUMN)  # pylint: disable=unused-variable
    delegate.paint(painter, option_for(palette), size_index)
    delegate.paint(painter, option_for(palette), kind_index)
    painter.end()

    # pylint cannot see past the closure spy_on_draw_text's lambda appends through
    # pylint: disable-next=unbalanced-tuple-unpacking
    (_, _, size_flags, _), (_, _, kind_flags, _) = calls
    assert size_flags & Qt.AlignmentFlag.AlignRight
    assert not kind_flags & Qt.AlignmentFlag.AlignRight


def test_a_name_too_long_for_its_cell_is_elided_rather_than_clipped(
    delegate: FilesRowDelegate, palette: QPalette, mocker: MockerFixture
) -> None:
    """A truncated name ends in an ellipsis the reader can see, not at whatever pixel the cell ran out
    at.

    **The elision itself is real** -- computed by :meth:`QFontMetrics.elidedText` against whichever font
    this test happens to run under, the same way :meth:`~FilesRowDelegate.__paint_text` computes it --
    and it is that computed string, not a rendered pixel, that proves it happened.

    **Test steps:**

    * paint a name far longer than the cell, capturing the string it was actually drawn with
    * verify that string is shorter than the original
    """
    long_name = "ArtStation_-_100_MultiPurpose_Imperfection_-_VOL_04.part1.rar" * 3
    image = QImage(CELL.size(), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    calls = spy_on_draw_text(mocker, painter)

    model, index = index_for(sample(long_name), NAME_COLUMN)  # pylint: disable=unused-variable
    delegate.paint(painter, option_for(palette), index)
    painter.end()

    assert len(calls) == 1
    _pen, _rect, _flags, elided = calls[0]
    assert elided != long_name
    assert len(elided) < len(long_name)


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


@mark.parametrize(
    ("column", "text"),
    [(KIND_COLUMN, "content"), (SIZE_COLUMN, "14.1M"), (MODIFIED_COLUMN, None)],
    ids=["kind", "size", "modified"],
)
def test_every_text_column_asks_for_the_padding_it_draws_with(
    delegate: FilesRowDelegate, column: int, text: str | None
) -> None:
    """The regression this guards, and the reason the base class no longer measures any of these: it
    sizes text against the *style*'s margin while :meth:`~FilesRowDelegate.__paint_text` insets it by
    :data:`TEXT_PADDING` a side. The few pixels between those two were the whole difference between a
    column that fits and one eliding the last character of every row -- "other resource's" losing its
    tail, a timestamp losing its minutes.

    Asserted as the invariant rather than as pixel counts: whatever the font, the hint has to leave at
    least the text's own measured width once this delegate's padding comes back off it.

    **Measured in fractional pixels, which is the point.** An earlier form of this test asked
    :class:`~PySide6.QtGui.QFontMetrics` for whole pixels and passed while the column was visibly
    eliding, because that is exactly the rounding that caused it: a string whose real advance is 93.1px
    is reported as 93, the hint asks for 93, and then
    :meth:`~PySide6.QtGui.QFontMetrics.elidedText` lays it out in fractional pixels and finds 93.1 does
    not fit. Only the fractional measurement -- what ``elidedText`` itself compares against -- can tell
    the two apart, and only off a whole-numbered display scale is there any difference to tell.

    **Test steps:**

    * ask for each text column's hint over a row whose text is known
    * verify the hint minus the padding still covers what that text measures
    """
    model, index = index_for(sample(), column)  # pylint: disable=unused-variable
    option = QStyleOptionViewItem()
    drawn = text if text is not None else str(index.data())
    assert drawn

    hint = delegate.sizeHint(option, index)

    available = hint.width() - 2 * TEXT_PADDING
    assert available >= QFontMetricsF(option.font).horizontalAdvance(drawn)


def test_the_modified_column_is_never_narrower_than_a_real_timestamp_needs(
    delegate: FilesRowDelegate,
) -> None:
    """The regression this guards: ``ResizeToContents`` measuring a real row's digits was observed
    eliding a timestamp's minutes in a narrow dock, plausibly because a proportional font's narrower
    digits on one row sized the column under what a wider-digited row then needed. The fix asks the
    hint from the format's *shape* rather than any one row's actual digits, so this checks the outcome
    that matters: the hint is never smaller than an actual formatted stamp needs, whatever digits it
    holds.

    **Test steps:**

    * put a row with a real timestamp in the model, and measure how wide Qt says that exact text is
    * ask the delegate for the Modified cell's hint
    * verify the hint is at least that wide
    """
    model = FilesTableModel()
    model.set_rows((sample(),))
    option: QStyleOptionViewItem = QStyleOptionViewItem()
    index = model.index(0, MODIFIED_COLUMN)
    text = str(index.data())
    needed = QFontMetricsF(option.font).horizontalAdvance(text)

    hint = delegate.sizeHint(option, index)

    assert hint.width() >= needed


def test_the_modified_columns_hint_does_not_depend_on_the_row_shown(delegate: FilesRowDelegate) -> None:
    """Unlike Kind or Size, whose width follows what is actually in the table, Modified's is now a
    property of the *format* -- the fix's whole point, since trusting a particular row's digits is what
    the regression traces back to.

    **Test steps:**

    * ask for the hint against two rows with different modification times
    * verify the two hints are identical
    """
    early = sample()
    late = FileRow(
        name=early.name, path=early.path, kind=early.kind, file_type=early.file_type, modified=1_111_111_111.0
    )
    option = QStyleOptionViewItem()

    model = FilesTableModel()
    model.set_rows((early,))
    first = delegate.sizeHint(option, model.index(0, MODIFIED_COLUMN))
    model.set_rows((late,))
    second = delegate.sizeHint(option, model.index(0, MODIFIED_COLUMN))

    assert first == second


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
