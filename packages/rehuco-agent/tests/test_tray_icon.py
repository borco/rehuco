"""Tests for TrayIcon: the tray icon menu and click-to-toggle behavior (#205)."""

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QSystemTrayIcon
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.tray_icon import HIDE_ACTION_TEXT, QUIT_ACTION_TEXT, SHOW_ACTION_TEXT, TrayIcon


def fake_window(mocker: MockerFixture, *, visible: bool) -> object:
    """A `TrayWindow`-shaped stand-in, `isVisible` fixed at ``visible``."""
    window = mocker.MagicMock()
    window.isVisible.return_value = visible
    return window


def test_menu_has_toggle_then_separator_then_quit(qtbot: QtBot, mocker: MockerFixture) -> None:
    """The context menu lists the toggle action first, then Quit, with a separator between (#205).

    **Test steps:**

    * build a `TrayIcon` over a hidden fake window
    * verify the context menu's actions, in order
    """
    del qtbot
    window = fake_window(mocker, visible=False)

    tray_icon = TrayIcon(window, QIcon())  # type: ignore[arg-type]

    menu = tray_icon.contextMenu()
    assert menu is not None
    actions = menu.actions()
    assert actions[0].text() == SHOW_ACTION_TEXT
    assert actions[1].isSeparator()
    assert actions[2].text() == QUIT_ACTION_TEXT


def test_toggle_action_text_reflects_hidden_window(mocker: MockerFixture) -> None:
    """The toggle action reads "Show" while the window is hidden, resynced right before the menu
    shows (#205).

    **Test steps:**

    * build a `TrayIcon` over a hidden fake window
    * fire the menu's ``aboutToShow``
    * verify the toggle action's text
    """
    window = fake_window(mocker, visible=False)
    tray_icon = TrayIcon(window, QIcon())  # type: ignore[arg-type]
    menu = tray_icon.contextMenu()
    assert menu is not None

    menu.aboutToShow.emit()

    assert menu.actions()[0].text() == SHOW_ACTION_TEXT


def test_toggle_action_text_reflects_visible_window(mocker: MockerFixture) -> None:
    """The toggle action reads "Hide" while the window is shown.

    **Test steps:**

    * build a `TrayIcon` over a visible fake window
    * fire the menu's ``aboutToShow``
    * verify the toggle action's text
    """
    window = fake_window(mocker, visible=True)
    tray_icon = TrayIcon(window, QIcon())  # type: ignore[arg-type]
    menu = tray_icon.contextMenu()
    assert menu is not None

    menu.aboutToShow.emit()

    assert menu.actions()[0].text() == HIDE_ACTION_TEXT


def test_toggle_action_hides_a_visible_window(mocker: MockerFixture) -> None:
    """Triggering the toggle action on a visible window hides it, without raising it.

    **Test steps:**

    * build a `TrayIcon` over a visible fake window
    * trigger the toggle action
    * verify ``hide`` was called and ``raise_and_activate`` was not
    """
    window = fake_window(mocker, visible=True)
    tray_icon = TrayIcon(window, QIcon())  # type: ignore[arg-type]
    menu = tray_icon.contextMenu()
    assert menu is not None

    menu.actions()[0].trigger()

    window.hide_to_tray.assert_called_once_with()  # type: ignore[attr-defined]
    window.raise_and_activate.assert_not_called()  # type: ignore[attr-defined]


def test_toggle_action_raises_a_hidden_window(mocker: MockerFixture) -> None:
    """Triggering the toggle action on a hidden window raises it, without hiding it.

    **Test steps:**

    * build a `TrayIcon` over a hidden fake window
    * trigger the toggle action
    * verify ``raise_and_activate`` was called and ``hide`` was not
    """
    window = fake_window(mocker, visible=False)
    tray_icon = TrayIcon(window, QIcon())  # type: ignore[arg-type]
    menu = tray_icon.contextMenu()
    assert menu is not None

    menu.actions()[0].trigger()

    window.raise_and_activate.assert_called_once_with()  # type: ignore[attr-defined]
    window.hide_to_tray.assert_not_called()  # type: ignore[attr-defined]


def test_quit_action_requests_quit(mocker: MockerFixture) -> None:
    """Triggering Quit asks the window for an explicit quit, not a plain close (#205).

    **Test steps:**

    * build a `TrayIcon`
    * trigger the Quit action
    * verify ``request_quit`` was called
    """
    window = fake_window(mocker, visible=True)
    tray_icon = TrayIcon(window, QIcon())  # type: ignore[arg-type]
    menu = tray_icon.contextMenu()
    assert menu is not None

    menu.actions()[2].trigger()

    window.request_quit.assert_called_once_with()  # type: ignore[attr-defined]


def test_a_trigger_activation_toggles_the_window(mocker: MockerFixture) -> None:
    """Left-clicking (``Trigger``) the icon itself toggles the window, the same as the menu's own
    toggle entry (#205).

    **Test steps:**

    * build a `TrayIcon` over a hidden fake window
    * emit ``activated`` with the ``Trigger`` reason
    * verify the window was raised
    """
    window = fake_window(mocker, visible=False)
    tray_icon = TrayIcon(window, QIcon())  # type: ignore[arg-type]

    tray_icon.activated.emit(QSystemTrayIcon.ActivationReason.Trigger)

    window.raise_and_activate.assert_called_once_with()  # type: ignore[attr-defined]


def test_a_double_click_activation_toggles_the_window(mocker: MockerFixture) -> None:
    """Double-clicking the icon toggles the window too -- whichever reason a desktop delivers for a
    single click on it is platform-dependent (#205).

    **Test steps:**

    * build a `TrayIcon` over a hidden fake window
    * emit ``activated`` with the ``DoubleClick`` reason
    * verify the window was raised
    """
    window = fake_window(mocker, visible=False)
    tray_icon = TrayIcon(window, QIcon())  # type: ignore[arg-type]

    tray_icon.activated.emit(QSystemTrayIcon.ActivationReason.DoubleClick)

    window.raise_and_activate.assert_called_once_with()  # type: ignore[attr-defined]


def test_a_context_menu_activation_does_not_toggle_the_window(mocker: MockerFixture) -> None:
    """Right-clicking the icon (``Context``, opening the menu) does not itself toggle the window --
    only the menu's own entries or the two click reasons above do (#205).

    **Test steps:**

    * build a `TrayIcon` over a hidden fake window
    * emit ``activated`` with the ``Context`` reason
    * verify the window was neither raised nor hidden
    """
    window = fake_window(mocker, visible=False)
    tray_icon = TrayIcon(window, QIcon())  # type: ignore[arg-type]

    tray_icon.activated.emit(QSystemTrayIcon.ActivationReason.Context)

    window.raise_and_activate.assert_not_called()  # type: ignore[attr-defined]
    window.hide_to_tray.assert_not_called()  # type: ignore[attr-defined]
