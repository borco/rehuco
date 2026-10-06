"""Tests for the Roots column view and the delegate that draws its rows (#378)."""

from collections.abc import Generator
from pathlib import Path
from typing import Any, Final, NamedTuple
from uuid import uuid4

from borco_pyside.widgets import RowBandDelegate
from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QAbstractItemView, QApplication, QListView, QStyleOptionViewItem
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco.root_row_delegate import ROW_PADDING, RootRowDelegate
from rehuco_agent.rehuco.roots_column_view import RootsColumnView
from rehuco_agent.rehuco.roots_folder_model import NodeListing, RootsFolderModel
from rehuco_agent.rehuco.roots_item_delegate import (
    ARROW_WIDTH,
    ICON_SIZE,
    ICON_TEXT_GAP,
    RootsItemDelegate,
    arrow_height,
)
from rehuco_core import RehucoRoot, RootFolderLister, RootStorage

WAIT_TIMEOUT_MS: Final = 10_000


@fixture(name="shown")
def fixture_shown(qtbot: QtBot, tmp_path: Path) -> Generator[tuple[RootsColumnView, RootsFolderModel]]:
    """A shown column view over a reachable root holding a folder and a file, and an unreachable network root.

    :param qtbot: pytest-qt fixture.
    :param tmp_path: pytest's temporary directory.
    :yields: the view and its model, with both roots listed.
    """
    (tmp_path / "lib" / "alpha").mkdir(parents=True)
    (tmp_path / "lib" / "clip.mp4").write_bytes(b"x")
    roots = [
        RehucoRoot(uuid4(), tmp_path / "lib", "lib", RootStorage.LOCAL),
        RehucoRoot(uuid4(), tmp_path / "away", "away", RootStorage.NETWORK),
    ]
    model = RootsFolderModel()
    view = RootsColumnView()
    view.setModel(model)
    qtbot.addWidget(view)
    model.set_roots(roots, RootFolderLister(roots))
    view.resize(520, 260)
    view.show()
    qtbot.waitExposed(view)
    for row in range(2):
        index = model.index(row, 0)
        qtbot.waitUntil(
            lambda index=index: model.listing_state(index) in (NodeListing.LISTED, NodeListing.UNREACHABLE),
            timeout=WAIT_TIMEOUT_MS,
        )
    yield view, model


def test_every_column_is_drawn_by_the_roots_delegate(
    qtbot: QtBot, shown: tuple[RootsColumnView, RootsFolderModel]
) -> None:
    """``QColumnView`` gives each column a delegate of its own and ignores one set on the view, so the columns are
    made here: the first and every one opened later wear the roots delegate.

    **Test steps:**

    * open the first root's column
    * verify every list view the column view holds uses :class:`RootsItemDelegate`
    """
    view, model = shown
    view.setCurrentIndex(model.index(0, 0))
    qtbot.wait(50)

    columns = view.findChildren(QListView)

    assert len(columns) >= 2
    assert all(isinstance(column.itemDelegate(), RootsItemDelegate) for column in columns)


def test_painting_every_kind_of_row_draws_something(
    qtbot: QtBot, shown: tuple[RootsColumnView, RootsFolderModel]
) -> None:
    """Rows paint without error: a root, a reachable and a greyed one, a folder with the arrow, a file, a selected
    row, and the placeholder an unreachable root shows.

    **Test steps:**

    * select the first root so a second column opens, and select its folder so a third does
    * grab the view
    * verify the image is not blank
    """
    view, model = shown
    root = model.index(0, 0)
    view.setCurrentIndex(root)
    qtbot.wait(50)
    view.setCurrentIndex(model.index(0, 0, root))
    qtbot.wait(50)

    image: QImage = view.grab().toImage()

    assert not image.isNull()
    assert len({image.pixel(x, y) for x in range(0, image.width(), 7) for y in range(0, image.height(), 7)}) > 3


