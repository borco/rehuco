"""Tests for ContentSizedListWidget: sized to its rows, never scrolling them itself.

The offscreen platform lays rows out for real, so these assert on the list's *own* row height rather
than pixel counts, which depend on the platform font and style.
"""

from borco_pyside.widgets import ContentSizedListWidget
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSizePolicy
from pytestqt.qtbot import QtBot


def fill(listing: ContentSizedListWidget, count: int) -> None:
    """Replace the list's contents with ``count`` short entries.

    :param listing: the list to fill.
    :param count: how many rows to leave it holding.
    """
    listing.clear()
    for index in range(count):
        listing.addItem(f"*.tmp{index}")


def chrome(listing: ContentSizedListWidget) -> int:
    """The height ``listing`` spends on anything that is not a row, read off a known row count.

    :param listing: a list holding at least one row.
    :returns: the frame (and any scrollbar) height its size hint carries on top of its rows.
    """
    return listing.sizeHint().height() - listing.count() * listing.sizeHintForRow(0)


def test_it_never_scrolls_vertically(qtbot: QtBot) -> None:
    """The list is sized to its rows, so a vertical scrollbar would have nothing to scroll to.

    **Test steps:**

    * build a list and fill it well past any plausible visible height
    * verify its vertical scrollbar policy is always-off and its vertical size policy is fixed
    """
    listing = ContentSizedListWidget()
    qtbot.addWidget(listing)

    fill(listing, 50)

    assert listing.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert listing.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Fixed


def test_the_size_hint_grows_by_a_row_for_every_row_added(qtbot: QtBot) -> None:
    """The hint is exactly its rows' height, so the enclosing scroll area sees the whole list (#229).

    **Test steps:**

    * fill a list with three rows, then with ten
    * verify the hint is the row count times a row's height, plus the same chrome either way
    """
    listing = ContentSizedListWidget()
    qtbot.addWidget(listing)

    fill(listing, 3)
    three = listing.sizeHint().height()
    fill(listing, 10)
    ten = listing.sizeHint().height()

    row = listing.sizeHintForRow(0)
    assert ten - three == 7 * row
    assert ten == 10 * row + chrome(listing)


def test_a_one_row_list_is_one_row_tall(qtbot: QtBot) -> None:
    """A single entry gets a single row's height and no more.

    **Test steps:**

    * fill a list with one row
    * verify its hint is that row plus the chrome
    """
    listing = ContentSizedListWidget()
    qtbot.addWidget(listing)

    fill(listing, 1)

    assert listing.sizeHint().height() == listing.sizeHintForRow(0) + chrome(listing)


def test_an_emptied_list_stays_exactly_one_row_tall(qtbot: QtBot) -> None:
    """Emptying the list floors it at one row, sized by the rows it just held.

    A list collapsed to a sliver is one there is nowhere to drop a first entry into, and an estimated
    row height is one that can differ from what the style actually draws.

    **Test steps:**

    * fill a list, read its one-row height, then clear it
    * verify it still asks for exactly that height
    """
    listing = ContentSizedListWidget()
    qtbot.addWidget(listing)
    fill(listing, 4)
    one_row = listing.sizeHintForRow(0) + chrome(listing)

    listing.clear()

    assert listing.sizeHint().height() == one_row


def test_a_list_that_never_held_a_row_is_still_a_legible_band(qtbot: QtBot) -> None:
    """With no row ever measured, the font's line height stands in -- never nothing at all.

    **Test steps:**

    * build a list and add nothing to it
    * verify it asks for a line of text's worth of height
    """
    listing = ContentSizedListWidget()
    qtbot.addWidget(listing)

    assert listing.sizeHint().height() == listing.fontMetrics().height() + 2 * listing.frameWidth()


def test_the_minimum_and_preferred_heights_agree(qtbot: QtBot) -> None:
    """Both hints are the rows' height: a list given more is blank space below its last entry.

    **Test steps:**

    * fill a list
    * verify its minimum size hint's height matches its size hint's
    """
    listing = ContentSizedListWidget()
    qtbot.addWidget(listing)

    fill(listing, 6)

    assert listing.minimumSizeHint().height() == listing.sizeHint().height()


def test_removing_a_row_re_advertises_the_height(qtbot: QtBot) -> None:
    """A row taken out shrinks the list there and then, without waiting for a resize.

    **Test steps:**

    * show a filled list inside its own window, then take a row out
    * verify its height fell by exactly one row
    """
    listing = ContentSizedListWidget()
    qtbot.addWidget(listing)
    fill(listing, 5)
    listing.show()
    qtbot.waitExposed(listing)
    row = listing.sizeHintForRow(0)
    before = listing.sizeHint().height()

    listing.takeItem(0)

    assert listing.sizeHint().height() == before - row
