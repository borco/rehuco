"""Tests for the Roots column view and the delegate that draws its rows (#378)."""

from collections.abc import Generator
from pathlib import Path
from typing import Final
from uuid import uuid4

from borco_pyside.widgets import RowBandDelegate
from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QAbstractItemView, QListView, QStyleOptionViewItem
from pytest import fixture
from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco.root_row_delegate import RootRowDelegate
from rehuco_agent.rehuco.roots_column_view import RootsColumnView
from rehuco_agent.rehuco.roots_folder_model import NodeListing, RootsFolderModel
from rehuco_agent.rehuco.roots_item_delegate import ARROW_WIDTH, ICON_SIZE, ICON_TEXT_GAP, RootsItemDelegate
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


def test_painting_a_root_row_shows_its_folder_line(
    qtbot: QtBot, shown: tuple[RootsColumnView, RootsFolderModel]
) -> None:
    """The folder line is drawn, fainter than the name: the row has ink in its lower half, and less strongly than in its
    upper half.

    **Test steps:**

    * grab the column of roots
    * verify the first row's lower half holds some ink, and its darkest pixel is lighter than the name's
    """
    view, _model = shown
    qtbot.wait(50)
    first = next(
        column
        for column in view.findChildren(QAbstractItemView)
        if column.model() is not None and not column.rootIndex().isValid()
    )
    height = RootRowDelegate(view).sizeHint(QStyleOptionViewItem(), first.model().index(0, 0)).height()
    image = first.viewport().grab().toImage()

    def darkest(top: int, bottom: int) -> int:
        return min(
            QColor(image.pixel(x, y)).lightness()
            for x in range(20, min(200, image.width()))
            for y in range(top, min(bottom, image.height()))
        )

    name_ink = darkest(0, height // 2)
    folder_ink = darkest(height // 2, height)
    assert folder_ink < 255
    assert folder_ink > name_ink
