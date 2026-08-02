"""Tests for ItemListEditor's optional proxy: a filtered view over one model, in **source** rows.

The rest of the widget -- the two columns, the shortcuts, the abandoned-insert rule -- is covered through
`StringListEditor`, which is the unfiltered case. What is here is the seam only a proxy can reach: which
row space a caller and the action columns speak in.
"""

from borco_pyside.widgets import ContentSizedListView, ItemListEditor, StringItemListModel
from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QSortFilterProxyModel
from pytest import fixture
from pytestqt.qtbot import QtBot

ENTRIES = ("alpha", "beta", "gamma", "delta")
"""Four entries, two of which the filter below keeps -- so a source row and a view row genuinely differ."""


class EvenRowsProxy(QSortFilterProxyModel):
    """Shows every other source row, so view row ``1`` is source row ``2``."""

    def filterAcceptsRow(  # noqa: N802  (Qt API name)
        self,
        source_row: int,
        source_parent: QModelIndex | QPersistentModelIndex,
    ) -> bool:
        del source_parent
        return source_row % 2 == 0


@fixture
def editor(qtbot: QtBot) -> ItemListEditor:
    """An editor over :data:`ENTRIES`, seen through :class:`EvenRowsProxy`.

    :param qtbot: the widget-owning fixture.
    :returns: the editor, shown so its view is real.
    """
    model = StringItemListModel()
    widget = ItemListEditor(ContentSizedListView(), model, proxy=EvenRowsProxy())
    qtbot.addWidget(widget)
    model.set_entries(ENTRIES)
    with qtbot.waitExposed(widget):
        widget.show()
    return widget


def test_the_view_shows_the_proxy_and_the_editor_still_holds_the_model(editor: ItemListEditor) -> None:
    """One model, one view onto part of it: a filtered list is not a second code path.

    **Test steps:**

    * verify the view is looking at the proxy, which shows half the rows
    * verify the editor's own ``model`` is still the unfiltered one
    """
    view_model = editor.view.model()
    assert isinstance(view_model, EvenRowsProxy)
    assert view_model.rowCount() == 2
    assert editor.model.rowCount() == len(ENTRIES)


def test_the_current_index_is_a_source_row(editor: ItemListEditor) -> None:
    """``current_index`` is stated in **source** rows -- the space every model call is already in, so the
    action columns hand it straight to the model without knowing a filter exists.

    **Test steps:**

    * make the second *visible* row current
    * verify the reported index is its source row, not its position on screen
    """
    editor.view.setCurrentIndex(editor.view.model().index(1, 0))

    assert editor.current_index == 2


def test_setting_the_current_index_takes_a_source_row(editor: ItemListEditor) -> None:
    """The setter is in the same space as the getter, so a model method's return value can be handed
    straight back -- which is exactly what the two action columns do.

    **Test steps:**

    * select source row ``2``
    * verify the view landed on the row showing that entry, and the getter agrees
    """
    editor.set_current_index(2)

    assert editor.view.currentIndex().data() == "gamma"
    assert editor.current_index == 2


def test_selecting_a_filtered_out_row_selects_nothing(editor: ItemListEditor) -> None:
    """A row the proxy does not show maps to an invalid index, which selects nothing -- the honest answer
    for a row that is not on screen to be current *on*.

    **Test steps:**

    * select a source row the filter hides
    * verify nothing is current
    """
    editor.set_current_index(1)

    assert editor.current_index == -1


def test_a_negative_row_still_selects_nothing(editor: ItemListEditor) -> None:
    """The select-none case is unchanged by a proxy: it never reaches the mapping at all.

    **Test steps:**

    * select a visible row, then a negative one
    * verify nothing is current
    """
    editor.set_current_index(0)

    editor.set_current_index(-1)

    assert editor.current_index == -1