def test_a_row_is_wider_by_its_glyph_and_its_arrow(shown: tuple[RootsColumnView, RootsFolderModel]) -> None:
    """The delegate measures what it draws: the base width plus the glyph, and the arrow where the row opens another
    column.

    **Test steps:**

    * measure a root with the base delegate and with this one, then a file, which has no arrow
    * verify the extra widths
    """
    view, model = shown
    delegate = RootsItemDelegate(view)
    base = RowBandDelegate(view)
    option = QStyleOptionViewItem()
    root = model.index(0, 0)
    clip = model.index(1, 0, root)

    assert (
        delegate.sizeHint(option, root).width()
        == base.sizeHint(option, root).width() + ICON_SIZE + ICON_TEXT_GAP + ARROW_WIDTH
    )
    assert delegate.sizeHint(option, clip).width() == base.sizeHint(option, clip).width() + ICON_SIZE + ICON_TEXT_GAP
    assert delegate.sizeHint(option, root).height() >= ICON_SIZE


def test_the_row_under_a_screen_point_is_found_in_whichever_column(
    qtbot: QtBot, shown: tuple[RootsColumnView, RootsFolderModel]
) -> None:
    """What the context menu asks: the row at a global point, in any open column, or nothing.

    **Test steps:**

    * open the first root's column, and take the centre of a root row and of a row in the second column
    * verify each point finds its row
    * verify a point far outside the view finds none
    """
    view, model = shown
    root = model.index(0, 0)
    view.setCurrentIndex(root)
    qtbot.wait(50)
    columns = view.findChildren(QListView)
    first = next(column for column in columns if not column.rootIndex().isValid())
    second = next(column for column in columns if column.rootIndex() == root)
    alpha = model.index(0, 0, root)
    qtbot.waitUntil(lambda: second.isVisible() and second.viewport().width() > 100, timeout=WAIT_TIMEOUT_MS)

    assert view.index_at_global(first.viewport().mapToGlobal(first.visualRect(root).center())) == root
    assert view.index_at_global(second.viewport().mapToGlobal(second.visualRect(alpha).center())) == alpha
    assert not view.index_at_global(QPoint(-5000, -5000)).isValid()


def test_a_file_current_opens_no_column_of_its_own(
    qtbot: QtBot, shown: tuple[RootsColumnView, RootsFolderModel]
) -> None:
    """``QColumnView`` ends the columns with a preview column for a row with nothing under it, empty or not; this view
    has a details pane beside it, so that column is collapsed to no width.

    **Test steps:**

    * open the root's column and select the file in it
    * verify the one item view that has no model, the preview column, ends up with no width
    """
    view, model = shown
    root = model.index(0, 0)
    view.setCurrentIndex(root)
    qtbot.wait(50)

    view.setCurrentIndex(model.index(1, 0, root))

    previews = [column for column in view.findChildren(QAbstractItemView) if column.model() is None]
    assert previews
    qtbot.waitUntil(lambda: all(column.width() == 0 for column in previews), timeout=WAIT_TIMEOUT_MS)


def test_the_first_column_draws_roots_in_two_lines_and_the_others_in_one(
    qtbot: QtBot, shown: tuple[RootsColumnView, RootsFolderModel]
) -> None:
    """The column of roots has a delegate that shows each root's folder under its name; a folder column keeps the
    one-line delegate.

    **Test steps:**

    * open the first root so a folder column exists
    * verify the first column's delegate is the root row delegate and the second's is not
    """
    view, model = shown
    view.setCurrentIndex(model.index(0, 0))
    qtbot.wait(50)
    columns = view.findChildren(QAbstractItemView)
    first = next(column for column in columns if column.model() is not None and not column.rootIndex().isValid())
    second = next(column for column in columns if column.model() is not None and column.rootIndex().isValid())

    assert isinstance(first.itemDelegate(), RootRowDelegate)
    assert not isinstance(second.itemDelegate(), RootRowDelegate)
    assert isinstance(second.itemDelegate(), RootsItemDelegate)


def test_a_root_row_is_taller_than_a_folder_row_and_its_folder_is_in_the_model(
    shown: tuple[RootsColumnView, RootsFolderModel],
) -> None:
    """The second line costs a line of height, and where it comes from is the model's path role -- a root's folder, and
    nothing for any other row.

    **Test steps:**

    * measure a root row with the root row delegate and with the one-line one
    * read the path role of a root and of a file
    * verify the taller height, the folder's text and no text for a file
    """
    view, model = shown
    option = QStyleOptionViewItem()
    root = model.index(0, 0)
    clip = model.index(1, 0, root)

    two_lines = RootRowDelegate(view).sizeHint(option, root).height()
    one_line = RootsItemDelegate(view).sizeHint(option, root).height()

    assert two_lines > one_line
    assert root.data(RootsFolderModel.PATH_ROLE) == str(model.path_of(root))
    assert clip.data(RootsFolderModel.PATH_ROLE) is None


