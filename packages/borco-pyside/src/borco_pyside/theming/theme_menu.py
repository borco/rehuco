"""Three checkable actions wired to the app's follow-system/light/dark theme mode."""

from typing import Final

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QAction, QActionGroup

from .action_icon_theme_handler import ActionIconThemeHandler
from .theme_model import ThemeModel


class ThemeMenu(QObject):
    """Owns and wires three checkable actions -- e.g. for a ``View`` menu's theme entries -- to
    ``model``'s mode, independently of any other control doing the same (e.g.
    :class:`~borco_pyside.theming.ThemeManager`'s toolbar action): both read/write
    ``model.mode`` -- never ``QApplication.styleHints().colorScheme()`` directly, which reports the
    *resolved* appearance and would conflate "explicitly Light" with "``Unknown``, currently
    resolving to Light" (see :class:`~borco_pyside.theming.ThemeModel`) -- and react to
    ``model.mode_changed`` rather than one polling or reaching into the other's internals, so
    picking a mode in either one shows up in the other.

    Builds :attr:`default_action`/:attr:`light_action`/:attr:`dark_action` itself rather than
    taking them as parameters -- their text ("Default"/"Light"/"Dark") and meaning are fixed by
    this class's own three-mode structure, with no legitimate per-caller variation, so there's
    nothing for a caller to usefully customize. Placing them in an actual menu (position, any
    surrounding separator) is still the caller's job -- add each returned action wherever it
    belongs, the same way :class:`~borco_pyside.dialogs.DockableDialog`'s own ``toggle_action`` is
    built internally and placed by its caller.

    The three actions are put in an exclusive ``QActionGroup`` (owned by this object), so checking
    one via the UI unchecks the other two; whichever one matches the current mode is also kept
    checked whenever the mode changes elsewhere. Each action's icon is kept themed via an internal,
    ``flat`` :class:`~borco_pyside.theming.ActionIconThemeHandler` per action (``flat`` since these
    are menu rows, relying on the native checkmark rather than a highlighted icon to show which one
    is active, same as :class:`~borco_pyside.theming.ActionIconThemeHandler`'s ``companion``
    scenario) -- so all three always contrast with the app's current theme, the same as any other
    themed action.

    A ``QObject``; the three actions are parented to it, so Qt destroys them along with it.

    :param model: the shared theme mode, e.g. also wired to a toolbar's
        :class:`~borco_pyside.theming.ThemeManager`.
    :param default_icon: icon for :attr:`default_action` (``Qt.ColorScheme.Unknown``, follow system).
    :param light_icon: icon for :attr:`light_action` (``Qt.ColorScheme.Light``).
    :param dark_icon: icon for :attr:`dark_action` (``Qt.ColorScheme.Dark``).
    :param parent: optional Qt parent.
    """

    def __init__(
        self,
        model: ThemeModel,
        default_icon: str,
        light_icon: str,
        dark_icon: str,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.__model = model
        self.__default_action = QAction("&Default", self)
        self.__default_action.setCheckable(True)
        self.__light_action = QAction("&Light", self)
        self.__light_action.setCheckable(True)
        self.__dark_action = QAction("Dar&k", self)
        self.__dark_action.setCheckable(True)

        self.__action_scheme: Final = {
            self.__default_action: Qt.ColorScheme.Unknown,
            self.__light_action: Qt.ColorScheme.Light,
            self.__dark_action: Qt.ColorScheme.Dark,
        }
        self.__scheme_action: Final = {scheme: action for action, scheme in self.__action_scheme.items()}
        # kept alive on self -- never read again, but each handler's own signal connections must
        # outlive __init__ (same reasoning as ThemeManager's own single __icon_handler attribute)
        self.__icon_handlers: Final = [  # pylint: disable=unused-private-member
            ActionIconThemeHandler(action, icon, self, flat=True)
            for action, icon in (
                (self.__default_action, default_icon),
                (self.__light_action, light_icon),
                (self.__dark_action, dark_icon),
            )
        ]

        group = QActionGroup(self)
        group.setExclusive(True)
        for action, scheme in self.__action_scheme.items():
            group.addAction(action)
            action.triggered.connect(lambda _checked=False, scheme=scheme: self.__apply(scheme))

        model.mode_changed.connect(self.__on_mode_changed)
        self.__on_mode_changed(model.mode)

    @property
    def default_action(self) -> QAction:
        """Checkable action for ``Qt.ColorScheme.Unknown`` (follow system)."""
        return self.__default_action

    @property
    def light_action(self) -> QAction:
        """Checkable action for ``Qt.ColorScheme.Light``."""
        return self.__light_action

    @property
    def dark_action(self) -> QAction:
        """Checkable action for ``Qt.ColorScheme.Dark``."""
        return self.__dark_action

    def __apply(self, scheme: Qt.ColorScheme) -> None:
        self.__model.mode = scheme

    def __on_mode_changed(self, mode: Qt.ColorScheme) -> None:
        """Check whichever action matches ``mode``, unchecking the other two via the exclusive group.

        :param mode: the mode now active, whichever control it was set from.
        """
        self.__scheme_action[mode].setChecked(True)
