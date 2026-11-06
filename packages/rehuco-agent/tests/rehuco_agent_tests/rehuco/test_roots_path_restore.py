"""Tests for the Root Catalog's current row across a restart ([[plugins#session-restore]], #576)."""

from pathlib import Path
from typing import Any, Final
from uuid import UUID

from pytest import mark
from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco.roots_node import NodeListing
from rehuco_agent.settings.catalog_state_store import CatalogState

from rehuco_agent_tests.conftest import MemoryCatalogStateStore
from rehuco_agent_tests.mapped_roots import location_at

from .test_catalog_docks import (  # noqa: F401  # pylint: disable=unused-import
    REHUCO_ID,
    REHUCO_PATH,
    ROOT_IDS,
    WAIT_TIMEOUT_MS,
    CatalogDocks,
    fixture_cache,
    fixture_cached_rows,
    fixture_catalog,
    fixture_dock,
    fixture_folders,
    fixture_machine,
    fixture_no_open_scan,
    fixture_on_disk,
    fixture_queue,
    fixture_saves,
    fixture_served,
)

FIRST_ROOT: Final = UUID(ROOT_IDS[0])
CATALOG: Final = UUID(REHUCO_ID)


def remember_row(store: MemoryCatalogStateStore, *names: str) -> tuple[UUID, tuple[str, ...]]:
    """Remember a row of the first root for the served catalog.

    :param store: the in-memory store.
    :param names: the names down from the root.
    :returns: the row's key.
    """
    key = (FIRST_ROOT, names)
    store.states[CATALOG] = CatalogState(roots_current=key)
    return key


def current_key(dock: CatalogDocks) -> object:
    """The Roots view's current row, as the model keys it.

    :param dock: the catalog's docks.
    :returns: the key, or ``None``.
    """
    return dock.roots.roots_model.key(dock.roots.roots_view.currentIndex())


def saved_row(store: MemoryCatalogStateStore) -> object:
    """What the served catalog remembers as its current row.

    :param store: the in-memory store.
    :returns: the key, or ``None``.
    """
    return store.states[CATALOG].roots_current


@mark.usefixtures("folders")
def test_the_row_is_walked_back_to_as_the_listings_arrive_and_the_preview_does_not_follow(
    qtbot: QtBot, dock: CatalogDocks, catalog_store: MemoryCatalogStateStore
) -> None:
    """A row two folders down has no index until each folder above it is listed, and walking there is not a selection.

    **Test steps:**

    * remember ``alpha/sub``, and open the catalog
    * verify the current row becomes it, and no record was announced on the way
    """
    key = remember_row(catalog_store, "alpha", "sub")
    announced: list[object] = []
    dock.roots.record_selected.connect(announced.append)

    dock.catalog.open_rehuco(REHUCO_PATH)

    qtbot.waitUntil(lambda: current_key(dock) == key, timeout=WAIT_TIMEOUT_MS)
    assert not announced


