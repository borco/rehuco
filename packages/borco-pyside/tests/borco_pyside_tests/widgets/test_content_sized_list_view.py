"""Tests for ContentSizedListView: sized to its model's rows, never scrolling them itself.

The offscreen platform lays rows out for real, so these assert on the view's *own* row height rather
than pixel counts, which depend on the platform font and style.
"""

from borco_pyside.widgets import ContentSizedListView
from PySide6.QtCore import QStringListModel, Qt
from PySide6.QtWidgets import QSizePolicy
from pytestqt.qtbot import QtBot


def fill(view: ContentSizedListView, count: int) -> QStringListModel:
    """Give the view a model holding ``count`` short entries.

    :param view: the view to fill.
    :param count: how many rows to leave it showing.
    :returns: the model, for driving further row changes.
    """
    model = view.model()
    if not isinstance(model, QStringListModel):
        model = QStringListModel(view)
        view.setModel(model)
    model.setStringList([f"*.tmp{index}" for index in range(count)])
    return model


def chrome(view: ContentSizedListView) -> int:
    """The height ``view`` spends on anything that is not a row, read off a known row count.

    :param view: a view showing at least one row.
    :returns: the frame (and any scrollbar) height its size hint carries on top of its rows.
    """
    model = view.model()
    assert model is not None
    return view.sizeHint().height() - model.rowCount() * view.sizeHintForRow(0)


def test_it_never_scrolls_vertically(qtbot: QtBot) -> None:
    """The view is sized to its rows, so a vertical scrollbar would have nothing to scroll to.

    **Test steps:**

    * build a view and fill it well past any plausible visible height
    * verify its vertical scrollbar policy is always-off and its vertical size policy is fixed
    """
    view = ContentSizedListView()
    qtbot.addWidget(view)

    fill(view, 50)

    assert view.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert view.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Fixed


def test_the_size_hint_grows_by_a_row_for_every_row_added(qtbot: QtBot) -> None:
    """The hint is exactly its rows' height, so the enclosing scroll area sees the whole list (#229).

    **Test steps:**

    * fill a view with three rows, then with ten
    * verify the hint is the row count times a row's height, plus the same chrome either way
    """
    view = ContentSizedListView()
    qtbot.addWidget(view)

    fill(view, 3)
    three = view.sizeHint().height()
    fill(view, 10)
    ten = view.sizeHint().height()

    row = view.sizeHintForRow(0)
    assert ten - three == 7 * row
    assert ten == 10 * row + chrome(view)


def test_a_one_row_list_is_one_row_tall(qtbot: QtBot) -> None:
    """A single entry gets a single row's height and no more.

    **Test steps:**

    * fill a view with one row
    * verify its hint is that row plus the chrome
    """
    view = ContentSizedListView()
    qtbot.addWidget(view)

    fill(view, 1)

    assert view.sizeHint().height() == view.sizeHintForRow(0) + chrome(view)


def test_an_emptied_list_stays_exactly_one_row_tall(qtbot: QtBot) -> None:
    """Emptying the list floors it at one row, sized by the rows it just held.

    A list collapsed to a sliver is one there is nowhere to drop a first entry into, and an estimated
    row height is one that can differ from what the style actually draws.

    **Test steps:**

    * fill a view, read its one-row height, then empty its model
    * verify it still asks for exactly that height
    """
    view = ContentSizedListView()
    qtbot.addWidget(view)
    model = fill(view, 4)
    one_row = view.sizeHintForRow(0) + chrome(view)

    model.setStringList([])

    assert view.sizeHint().height() == one_row


def test_a_list_that_never_held_a_row_is_still_a_legible_band(qtbot: QtBot) -> None:
    """With no row ever measured, the font's line height stands in -- never nothing at all.

    **Test steps:**

    * build a view and give it nothing, not even a model
    * verify it asks for a line of text's worth of height
    """
    view = ContentSizedListView()
    qtbot.addWidget(view)

    assert view.sizeHint().height() == view.fontMetrics().height() + 2 * view.frameWidth()


def test_the_minimum_and_preferred_heights_agree(qtbot: QtBot) -> None:
    """Both hints are the rows' height: a list given more is blank space below its last entry.

    **Test steps:**

    * fill a view
    * verify its minimum size hint's height matches its size hint's
    """
    view = ContentSizedListView()
    qtbot.addWidget(view)

    fill(view, 6)

    assert view.minimumSizeHint().height() == view.sizeHint().height()


def test_removing_a_row_re_advertises_the_height(qtbot: QtBot) -> None:
    """A row taken out shrinks the view there and then, without waiting for a resize.

    **Test steps:**

    * show a filled view inside its own window, then remove a row from its model
    * verify its height fell by exactly one row
    """
    view = ContentSizedListView()
    qtbot.addWidget(view)
    model = fill(view, 5)
    view.show()
    qtbot.waitExposed(view)
    row = view.sizeHintForRow(0)
    before = view.sizeHint().height()

    model.removeRow(0)

    assert view.sizeHint().height() == before - row


def test_a_replacement_model_is_the_one_the_height_follows(qtbot: QtBot) -> None:
    """A view handed a second model is sized by *its* rows, and stops listening to the first.

    A view is given its model after construction and may be given another, so the size wiring cannot
    live in the constructor the way it could on a list widget that owns its own model.

    **Test steps:**

    * fill a view, then hand it a second model holding twice as many rows
    * verify the height followed the new model
    * add rows to the *old* model and verify the height did not move
    """
    view = ContentSizedListView()
    qtbot.addWidget(view)
    first = fill(view, 2)
    row = view.sizeHintForRow(0)

    second = QStringListModel([f"*.bak{index}" for index in range(4)], view)
    view.setModel(second)

    assert view.sizeHint().height() == 4 * row + chrome(view)

    settled = view.sizeHint().height()
    first.setStringList([f"*.old{index}" for index in range(20)])

    assert view.sizeHint().height() == settled


def test_a_view_stripped_of_its_model_falls_back_to_the_one_row_floor(qtbot: QtBot) -> None:
    """Detaching the model leaves no rows to be sized by, which is the emptied-list case.

    **Test steps:**

    * fill a view, then take its model away entirely
    * verify it asks for exactly one row's worth of height
    """
    view = ContentSizedListView()
    qtbot.addWidget(view)
    fill(view, 5)
    one_row = view.sizeHintForRow(0) + 2 * view.frameWidth()

    view.setModel(None)

    assert view.sizeHint().height() == one_row
