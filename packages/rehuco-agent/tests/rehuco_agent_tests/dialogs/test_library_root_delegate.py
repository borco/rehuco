"""Tests for LibraryRootDelegate: a root drawn on two lines in the library wizard's Root list (#685)."""

from typing import Any, NamedTuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFontMetrics, QImage, QPainter, QPalette, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QStyle, QStyleOptionViewItem
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.dialogs.library_root_delegate import LOCATION_ROLE, LibraryRootDelegate
from rehuco_agent.rehuco.root_row_delegate import PATH_ALPHA, ROW_PADDING, RootRowDelegate

LABEL = "Assets"
LOCATION = "//nas/data/Assets"
ENABLED = QStyle.StateFlag.State_Enabled


class Line(NamedTuple):
    """One line the delegate drew."""

    text: str
    elide: Qt.TextElideMode
    ink: tuple[int, int, int, int]


class Root(NamedTuple):
    """A model of one root, and its item."""

    model: QStandardItemModel
    item: QStandardItem


@fixture(name="root")
def fixture_root(qtbot: QtBot) -> Root:
    """One root: a label and, under :data:`LOCATION_ROLE`, its location.

    :param qtbot: pytest-qt fixture, which makes the application the style needs.
    :returns: the model and its item.
    """
    del qtbot
    model = QStandardItemModel()
    item = QStandardItem(LABEL)
    item.setData(LOCATION, LOCATION_ROLE)
    model.appendRow(item)
    return Root(model, item)


def paint(mocker: MockerFixture, root: Root, state: QStyle.StateFlag) -> list[Line]:
    """Paint the root's row in ``state`` and report the lines drawn.

    :param mocker: pytest-mock fixture.
    :param root: the root.
    :param state: the style state the row is drawn in.
    :returns: the lines, the label first.
    """
    drawn: list[Line] = []

    def record(painter: QPainter, _font: Any, text: str, elide: Qt.TextElideMode, _line: Any) -> None:
        drawn.append(Line(text, elide, rgba(painter.pen().color())))

    mocker.patch.object(RootRowDelegate, "draw_line", side_effect=record)
    image = QImage(240, 80, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    option = QStyleOptionViewItem()
    option.rect = image.rect()
    option.state = state
    try:
        LibraryRootDelegate().paint(painter, option, root.model.index(0, 0))
    finally:
        painter.end()
    return drawn


def rgba(color: QColor) -> tuple[int, int, int, int]:
    """A color as its four channels.

    :param color: the color.
    :returns: red, green, blue and alpha.
    """
    return (color.red(), color.green(), color.blue(), color.alpha())


def ink(group: QPalette.ColorGroup, role: QPalette.ColorRole) -> tuple[int, int, int, int]:
    """A color of the default palette.

    :param group: its group.
    :param role: its role.
    :returns: the color's rgba.
    """
    option = QStyleOptionViewItem()  # held, or its palette is freed under the color
    return rgba(option.palette.color(group, role))


def test_a_root_is_drawn_as_its_label_over_its_location(mocker: MockerFixture, root: Root) -> None:
    """The label is drawn first, elided on the right, and the location under it, elided in the middle and fainter.

    **Test steps:**

    * paint an enabled, unselected root
    * verify the label then the location were drawn
    * verify the label is elided on the right and the location in the middle
    * verify the location's ink is the label's, at the Roots view's folder opacity
    """
    lines = paint(mocker, root, ENABLED)
    label, location = lines[0], lines[1]

    assert (label.text, label.elide) == (LABEL, Qt.TextElideMode.ElideRight)
    assert (location.text, location.elide) == (LOCATION, Qt.TextElideMode.ElideMiddle)
    assert location.ink[:3] == label.ink[:3]
    assert location.ink[3] == PATH_ALPHA


def test_a_root_with_no_location_draws_an_empty_second_line(mocker: MockerFixture, root: Root) -> None:
    """A root whose location is missing still has its second line, empty.

    **Test steps:**

    * clear the item's location
    * paint it
    * verify the second line is empty
    """
    root.item.setData(None, LOCATION_ROLE)

    assert paint(mocker, root, ENABLED)[1].text == ""


def test_a_disabled_root_is_drawn_in_the_disabled_ink(mocker: MockerFixture, root: Root) -> None:
    """A root that can take no scan is drawn grayed, in the palette's disabled text.

    **Test steps:**

    * paint the root in the state the view gives a disabled item, which has no enabled flag
    * verify the label's ink is the palette's disabled text color
    """
    assert paint(mocker, root, QStyle.StateFlag.State_None)[0].ink == ink(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text
    )


def test_a_selected_root_is_drawn_in_the_highlighted_ink(mocker: MockerFixture, root: Root) -> None:
    """The row under the pointer or the keyboard is drawn in the ink that reads on the selection band.

    **Test steps:**

    * paint the root selected
    * verify the label's ink is the palette's highlighted text color
    """
    drawn = paint(mocker, root, ENABLED | QStyle.StateFlag.State_Selected)

    assert drawn[0].ink == ink(QPalette.ColorGroup.Normal, QPalette.ColorRole.HighlightedText)


def test_a_root_is_two_lines_tall(root: Root) -> None:
    """The size hint holds both lines and the padding, so the list gives every root room for its location.

    **Test steps:**

    * ask for the size hint of a root
    * verify its height is the label's line, the location's line and the padding above and below
    * verify that is taller than a one-line row would be
    """
    option = QStyleOptionViewItem()
    option.state = ENABLED

    hint = LibraryRootDelegate().sizeHint(option, root.model.index(0, 0))

    name = QFontMetrics(option.font).height()
    assert hint.height() == name + QFontMetrics(RootRowDelegate.folder_font(option.font)).height() + 2 * ROW_PADDING
    assert hint.height() > name + 2 * ROW_PADDING
