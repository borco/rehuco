"""System tray icon: close-to-tray with an explicit Quit while enabled (#205, [[nodes#single-instance]])."""

from typing import Final, Protocol, runtime_checkable

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

SHOW_ACTION_TEXT: Final = "Show"
HIDE_ACTION_TEXT: Final = "Hide"
QUIT_ACTION_TEXT: Final = "Quit"

ACTIVATION_REASONS_TOGGLE: Final = (
    QSystemTrayIcon.ActivationReason.Trigger,
    QSystemTrayIcon.ActivationReason.DoubleClick,
)
"""Which clicks on the icon itself toggle the window, mirroring the menu's own top entry (#205).

Both rather than just one: which of the two a desktop actually delivers for a single click is
platform-dependent (``Trigger`` on Windows/most Linux desktops, ``DoubleClick`` on some), and treating
whichever arrives the same way means never having to guess which this desktop uses."""


@runtime_checkable
class TrayWindow(Protocol):
    """The shape `TrayIcon` needs from the window it shows/hides and can quit -- `MainWindow`'s own,
    kept structural (matching `SettingsPage`'s style) so this module never has to import
    `MainWindow` back, since `MainWindow` is what owns a `TrayIcon`.
    """

    def isVisible(self) -> bool:  # noqa: N802  (Qt API name)  # pylint: disable=invalid-name  # pyright: ignore[reportReturnType]
        """Whether the window is currently shown."""

    def hide_to_tray(self) -> None:
        """Hide the window to the tray, taking every floating dock window with it."""

    def raise_and_activate(self) -> None:
        """Show the window, restoring it first if minimized, and bring it to the foreground."""

    def request_quit(self) -> None:
        """Ask the window to close as an explicit quit, running the same guarded-close path a window
        close does."""


class TrayIcon(QSystemTrayIcon):
    """The tray icon shown while tray mode is on (#205): a menu toggling ``window``'s visibility, and
    the one explicit way out while it is -- ``Quit``.

    Left-clicking or double-clicking the icon itself also toggles visibility -- the same action the
    menu's top entry runs (:data:`ACTIVATION_REASONS_TOGGLE`).

    :param window: the window this icon shows/hides and can quit.
    :param icon: the icon to show in the tray.
    """

    def __init__(self, window: TrayWindow, icon: QIcon) -> None:
        super().__init__(icon)
        self.__window: Final = window
        self.__menu: Final = QMenu()
        self.__toggle_action: Final = self.__menu.addAction(SHOW_ACTION_TEXT)
        self.__toggle_action.triggered.connect(self.__toggle_window)
        self.__menu.aboutToShow.connect(self.__resync_toggle_action_text)
        self.__menu.addSeparator()
        quit_action = self.__menu.addAction(QUIT_ACTION_TEXT)
        quit_action.triggered.connect(window.request_quit)
        self.setContextMenu(self.__menu)
        self.activated.connect(self.__on_activated)

    def __resync_toggle_action_text(self) -> None:
        """Read fresh off the window every time the menu is about to show (the same lazy-resync
        idiom `MainWindow`'s own menus use, e.g. ``__resync_close_actions_enabled``): visibility can
        change from outside a click on this icon -- the window's own titlebar, taskbar entry, or a
        forwarded open from a second process -- so a value cached at construction would go stale.
        """
        self.__toggle_action.setText(HIDE_ACTION_TEXT if self.__window.isVisible() else SHOW_ACTION_TEXT)

    def __toggle_window(self) -> None:
        """Hide the window if shown, or bring it to the foreground if not."""
        if self.__window.isVisible():
            self.__window.hide_to_tray()
        else:
            self.__window.raise_and_activate()

    def __on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """Toggle the window for a click reason that means "the icon itself was clicked", ignoring
        the rest (context menu requests and the middle-click ``MiddleClick`` reason, which this icon
        assigns no action to).

        :param reason: which kind of activation this was.
        """
        if reason in ACTIVATION_REASONS_TOGGLE:
            self.__toggle_window()
