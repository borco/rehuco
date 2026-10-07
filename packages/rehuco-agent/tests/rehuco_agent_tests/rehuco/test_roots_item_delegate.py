"""Tests for how a Roots view row shows a covered file's checksum state: the icon at the right edge, the name kept clear
of it, and the red and orange of a problem (#457).

The rows come from a model that only holds the roles the delegate reads, so each state can be asked for directly; what
the real model derives from a record is ``test_roots_folder_model``'s subject.
"""

from typing import Any, Final

from PySide6.QtCore import QModelIndex, QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QListView, QStyle, QStyleOptionViewItem
from pytest import fixture, mark
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.files_rows import FileChecksumState
from rehuco_agent.rehuco.roots_checksum import BAD_INK, OLD_BAD_INK, RowChecksum
from rehuco_agent.rehuco.roots_folder_model import RootsFolderModel
from rehuco_agent.rehuco.roots_item_delegate import ARROW_WIDTH, ICON_SIZE, ICON_TEXT_GAP, RootsItemDelegate

ROW: Final = QRect(0, 0, 300, 24)
"""Where a row is painted, in the image the tests paint into."""

NAME: Final = "movie.mp4"


ICON_SLOT: Final = QRect(ROW.right() - 6 - ICON_SIZE + 1, (ROW.height() - ICON_SIZE) // 2, ICON_SIZE, ICON_SIZE)
"""Where a state's icon is drawn: the right edge of the padded row, centred in its height."""


class RecordingPainter(QPainter):
    """A painter that remembers what it was asked to write and in which pen, because offscreen text may draw no ink.

    An icon is drawn by Qt itself, past anything Python could override, so what it left in the image is what is read.
    """

    def __init__(self, device: QImage) -> None:
        super().__init__(device)
        self.image: Final = device
        self.texts: Final[list[tuple[QRect, QColor]]] = []
        self.rights: Final[list[int]] = []

    def name_right(self) -> int:
        """Where the name's rectangle ends, in the row's own pixels."""
        return self.rights[-1]

    @property
    def icon_drawn(self) -> bool:
        """Whether anything but the row's plain background is in the icon's slot."""
        background = QColor(Qt.GlobalColor.white).rgb()
        return any(
            self.image.pixelColor(x, y).rgb() != background
            for x in range(ICON_SLOT.left(), ICON_SLOT.right() + 1)
            for y in range(ICON_SLOT.top(), ICON_SLOT.bottom() + 1)
        )

    def drawText(self, *args: Any) -> None:  # noqa: N802  # pyright: ignore[reportIncompatibleMethodOverride]
        """Note the rectangle and the pen of a text, then draw it."""
        if args and isinstance(args[0], QRect):
            self.texts.append((QRect(args[0]), QColor(self.pen().color())))
            self.rights.append(args[0].right())
        super().drawText(*args)


@fixture(name="view")
def view_fixture(qtbot: QtBot) -> QListView:
    """The widget a row is painted for, which supplies the style and the palette.

    :param qtbot: pytest-qt fixture.
    :returns: an unshown list view.
    """
    view = QListView()
    qtbot.addWidget(view)
    return view


def make_index(view: QListView, checksum: RowChecksum | None, *, folder: bool = False) -> QModelIndex:
    """A file row carrying ``checksum``, or a folder row -- one with a row under it, so it opens another column.

    :param view: the widget the model is shown by, which keeps it alive.
    :param checksum: what the row's record found.
    :param folder: whether the row has children, as a folder does.
    :returns: the row's index.
    """
    model = QStandardItemModel(view)
    item = QStandardItem(NAME)
    item.setDragEnabled(False)
    item.setData(checksum, RootsFolderModel.CHECKSUM_ROLE)
    if folder:
        item.appendRow(QStandardItem("inside"))
    model.appendRow(item)
    view.setModel(model)
    return model.index(0, 0)


def paint(view: QListView, index: QModelIndex, *, selected: bool = False) -> RecordingPainter:
    """Paint a row the way the column view does.

    :param view: the widget the row is for.
    :param index: the row.
    :param selected: whether it is the selected row.
    :returns: the painter, which has recorded what was drawn.
    """
    image = QImage(ROW.size(), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.white)
    option = QStyleOptionViewItem()
    option.rect = ROW  # pyright: ignore[reportAttributeAccessIssue]
    option.widget = view  # pyright: ignore[reportAttributeAccessIssue]
    option.state = QStyle.StateFlag.State_Enabled | (
        QStyle.StateFlag.State_Selected if selected else QStyle.StateFlag(0)
    )  # pyright: ignore[reportAttributeAccessIssue]
    painter = RecordingPainter(image)
    try:
        RootsItemDelegate(view).paint(painter, option, index)
    finally:
        painter.end()
    return painter


def test_a_file_with_no_state_is_drawn_as_it_always_was(view: QListView) -> None:
    """A row no record covers has no icon, and its name has the whole row.

    **Test steps:**

    * paint a file row with no state
    * verify nothing is drawn in the icon's slot and the name's rectangle reaches the row's padded edge
    """
    painter = paint(view, make_index(view, None))

    assert not painter.icon_drawn
    assert painter.name_right() == ROW.right() - 6


@mark.parametrize("state", [FileChecksumState.OK, FileChecksumState.OLD_OK, FileChecksumState.MISSING])
def test_a_state_is_an_icon_at_the_right_edge_and_the_name_elides_before_it(
    view: QListView, state: FileChecksumState
) -> None:
    """The icon sits where the row ends, and the text stops short of it, so a long name never runs under it.

    **Test steps:**

    * paint a file row of a state that has an icon
    * verify the icon's slot holds ink and the name's rectangle ends before the icon's slot, in the row's own ink
    """
    painter = paint(view, make_index(view, RowChecksum(state)))

    assert painter.icon_drawn
    ink = painter.texts[-1][1]
    assert painter.name_right() <= ROW.right() - 6 - ICON_SIZE - ICON_TEXT_GAP
    assert ink not in (BAD_INK, OLD_BAD_INK)


@mark.parametrize(
    ("state", "ink"),
    [(FileChecksumState.BAD, BAD_INK), (FileChecksumState.OLD_BAD, OLD_BAD_INK)],
    ids=["mismatch", "old mismatch"],
)
def test_a_problem_is_drawn_in_its_own_ink_unless_the_row_is_selected(
    view: QListView, state: FileChecksumState, ink: QColor
) -> None:
    """Red for a mismatch, orange for one that has expired; on the selection band the band's own ink wins, since a
    warning colour over a highlight would not read.

    **Test steps:**

    * paint a mismatched row, unselected and then selected
    * verify the name's pen is the warning ink for the first and is not for the second
    """
    index = make_index(view, RowChecksum(state))

    assert paint(view, index).texts[-1][1] == ink
    assert paint(view, index, selected=True).texts[-1][1] != ink


def test_a_state_with_no_icon_leaves_the_row_alone(view: QListView) -> None:
    """Only the states with a glyph take room; one without is a row like any other.

    **Test steps:**

    * paint a file row whose state has no icon
    * verify the icon's slot is empty and the name keeps the whole row
    """
    painter = paint(view, make_index(view, RowChecksum(FileChecksumState.NONE)))

    assert not painter.icon_drawn
    assert painter.name_right() == ROW.right() - 6


def test_a_row_with_a_state_is_measured_wider_by_its_icon(view: QListView) -> None:
    """The column is as wide as the longest row needs: the icon and its gap are part of that row.

    **Test steps:**

    * measure a file with an iconed state, with none, and with a state that has no icon
    * verify only the first is wider, by the icon and its gap
    """
    delegate = RootsItemDelegate(view)
    option = QStyleOptionViewItem()

    plain = delegate.sizeHint(option, make_index(view, None)).width()
    iconed = delegate.sizeHint(option, make_index(view, RowChecksum(FileChecksumState.OK))).width()
    bare = delegate.sizeHint(option, make_index(view, RowChecksum(FileChecksumState.NONE))).width()

    assert iconed == plain + ICON_SIZE + ICON_TEXT_GAP
    assert bare == plain


def test_a_folder_row_keeps_its_arrow_and_takes_no_state(view: QListView) -> None:
    """Only a file carries a state, so the arrow at a folder's right edge and the icon never meet: a folder row is
    drawn as it was before states existed.

    **Test steps:**

    * paint a folder row, and measure it
    * verify the name stops before the arrow's room and nothing else, and the width adds the arrow and no icon
    """
    delegate = RootsItemDelegate(view)
    option = QStyleOptionViewItem()
    folder = make_index(view, None, folder=True)
    file = make_index(view, None)

    painter = paint(view, folder)

    assert painter.name_right() == ROW.right() - 6 - ARROW_WIDTH
    assert delegate.sizeHint(option, folder).width() == delegate.sizeHint(option, file).width() + ARROW_WIDTH
