"""Tests for `ShortcutsPageSettings` -- the Shortcuts page's search text and sort (#344)."""

from PySide6.QtCore import Qt
from rehuco_agent.settings.shortcuts_page_settings import UNSORTED, ShortcutsPageSettings

from rehuco_agent_tests.conftest import FakeSettings


def test_the_view_state_round_trips() -> None:
    """What is saved reads back.

    **Test steps:**

    * save a search, a sort column and a descending order
    * load into a fresh object and verify all three
    """
    store = FakeSettings()
    ShortcutsPageSettings("save", 2, Qt.SortOrder.DescendingOrder).save(store)  # type: ignore[arg-type]

    loaded = ShortcutsPageSettings()
    loaded.load(store)  # type: ignore[arg-type]

    assert loaded == ShortcutsPageSettings("save", 2, Qt.SortOrder.DescendingOrder)


def test_nothing_stored_means_no_search_and_no_sort() -> None:
    """A first run shows every command in declared order.

    **Test steps:**

    * load from an empty store
    * verify an empty search and the unsorted column
    """
    loaded = ShortcutsPageSettings("left over", 1)
    loaded.load(FakeSettings())  # type: ignore[arg-type]

    assert loaded.filter_text == ""
    assert loaded.sort_column == UNSORTED
    assert loaded.sort_order == Qt.SortOrder.AscendingOrder
