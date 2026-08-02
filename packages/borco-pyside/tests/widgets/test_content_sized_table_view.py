"""Tests for ContentSizedTableView: sized to its model's rows and header, never scrolling them itself.

The offscreen platform lays rows out for real, so these assert on the view's *own* row height rather
than pixel counts, which depend on the platform font and style.
"""

# pylint: disable=duplicate-code  # the table's half of what ContentSizedListView is tested for

from borco_pyside.widgets import ContentSizedTableView
from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QSizePolicy
from pytestqt.qtbot import QtBot


def fill(view: ContentSizedTableView, count: int) -> QStandardItemModel:
    """Give the view a two-column model holding ``count`` rows.

    :param view: the view to fill.
    :param count: how many rows to leave it showing.
    :returns: the model, for driving further row changes.
    """
    model = view.model()
    if not isinstance(model, QStandardItemModel):
        model = QStandardItemModel(view)
        model.setHorizontalHeaderLabels(["Name", "URL"])
        view.setModel(model)
    model.removeRows(0, model.rowCount())
    for index in range(count):
        model.appendRow([QStandardItem(f"name {index}"), QStandardItem(f"https://example.com/{index}")])
    return model


def row_height(view: ContentSizedTableView) -> int:
    """The height one row is drawn at -- what the view sizes itself by.

    :param view: a view showing at least one row.
    :returns: the laid-out row height, falling back to the measurement behind it.
    """
    return view.rowHeight(0) or view.sizeHintForRow(0)


def chrome(view: ContentSizedTableView) -> int:
    """The height ``view`` spends on anything that is not a row, read off a known row count.

    :param view: a view showing at least one row.
    :returns: the header and frame height its size hint carries on top of its rows.
    """
    model = view.model()
    assert model is not None
    return view.sizeHint().height() - model.rowCount() * row_height(view)


def test_it_never_scrolls_vertically(qtbot: QtBot) -> None:
    """The view is sized to its rows, so a vertical scrollbar would have nothing to scroll to.

    **Test steps:**

    * build a view and fill it well past any plausible visible height
    * verify its vertical scrollbar policy is always-off and its vertical size policy is fixed
    """
    view = ContentSizedTableView()
    qtbot.addWidget(view)

    fill(view, 50)

    assert view.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert view.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Fixed


def test_the_size_hint_grows_by_a_row_for_every_row_added(qtbot: QtBot) -> None:
    """The hint is its rows plus its header, so the enclosing scroll area sees the whole table.

    **Test steps:**

    * fill a view with three rows, then with ten
    * verify the hint is the row count times a row's height, plus the same chrome either way
    """
    view = ContentSizedTableView()
    qtbot.addWidget(view)

    fill(view, 3)
    three = view.sizeHint().height()
    fill(view, 10)
    ten = view.sizeHint().height()

    row = row_height(view)
    assert ten - three == 7 * row
    assert ten == 10 * row + chrome(view)


def test_the_header_is_part_of_the_height_it_asks_for(qtbot: QtBot) -> None:
    """A table's first line is its header, so a hint without it would clip the last row.

    **Test steps:**

    * fill a view and read its hint with the header shown
    * hide the header
    * verify the hint fell by exactly the header's height
    """
    view = ContentSizedTableView()
    qtbot.addWidget(view)
    fill(view, 3)
    header = view.horizontalHeader()
    with_header = view.sizeHint().height()

    header.hide()

    assert with_header - view.sizeHint().height() == header.sizeHint().height()


def test_an_emptied_table_stays_exactly_one_row_tall(qtbot: QtBot) -> None:
    """Emptying the table floors it at one row, sized by the rows it just held.

    A table collapsed onto its header is one there is nowhere to drop a first entry into, and an
    estimated row height is one that can differ from what the style actually draws.

    **Test steps:**

    * fill a view, read its one-row height, then remove every row
    * verify it still asks for exactly that height
    """
    view = ContentSizedTableView()
    qtbot.addWidget(view)
    model = fill(view, 4)
    one_row = row_height(view) + chrome(view)

    model.removeRows(0, model.rowCount())

    assert view.sizeHint().height() == one_row


def test_a_table_that_never_held_a_row_is_still_a_legible_band(qtbot: QtBot) -> None:
    """With no row ever measured, the font's line height stands in -- never nothing at all.

    **Test steps:**

    * build a view and give it nothing, not even a model
    * verify it asks for a line of text's worth of height on top of its chrome
    """
    view = ContentSizedTableView()
    qtbot.addWidget(view)

    # a header with nothing behind it reports an invalid hint, which counts as no header at all
    assert view.sizeHint().height() == view.fontMetrics().height() + 2 * view.frameWidth()


def test_the_minimum_and_preferred_heights_agree(qtbot: QtBot) -> None:
    """Both hints are the rows' height: a table given more is blank space below its last entry.

    **Test steps:**

    * fill a view
    * verify its minimum size hint's height matches its size hint's
    """
    view = ContentSizedTableView()
    qtbot.addWidget(view)

    fill(view, 6)

    assert view.minimumSizeHint().height() == view.sizeHint().height()


def test_removing_a_row_re_advertises_the_height(qtbot: QtBot) -> None:
    """A row taken out shrinks the view there and then, without waiting for a resize.

    **Test steps:**

    * show a filled view inside its own window, then remove a row from its model
    * verify its height fell by exactly one row
    """
    view = ContentSizedTableView()
    qtbot.addWidget(view)
    model = fill(view, 5)
    view.show()
    qtbot.waitExposed(view)
    row = row_height(view)
    before = view.sizeHint().height()

    model.removeRow(0)

    assert view.sizeHint().height() == before - row


def test_a_replacement_model_is_the_one_the_height_follows(qtbot: QtBot) -> None:
    """A view handed a second model is sized by *its* rows, and stops listening to the first.

    A view is given its model after construction and may be given another, so the size wiring cannot
    live in the constructor the way it could on a widget that owns its own model.

    **Test steps:**

    * fill a view, then hand it a second model
    * add a row to the *old* model and verify the height did not move
    * remove one from the new model and verify the height followed it
    """
    view = ContentSizedTableView()
    qtbot.addWidget(view)
    first = fill(view, 2)
    view.sizeHint()

    second = QStandardItemModel(view)
    second.setHorizontalHeaderLabels(["Name", "URL"])
    for index in range(4):
        second.appendRow([QStandardItem(f"other {index}"), QStandardItem("https://example.com")])
    view.setModel(second)
    settled = view.sizeHint().height()

    first.appendRow([QStandardItem("late"), QStandardItem("https://example.com/late")])

    assert view.sizeHint().height() == settled, "still sized by the model it was handed away from"

    second.removeRow(0)

    assert view.sizeHint().height() == settled - row_height(view)


def test_a_view_stripped_of_its_model_falls_back_to_the_one_row_floor(qtbot: QtBot) -> None:
    """Detaching the model leaves no rows to be sized by, which is the emptied-table case.

    **Test steps:**

    * fill a view, then take its model away entirely
    * verify it asks for exactly one row's worth of height
    """
    view = ContentSizedTableView()
    qtbot.addWidget(view)
    fill(view, 5)
    # asked while it still has rows, which is what leaves it a row height to remember; no model is
    # also no header sections, so what is left afterwards is that one row inside the frame
    view.sizeHint()
    one_row = row_height(view) + 2 * view.frameWidth()

    view.setModel(None)

    assert view.sizeHint().height() == one_row
