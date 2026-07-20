"""Cycle an action through follow-system/light/dark theme modes."""

from typing import Final

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QAction

from .action_icon_theme_handler import ActionIconThemeHandler
from .theme_model import ThemeModel


class ThemeManager(QObject):
    """Cycles ``action`` through ``model``'s ``Qt.ColorScheme.Unknown``/``Light``/``Dark`` mode on
    each click, reflecting the current mode on the action's icon. ``Unknown`` doubles as "follow
    system": there is no separate mode enum, since Qt's own three scheme values already say
    exactly what's needed.

    Reads and writes ``model.mode`` -- never ``QApplication.styleHints().colorScheme()`` directly,
    which reports the *resolved* appearance and would conflate "explicitly Light" with "``Unknown``,
    currently resolving to Light" (see :class:`~borco_pyside.theming.ThemeModel`, #57) -- and reacts
    to ``model.mode_changed``, so it starts, and stays, in step with whatever mode is already active
    (a persisted choice applied before this is constructed, or a change made elsewhere, e.g. a
    ``View`` menu wired the same way via :class:`~borco_pyside.theming.ThemeMenu`) without either
    side polling or reaching into the other's internals.

    Each mode's icon is kept themed via an internal :class:`~borco_pyside.theming.ActionIconThemeHandler`
    (swapping its source SVG on every mode change instead of setting a plain, uncolored icon), so
    ``action``'s glyph always contrasts with the app's current theme, the same as any other themed
    action.

    A ``QObject``, parented to ``action`` by default -- ``ThemeManager(model, action, ...)`` alone
    is enough, with nothing to hold onto: Qt destroys it along with ``action``.

    :param model: the shared theme mode, e.g. also wired to a ``View`` menu's
        :class:`~borco_pyside.theming.ThemeMenu`.
    :param action: the action to wire as the theme-cycling control.
    :param default_icon: icon shown while in ``Qt.ColorScheme.Unknown`` (follow system).
    :param light_icon: icon shown while in ``Qt.ColorScheme.Light``.
    :param dark_icon: icon shown while in ``Qt.ColorScheme.Dark``.
    :param parent: optional Qt parent; defaults to ``action`` itself.
    """

    __SCHEME_CYCLE: Final = (Qt.ColorScheme.Unknown, Qt.ColorScheme.Light, Qt.ColorScheme.Dark)

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        model: ThemeModel,
        action: QAction,
        default_icon: str,
        light_icon: str,
        dark_icon: str,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent if parent is not None else action)
        self.__model = model
        self.__scheme_icon: Final = {
            Qt.ColorScheme.Unknown: default_icon,
            Qt.ColorScheme.Light: light_icon,
            Qt.ColorScheme.Dark: dark_icon,
        }
        self.__icon_handler: Final = ActionIconThemeHandler(action, default_icon, self)

        action.triggered.connect(self.__on_triggered)
        model.mode_changed.connect(self.__on_mode_changed)
        self.__on_mode_changed(model.mode)

    def __on_triggered(self) -> None:
        index = self.__SCHEME_CYCLE.index(self.__model.mode)
        self.__model.mode = self.__SCHEME_CYCLE[(index + 1) % len(self.__SCHEME_CYCLE)]

    def __on_mode_changed(self, mode: Qt.ColorScheme) -> None:
        """Reflect ``mode``, themed, on the action's icon.

        :param mode: the mode now active, whichever control it was set from.
        """
        self.__icon_handler.set_icon(self.__scheme_icon[mode])
