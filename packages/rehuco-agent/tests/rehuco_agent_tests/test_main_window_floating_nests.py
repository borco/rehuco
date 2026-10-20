"""Tests that a floating window holding a dock with a nested dock manager survives that manager emptying (#493,
[[appendices.qt-ads#nested-emptied-float]]): the Browsers dock as catalogs change, the Documents dock as its last
document closes, and a document's own sub-docks as the preview moves on."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any, Final
from unittest.mock import MagicMock

import PySide6QtAds as QtAds
import shiboken6
from PySide6.QtCore import QCoreApplication, QEvent
from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.main_window import (
    BROWSERS_DOCK_OBJECT_NAME,
    DOCUMENTS_DOCK_OBJECT_NAME,
    LOG_DOCK_OBJECT_NAME,
    REHUCO_DOCK_OBJECT_NAME,
    MainWindow,
)
from rehuco_core.access import ResourceKey

from .rehuco.test_catalog_docks import (  # noqa: F401  # pylint: disable=unused-import
    OTHER_PATH,
    REHUCO_PATH,
    fixture_cache,
    fixture_cached_rows,
    fixture_catalog,
    fixture_no_open_scan,
    fixture_saves,
    fixture_served,
)
from .test_main_window import main_dock, mock_persistent_settings  # noqa: F401  # pylint: disable=unused-import

pytestmark = mark.usefixtures("stub_settings_pages", "stub_sub_docks")
"""Every window here is built over stub settings pages, and every document it opens over stub sub-docks (#545), but
where a test asks for the real ones (``real_settings_pages``, ``real_sub_docks``)."""

NEW_PATH: Final = Path("/fake/new.rehuco")


# region fixtures and helpers
@fixture(name="window")
def fixture_window(qtbot: QtBot) -> Iterator[MainWindow]:
    """A shown main window, held for the whole test.

    :param qtbot: the test's bot, which closes the window at teardown.
    :yields: the window.
    """
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    yield window


def float_over(window: MainWindow, top: str, *bottom: str) -> list[Any]:
    """Float the outer dock ``top`` in a window of its own, with the docks ``bottom`` tabbed together under it.

    :param window: the main window.
    :param top: the object name of the dock that floats first.
    :param bottom: the object names of the docks split below it, tabbed together.
    :returns: every dock placed, ``top`` first.
    """
    dock_manager = window._MainWindow__dock_manager  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    docks = [main_dock(window, name) for name in (top, *bottom)]
    for dock in docks:
        dock.toggleView(True)
    dock_manager.addDockWidgetFloating(docks[0])
    below = dock_manager.addDockWidget(QtAds.BottomDockWidgetArea, docks[1], docks[0].dockAreaWidget())
    for dock in docks[2:]:
        dock_manager.addDockWidget(QtAds.CenterDockWidgetArea, dock, below)
    return docks


def settle() -> None:
    """Let every pending deletion run -- a window QtAds retired is gone after this."""
    QCoreApplication.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


def assert_floating_together(window: MainWindow, docks: list[Any]) -> None:
    """Assert every one of ``docks`` lives, open, in one floating window that is on screen, its toggle still on the
    action bar.

    :param window: the main window.
    :param docks: the docks.
    """
    assert all(shiboken6.isValid(dock) for dock in docks)
    container = docks[0].floatingDockContainer()
    assert container is not None and container.isVisible()
    assert all(dock.floatingDockContainer() is container for dock in docks)
    assert not any(dock.isClosed() for dock in docks)
    action_bar = window._MainWindow__ui.action_bar.actions()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    toggles = [dock.toggleViewAction() for dock in docks]
    assert all(toggle in action_bar for toggle in toggles)


# endregion


# region the Browsers dock as catalogs change
def test_changing_catalogs_keeps_a_floating_window_holding_the_browsers_dock(
    cache: MagicMock, served: object, saves: object, mocker: MockerFixture, window: MainWindow
) -> None:
    """The reported layout -- the Root Catalog dock floating over the Browsers and Log docks tabbed together --
    survives opening a catalog, switching to another and creating a new one, each of which lets every browser go
    before the next catalog's come.

    **Test steps:**

    * float the Root Catalog dock over the Browsers and Log docks
    * open a catalog, open another, then create a new one through ``Root Catalog`` > ``New...``
    * verify after each that the three docks live, open, in one floating window, their toggles on the action bar
    """
    del cache, served, saves
    docks = float_over(window, REHUCO_DOCK_OBJECT_NAME, BROWSERS_DOCK_OBJECT_NAME, LOG_DOCK_OBJECT_NAME)
    mocker.patch("rehuco_agent.main_window.QFileDialog.getSaveFileName", return_value=(str(NEW_PATH), ""))

    assert window.open_rehuco_path(REHUCO_PATH)
    settle()
    assert_floating_together(window, docks)

    assert window.open_rehuco_path(OTHER_PATH)
    settle()
    assert_floating_together(window, docks)

    window._MainWindow__on_new_rehuco()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    settle()
    assert_floating_together(window, docks)
    browsers = window._MainWindow__browsers_dock  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    assert len(browsers.open_browsers()) == 1


# endregion


# region the Documents dock and a document's sub-docks
def test_closing_the_last_document_keeps_a_floating_window_holding_the_documents_dock(window: MainWindow) -> None:
    """The Documents dock floating with the Log dock below it survives its last document closing.

    Opens a path that does not exist, which yields a real (locked) document dock.

    **Test steps:**

    * float the Documents dock over the Log dock and open a document
    * close it as ``File`` > ``Close`` does
    * verify both docks live, open, in one floating window, and no document is left
    """
    docks = float_over(window, DOCUMENTS_DOCK_OBJECT_NAME, LOG_DOCK_OBJECT_NAME)
    window.open_file("missing.rehu")
    documents = window._MainWindow__documents_dock  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    assert documents.open_document_widgets()

    documents.close_focused_document()
    settle()

    assert_floating_together(window, docks)
    assert not documents.open_document_widgets()


def test_the_preview_moving_on_keeps_a_floating_window_holding_the_documents_dock(window: MainWindow) -> None:
    """A preview moving on to a document another holder already has takes the last one's sub-docks out of the host
    they share before building the next one's, emptying its manager for a moment; the floating window holding the
    Documents dock stays.

    **Test steps:**

    * float the Documents dock over the Log dock and preview one document
    * hold a second document in the registry, as another holder would, and preview it
    * verify both docks live, open, in one floating window, and the preview shows the second document
    """
    docks = float_over(window, DOCUMENTS_DOCK_OBJECT_NAME, LOG_DOCK_OBJECT_NAME)
    documents = window._MainWindow__documents_dock  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    registry = window._MainWindow__document_registry  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    second = ResourceKey(Path("second_missing.rehu").resolve())
    documents.show_in_preview(ResourceKey(Path("first_missing.rehu").resolve()))
    settle()
    held = registry.acquire(second)

    documents.show_in_preview(second)
    settle()

    assert_floating_together(window, docks)
    preview = documents.preview_document_widget()
    assert preview is not None and preview.model is held
    registry.release(held)


# endregion