@mark.usefixtures("folders")
def test_closing_remembers_the_current_row(
    qtbot: QtBot, dock: CatalogDocks, catalog_store: MemoryCatalogStateStore
) -> None:
    """The row the reader is on is what the catalog remembers, beside the browsers' half of its state.

    **Test steps:**

    * open the catalog and make ``alpha`` current once it is listed
    * close the catalog
    * verify the row is remembered, and so is the browsers' layout
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    model = dock.roots.roots_model
    root = model.index(0, 0)
    qtbot.waitUntil(lambda: model.listing_state(root) is NodeListing.LISTED, timeout=WAIT_TIMEOUT_MS)
    dock.roots.roots_view.setCurrentIndex(model.index_for(FIRST_ROOT, ("alpha",)))

    dock.catalog.close_rehuco()

    assert saved_row(catalog_store) == (FIRST_ROOT, ("alpha",))
    assert catalog_store.states[CATALOG].layout is not None


@mark.usefixtures("folders")
def test_a_name_no_longer_there_ends_the_walk_on_the_deepest_row_that_is(
    qtbot: QtBot, dock: CatalogDocks, catalog_store: MemoryCatalogStateStore
) -> None:
    """A folder listed without the name stops the walk there, and the gone row is not remembered any longer.

    **Test steps:**

    * remember ``alpha/gone``, and open the catalog
    * verify the current row becomes ``alpha``, and that closing remembers ``alpha``
    """
    remember_row(catalog_store, "alpha", "gone")

    dock.catalog.open_rehuco(REHUCO_PATH)

    alpha = (FIRST_ROOT, ("alpha",))
    model = dock.roots.roots_model

    def settled() -> bool:
        """Whether ``alpha`` is current and listed.

        :returns: whether it is.
        """
        return current_key(dock) == alpha and model.listing_state(dock.roots.roots_view.currentIndex()) is (
            NodeListing.LISTED
        )

    qtbot.waitUntil(settled, timeout=WAIT_TIMEOUT_MS)
    qtbot.waitUntil(lambda: not dock.roots.path_restore.held, timeout=WAIT_TIMEOUT_MS)

    dock.catalog.close_rehuco()

    assert saved_row(catalog_store) == alpha


def test_an_offline_root_selects_the_root_and_keeps_the_path_for_when_it_answers(
    qtbot: QtBot, dock: CatalogDocks, catalog_store: MemoryCatalogStateStore, served: dict[str, Any]
) -> None:
    """A run with the root away ends on its row, and costs the remembered path nothing.

    **Test steps:**

    * remember a row under a root whose folder does not exist, and open the catalog
    * verify the root's row is current once it reads as unreachable
    * close the catalog, and verify the whole path is still remembered
    """
    del served
    key = remember_row(catalog_store, "alpha", "sub")

    dock.catalog.open_rehuco(REHUCO_PATH)

    model = dock.roots.roots_model
    root = model.index(0, 0)
    qtbot.waitUntil(lambda: model.listing_state(root) is NodeListing.UNREACHABLE, timeout=WAIT_TIMEOUT_MS)
    qtbot.waitUntil(lambda: current_key(dock) == (FIRST_ROOT, ()), timeout=WAIT_TIMEOUT_MS)

    dock.catalog.close_rehuco()

    assert saved_row(catalog_store) == key


def test_the_walk_goes_on_when_the_offline_root_answers(
    qtbot: QtBot, dock: CatalogDocks, catalog_store: MemoryCatalogStateStore, served: dict[str, Any], tmp_path: Path
) -> None:
    """The path held through an offline start is finished once the root can be listed.

    **Test steps:**

    * remember a row under a folder that does not exist yet, and open the catalog
    * wait for the root to read as unreachable
    * make the folder exist and list the root again
    * verify the row becomes current
    """
    tutorials = tmp_path / "later"
    served["roots"][0]["location"] = location_at(tutorials)
    key = remember_row(catalog_store, "alpha")
    dock.catalog.open_rehuco(REHUCO_PATH)
    model = dock.roots.roots_model
    root = model.index(0, 0)
    qtbot.waitUntil(lambda: model.listing_state(root) is NodeListing.UNREACHABLE, timeout=WAIT_TIMEOUT_MS)

    (tutorials / "alpha").mkdir(parents=True)
    model.relist(root)

    qtbot.waitUntil(lambda: current_key(dock) == key, timeout=WAIT_TIMEOUT_MS)


@mark.usefixtures("folders")
def test_the_reader_moving_overtakes_the_walk(
    qtbot: QtBot, dock: CatalogDocks, catalog_store: MemoryCatalogStateStore
) -> None:
    """A row the reader picks is announced as any selection is, and the walk does not take them away from it.

    **Test steps:**

    * remember ``alpha/sub``, open the catalog and wait for ``alpha`` to be there
    * make the other root's row current
    * verify it stays current once the listings have landed, and is what closing remembers
    """
    remember_row(catalog_store, "alpha", "sub")
    dock.catalog.open_rehuco(REHUCO_PATH)
    model = dock.roots.roots_model
    first, second = model.index(0, 0), model.index(1, 0)
    qtbot.waitUntil(lambda: model.listing_state(first) is NodeListing.LISTED, timeout=WAIT_TIMEOUT_MS)

    dock.roots.roots_view.setCurrentIndex(second)
    assert not dock.roots.path_restore.held
    qtbot.waitUntil(lambda: model.listing_state(second) is NodeListing.LISTED, timeout=WAIT_TIMEOUT_MS)

    other = (UUID(ROOT_IDS[1]), ())
    assert current_key(dock) == other

    dock.catalog.close_rehuco()

    assert saved_row(catalog_store) == other


@mark.usefixtures("folders")
def test_a_root_no_longer_in_the_catalog_restores_nothing(
    qtbot: QtBot, dock: CatalogDocks, catalog_store: MemoryCatalogStateStore
) -> None:
    """A root removed since leaves nothing current, and nothing remembered.

    **Test steps:**

    * remember a row of a root the catalog does not hold, and open it
    * verify nothing becomes current, and closing remembers nothing
    """
    catalog_store.states[CATALOG] = CatalogState(
        roots_current=(UUID("a41b9c3d-0000-4000-8000-00000000ffff"), ("alpha",))
    )

    dock.catalog.open_rehuco(REHUCO_PATH)
    qtbot.waitUntil(lambda: not dock.roots.path_restore.held, timeout=WAIT_TIMEOUT_MS)

    assert current_key(dock) is None

    dock.catalog.close_rehuco()

    assert saved_row(catalog_store) is None


@mark.usefixtures("folders")
def test_a_maximized_browser_comes_back_with_the_catalog(
    qtbot: QtBot, dock: CatalogDocks, catalog_store: MemoryCatalogStateStore
) -> None:
    """The sub-dock filling the Browsers dock is saved beside the layout and maximized again once on screen.

    **Test steps:**

    * open a catalog with two browsers side by side on a shown dock, and maximize the second
    * close the catalog, and verify the store names it
    * open the catalog again, and verify it fills the dock
    """
    dock.browsers.resize(800, 600)
    dock.browsers.show()
    dock.catalog.open_rehuco(REHUCO_PATH)
    dock.browsers.new_browser_action.trigger()
    _, second = dock.browsers.browsers
    second_dock = dock.browsers.browser_dock(second)
    from_handler = dock.browsers._BrowsersDock__maximize_handler  # type: ignore[attr-defined]  # pylint: disable=protected-access
    from_handler.maximize(second_dock)
    name = second_dock.objectName()

    dock.catalog.close_rehuco()

    assert catalog_store.states[CATALOG].maximized_dock == name

    dock.catalog.open_rehuco(REHUCO_PATH)

    qtbot.waitUntil(lambda: from_handler.maximized_name == name, timeout=WAIT_TIMEOUT_MS)
    qtbot.waitUntil(lambda: from_handler.maximized_dock is not None, timeout=WAIT_TIMEOUT_MS)
    assert from_handler.maximized_dock.objectName() == name
