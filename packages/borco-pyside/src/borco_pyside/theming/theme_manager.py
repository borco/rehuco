"""Cycle an action through follow-system/light/dark theme modes."""

from typing import Final

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication

from borco_pyside.theming.action_icon_theme_handler import ActionIconThemeHandler


class ThemeManager(QObject):
    """Cycles ``action`` through ``Qt.ColorScheme.Unknown``/``Light``/``Dark`` on each click,
    applying the chosen scheme via ``QStyleHints`` and reflecting it on the action's icon.
    ``Unknown`` doubles as "follow system": there is no separate mode enum, since Qt's own three
    scheme values already say exactly what's needed.

    Starts in ``Qt.ColorScheme.Unknown`` -- Qt's own default before any override is ever applied --
    so launching fresh always matches the OS. Clicking back to ``Unknown`` is also how to restore
    OS live-tracking after pinning ``Light``/``Dark``: an explicit scheme override otherwise
    disables that tracking for the rest of the process.

    Each mode's icon is kept themed via an internal :class:`~borco_pyside.theming.ActionIconThemeHandler`
    (swapping its source SVG on every mode change instead of setting a plain, uncolored icon), so
    ``action``'s glyph always contrasts with the app's current theme, the same as any other themed
    action.

    A ``QObject``, parented to ``action`` by default -- ``ThemeManager(action, ...)`` alone is
    enough, with nothing to hold onto: Qt destroys it along with ``action``.

    :param action: the action to wire as the theme-cycling control.
    :param system_icon: icon shown while in ``Qt.ColorScheme.Unknown`` (follow system).
    :param light_icon: icon shown while in ``Qt.ColorScheme.Light``.
    :param dark_icon: icon shown while in ``Qt.ColorScheme.Dark``.
    :param parent: optional Qt parent; defaults to ``action`` itself.
    """

    __SCHEME_CYCLE: Final = (Qt.ColorScheme.Unknown, Qt.ColorScheme.Light, Qt.ColorScheme.Dark)

    def __init__(
        self,
        action: QAction,
        system_icon: str,
        light_icon: str,
        dark_icon: str,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent if parent is not None else action)
        self.__scheme_icon: Final = {
            Qt.ColorScheme.Unknown: system_icon,
            Qt.ColorScheme.Light: light_icon,
            Qt.ColorScheme.Dark: dark_icon,
        }
        self.__scheme_index = 0
        self.__icon_handler: Final = ActionIconThemeHandler(action, system_icon, self)

        action.triggered.connect(self.__on_triggered)
        self.__apply_scheme(self.__SCHEME_CYCLE[self.__scheme_index])

    def __on_triggered(self) -> None:
        self.__scheme_index = (self.__scheme_index + 1) % len(self.__SCHEME_CYCLE)
        self.__apply_scheme(self.__SCHEME_CYCLE[self.__scheme_index])

    def __apply_scheme(self, scheme: Qt.ColorScheme) -> None:
        """Apply ``scheme`` and reflect it, themed, on the action's icon.

        :param scheme: the color scheme to switch to.
        """
        QApplication.styleHints().setColorScheme(scheme)
        self.__icon_handler.set_icon(self.__scheme_icon[scheme])