class DrawnLine(NamedTuple):
    """One line of text a painter was asked to draw: where, what, in which font and in which colour."""

    rect: QRect
    text: str
    font: QFont
    ink: QColor


class RecordingPainter(QPainter):
    """A painter that notes each line of text it is asked to draw."""

    def __init__(self, device: QImage) -> None:
        super().__init__(device)
        self.lines: list[DrawnLine] = []

    def drawText(self, *args: Any) -> None:  # noqa: N802  # pyright: ignore[reportIncompatibleMethodOverride]
        """Note a ``(rect, flags, text)`` draw, then draw it."""
        rect, _flags, text = args
        self.lines.append(DrawnLine(rect, text, self.font(), self.pen().color()))
        super().drawText(*args)


def test_painting_a_root_row_shows_its_folder_line(shown: tuple[RootsColumnView, RootsFolderModel]) -> None:
    """The folder line is drawn under the name, in a smaller font and fainter ink.

    Read off the draw calls, not the pixels: the offscreen platform has no system fonts, and once any test has loaded
    an icon font plain text draws nothing at all, so a grab of the row holds no ink to measure.

    **Test steps:**

    * paint a root row's content with a painter that records each line of text
    * verify two lines: the name, then the folder -- below it, smaller, and drawn with a lower alpha
    """
    view, model = shown
    root = model.index(0, 0)
    delegate = RootRowDelegate(view)
    option = QStyleOptionViewItem()
    delegate.initStyleOption(option, root)
    image = QImage(320, 80, QImage.Format.Format_ARGB32)  # kept: a painter does not own its device
    painter = RecordingPainter(image)
    try:
        painter.setPen(QColor("black"))
        delegate.paint_content(painter, option, root, QRect(0, 0, 300, 60), QColor("black"))
    finally:
        painter.end()

    lines = painter.lines
    name, folder = lines[0], lines[1]
    assert len(lines) == 2
    assert name.text == "lib"
    assert folder.text  # elided to fit, so not compared with the whole path
    assert folder.rect.top() >= name.rect.bottom()
    assert folder.font.pointSizeF() < name.font.pointSizeF()
    assert (name.ink.alpha(), folder.ink.alpha() < 255) == (255, True)


