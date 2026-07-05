"""Tests for MainWindow: the top-level dock-in-dock shell hosting DocumentsDock."""

from pathlib import Path

from PySide6.QtWidgets import QWidget
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.main_window import MainWindow


def test_installs_a_dock_manager_as_the_central_widget(qtbot: QtBot) -> None:
    """Setting up the docking system replaces the `.ui`'s plain central widget with a `CDockManager`.

    **Test steps:**

    * construct a real ``MainWindow`` (real `QtAds` objects, no mocking)
    * find the `.ui`'s original ``centralwidget`` by object name
    * verify it's no longer the current central widget, and was hidden
    """
    window = MainWindow()
    qtbot.addWidget(window)

    original_central = window.findChild(QWidget, "centralwidget")
    assert original_central is not None
    assert window.centralWidget() is not original_central
    assert original_central.isHidden()


def test_open_file_resolves_and_delegates_to_the_documents_dock(mocker: MockerFixture, qtbot: QtBot) -> None:
    """``open_file`` resolves its path and hands it to the documents dock.

    **Test steps:**

    * mock only ``DocumentsDock.open_document`` (the dock itself is real -- it's a real
      ``QWidget`` `CDockWidget.setWidget` requires, so mocking the whole class would break
      ``MainWindow``'s docking setup)
    * construct a ``MainWindow`` and call ``open_file`` with a relative path
    * verify ``open_document`` was called with the resolved absolute path
    """
    open_document = mocker.patch("rehuco_agent.main_window.DocumentsDock.open_document")
    window = MainWindow()
    qtbot.addWidget(window)

    window.open_file("a.rehu")

    open_document.assert_called_once_with(Path("a.rehu").resolve())


def test_raise_and_activate_shows_a_normal_window(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A visible, non-minimized window is shown (not restored), raised, and activated.

    Forces ``sys.platform`` to a non-Windows value so this runs identically on every CI leg,
    without touching the real Windows-only foreground helper.

    **Test steps:**

    * force ``sys.platform`` to ``"linux"`` and mock show/showNormal/raise_/activateWindow
    * call ``raise_and_activate``
    * verify ``show`` (not ``showNormal``) was called, plus ``raise_``/``activateWindow``
    """
    mocker.patch("rehuco_agent.main_window.sys.platform", "linux")
    window = MainWindow()
    qtbot.addWidget(window)
    show = mocker.patch.object(window, "show")
    show_normal = mocker.patch.object(window, "showNormal")
    raise_ = mocker.patch.object(window, "raise_")
    activate = mocker.patch.object(window, "activateWindow")

    window.raise_and_activate()

    show.assert_called_once_with()
    show_normal.assert_not_called()
    raise_.assert_called_once_with()
    activate.assert_called_once_with()


def test_raise_and_activate_restores_a_minimized_window(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A minimized window is restored via ``showNormal()`` instead of ``show()``.

    **Test steps:**

    * force ``sys.platform`` to ``"linux"``, mark the window minimized
    * call ``raise_and_activate``
    * verify ``showNormal`` (not ``show``) was called
    """
    mocker.patch("rehuco_agent.main_window.sys.platform", "linux")
    window = MainWindow()
    qtbot.addWidget(window)
    mocker.patch.object(window, "isMinimized", return_value=True)
    show_normal = mocker.patch.object(window, "showNormal")
    show = mocker.patch.object(window, "show")

    window.raise_and_activate()

    show_normal.assert_called_once_with()
    show.assert_not_called()


def test_raise_and_activate_forces_foreground_on_windows(mocker: MockerFixture, qtbot: QtBot) -> None:
    """On Windows, the process-input-attach foreground helper is invoked with this window.

    **Test steps:**

    * force ``sys.platform`` to ``"win32"`` and mock the Windows-only helper
    * call ``raise_and_activate``
    * verify the helper was called with this window
    """
    mocker.patch("rehuco_agent.main_window.sys.platform", "win32")
    force_foreground = mocker.patch("borco_pyside.platforms.windows.window_activation.force_foreground")
    window = MainWindow()
    qtbot.addWidget(window)
    mocker.patch.object(window, "show")
    mocker.patch.object(window, "raise_")
    mocker.patch.object(window, "activateWindow")

    window.raise_and_activate()

    force_foreground.assert_called_once_with(window)


def test_raise_and_activate_skips_the_windows_helper_elsewhere(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Off Windows, the platform-specific foreground helper is never invoked.

    **Test steps:**

    * force ``sys.platform`` to ``"linux"`` and mock the Windows-only helper
    * call ``raise_and_activate``
    * verify the helper was never called
    """
    mocker.patch("rehuco_agent.main_window.sys.platform", "linux")
    force_foreground = mocker.patch("borco_pyside.platforms.windows.window_activation.force_foreground")
    window = MainWindow()
    qtbot.addWidget(window)
    mocker.patch.object(window, "show")
    mocker.patch.object(window, "raise_")
    mocker.patch.object(window, "activateWindow")

    window.raise_and_activate()

    force_foreground.assert_not_called()