def test_a_root_rows_glyph_is_centred_on_the_whole_row(
    mocker: MockerFixture, shown: tuple[RootsColumnView, RootsFolderModel]
) -> None:
    """The storage glyph sits halfway down the two-line row, beside both the name and the folder, not level with the
    name alone.

    **Test steps:**

    * paint a root row's content into a rect taller than its two lines, with the glyph drawing captured
    * verify the glyph's vertical centre is the rect's
    """
    view, model = shown
    delegate = RootRowDelegate(view)
    draw = mocker.patch.object(delegate, "draw_icon")
    root = model.index(0, 0)
    option = QStyleOptionViewItem()
    delegate.initStyleOption(option, root)
    row = QRect(0, 10, 300, 60)
    image = QImage(320, 80, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    try:
        delegate.paint_content(painter, option, root, row, QColor("black"))
    finally:
        painter.end()

    _painter, _path, _color, glyph = draw.call_args.args
    assert glyph.width() == glyph.height() == delegate.glyph_size(option, root, row.height())
    assert abs(glyph.center().y() - row.center().y()) <= 1


def test_a_root_rows_glyph_grows_as_its_arrow_does(shown: tuple[RootsColumnView, RootsFolderModel]) -> None:
    """The style draws the column view's arrow bigger in a taller row, so the two-line root row's arrow is bigger than a
    folder's; the root's glyph is the folders' scaled by the ratio of the two arrows, and the row is wider by what that
    adds.

    **Test steps:**

    * measure a root row with the root row delegate and with the one-line one, and the arrow each gets
    * verify the glyph is the folders' size scaled by the ratio of the two arrows, capped at the two lines' height
    * verify the root row's width hint grew by exactly the glyph's growth
    * verify it never shrinks below a folder's in a short row
    """
    view, model = shown
    root = model.index(0, 0)
    option = QStyleOptionViewItem()
    delegate = RootRowDelegate(view)
    two_lines = delegate.sizeHint(option, root)
    one_line = RootsItemDelegate(view).sizeHint(option, root)
    ratio = arrow_height(QApplication.style(), two_lines.height()) / arrow_height(
        QApplication.style(), one_line.height()
    )

    side = delegate.glyph_size(option, root, two_lines.height())

    assert side == max(ICON_SIZE, min(round(ICON_SIZE * ratio), two_lines.height() - 2 * ROW_PADDING))
    assert two_lines.width() == one_line.width() + side - ICON_SIZE
    assert delegate.glyph_size(option, root, 4) == ICON_SIZE


def test_the_arrow_is_measured_as_the_style_draws_it_and_grows_with_the_row(qtbot: QtBot) -> None:
    """The arrow's height is read off what the style draws -- something, and more of it in a taller row -- and asking
    twice gives the same answer.

    **Test steps:**

    * measure the arrow of a one-line row and of a row three times as tall
    * verify both drew something, the taller one more, and a second ask agrees
    """
    del qtbot
    style = QApplication.style()

    short, tall = arrow_height(style, 20), arrow_height(style, 60)

    assert 0 < short <= tall
    assert arrow_height(style, 20) == short


def test_a_style_that_draws_no_arrow_leaves_the_root_glyph_at_the_folders_size(
    mocker: MockerFixture, shown: tuple[RootsColumnView, RootsFolderModel]
) -> None:
    """With nothing drawn to measure, there is no ratio to scale by: the arrow measures nothing, and the root's glyph
    stays the size a folder's is.

    **Test steps:**

    * measure the arrow of a style that draws nothing
    * make every arrow measure nothing and ask for a root's glyph
    * verify zero, then the folders' size
    """
    view, model = shown
    blank = mocker.MagicMock()
    blank.name.return_value = "blank"

    assert arrow_height(blank, 30) == 0

    mocker.patch("rehuco_agent.rehuco.root_row_delegate.arrow_height", return_value=0)
    assert RootRowDelegate(view).glyph_size(QStyleOptionViewItem(), model.index(0, 0), 38) == ICON_SIZE


def test_a_row_with_no_glyph_is_no_wider_than_its_one_line_hint(
    shown: tuple[RootsColumnView, RootsFolderModel],
) -> None:
    """A row with no glyph -- a placeholder -- has none to grow, so its two-line hint is exactly as wide as its one-line
    one.

    **Test steps:**

    * take the placeholder row of the unreachable root, which has no glyph
    * verify the root row delegate's width hint is the one-line delegate's
    """
    view, model = shown
    placeholder = model.index(0, 0, model.index(1, 0))
    assert placeholder.isValid()
    assert placeholder.data(RootsFolderModel.ICON_PATH_ROLE) is None

    width = RootRowDelegate(view).sizeHint(QStyleOptionViewItem(), placeholder).width()

    assert width == RootsItemDelegate(view).sizeHint(QStyleOptionViewItem(), placeholder).width()


def test_a_row_with_no_glyph_paints_its_name_alone(
    mocker: MockerFixture, shown: tuple[RootsColumnView, RootsFolderModel]
) -> None:
    """Neither delegate draws a glyph, or leaves room for one, in a row that has none.

    **Test steps:**

    * paint the placeholder row of the unreachable root with each delegate, the glyph drawing captured
    * verify no glyph was drawn
    """
    view, model = shown
    placeholder = model.index(0, 0, model.index(1, 0))
    for delegate in (RootRowDelegate(view), RootsItemDelegate(view)):
        draw = mocker.patch.object(delegate, "draw_icon")
        option = QStyleOptionViewItem()
        delegate.initStyleOption(option, placeholder)
        image = QImage(320, 80, QImage.Format.Format_ARGB32)
        painter = QPainter(image)
        try:
            delegate.paint_content(painter, option, placeholder, QRect(0, 0, 300, 60), QColor("black"))
        finally:
            painter.end()
        draw.assert_not_called()


def test_the_folder_line_scales_a_font_sized_in_pixels(qtbot: QtBot) -> None:
    """A font with no point size -- one set in pixels -- gets a folder line smaller by the same scale.

    **Test steps:**

    * build a font of 20 pixels and ask for the folder line's font
    * verify it is smaller and still in pixels
    """
    del qtbot
    font = QFont()
    font.setPixelSize(20)

    folder_font = RootRowDelegate._RootRowDelegate__folder_font(font)  # type: ignore[attr-defined]  # pylint: disable=protected-access

    assert 0 < folder_font.pixelSize() < 20
