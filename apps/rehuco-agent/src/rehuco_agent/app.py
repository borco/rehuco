"""QApplication wiring: single-instance guard, argv/QFileOpenEvent routing to the main window
([[nodes#single-instance]]).
"""

import logging
from typing import Final, override

import PySide6QtAds as QtAds
from borco_pyside.core import ApplicationSingleton
from borco_pyside.logging import setup_console_logging
from borco_pyside.theming import read_resource_bytes, recolored_svg_icon
from borco_pyside.widgets import (
    LineEditClearActionFilter,
    MessageBanner,
    MessageBannerSeverity,
    MessageBannerSeverityStyle,
)
from PySide6.QtCore import QEvent
from PySide6.QtGui import QColor, QFileOpenEvent, QFontDatabase, QIcon
from PySide6.QtWidgets import QApplication

from rehuco_agent import main_rc  # noqa: F401  # pylint: disable=unused-import  # registers :/icons/... resources
from rehuco_agent.fields.colors import ERROR_COLOR, INFO_COLOR, WARNING_COLOR
from rehuco_agent.glyphs import CLEAR_ACTION_GLYPH
from rehuco_agent.main_window import MainWindow
from rehuco_agent.settings.persistent_settings import persistent_settings

LOG: Final = logging.getLogger(__name__)

APP_ID: Final = "rehuco-agent"
"""Stable per-app identifier for :class:`ApplicationSingleton`'s local-server name."""

ICON_RESOURCE: Final = ":/icons/rehuco-agent.svg"
"""qrc path to the app icon, registered by importing :mod:`rehuco_agent.main_rc`."""

WARNING_BANNER_ICON_RESOURCE: Final = ":/icons/banner_warning.svg"
"""qrc path to the inline notice banner's ``warning`` severity icon (#94)."""

INFO_BANNER_ICON_RESOURCE: Final = ":/icons/banner_info.svg"
"""qrc path to the inline notice banner's ``info`` severity icon (#94)."""

ERROR_BANNER_ICON_RESOURCE: Final = ":/icons/banner_error.svg"
"""qrc path to the inline notice banner's ``error`` severity icon (#94)."""

ICON_FONT_RESOURCES: Final = (
    ":/fonts/Phosphor-Bold.ttf",
    ":/fonts/Phosphor-Fill.ttf",
)
"""qrc paths to the custom icon fonts loaded at startup: bold (every action/toggle/close-button glyph
in :mod:`rehuco_agent.glyphs`, plus :data:`~borco_pyside.qtads.QtAdsFocusTracker.CLOSE_BUTTON_FONT`)
and fill (the rating field's filled stars). Thin, Light, and regular were each vendored for
experimentation but never ended up with a sole consumer once bold covered every glyph, so they're
pruned (#37). No
``Phosphor-Duotone.ttf`` -- Phosphor's duotone rendering isn't implemented in the font files at all,
only in their web/Flutter packages, so a glyph drawn from it can only ever be a flat, single-color
silhouette ([[appendices.theming_and_styling#duotone-font-limitation]])."""


class Application(QApplication):
    """The single ``QApplication``, holding the one :class:`MainWindow` every path opens into.

    Handles both argv-based opens (Windows ProgID ``"%1"`` forwarding) and ``QFileOpenEvent``
    (macOS double-click delivery) -- see [[nodes#single-instance]]. The main window is deliberately
    **not** built here: a ``QApplication`` must exist before :class:`~borco_pyside.core.ApplicationSingleton`
    can even check whether this process is the primary instance, but building the
    ``QMainWindow``-based dock shell is real, visible work that a forwarding (non-primary) process
    should never do -- see :meth:`show_main_window`, called only once ``run()`` confirms primary.

    :param argv: process argv, forwarded to the ``QApplication`` base constructor.
    """

    def __init__(self, argv: list[str]) -> None:  # pragma: no cover
        # untestable: super().__init__(argv) constructs the real C++-backed QApplication, and
        # Qt permits only one per process -- packages/borco-pyside's tests already construct a
        # plain QApplication earlier in the same session, so a real Application can never be
        # constructed here; mocking away QApplication.__init__ instead risks a crash, since
        # setWindowIcon() below needs a genuinely-constructed object, not a skipped one
        super().__init__(argv)
        self.setWindowIcon(QIcon(ICON_RESOURCE))
        for font_resource in ICON_FONT_RESOURCES:
            QFontDatabase.addApplicationFont(font_resource)
        clear_action_filter = LineEditClearActionFilter(
            CLEAR_ACTION_GLYPH.codepoint, CLEAR_ACTION_GLYPH.family, parent=self
        )
        self.installEventFilter(clear_action_filter)
        # give the inline notice banner (#94) this app's own icons/brand colors for every severity it
        # uses, rather than borco-pyside's generic fallback (MessageBanner.SEVERITY_STYLES's own
        # docstring covers the override seam this uses) -- a shared class-level table, not
        # per-instance, so every DocumentWidget (hence every locked document's banner) picks this up
        # automatically
        MessageBanner.SEVERITY_STYLES.update(
            {
                MessageBannerSeverity.WARNING: self.__severity_style(WARNING_BANNER_ICON_RESOURCE, WARNING_COLOR),
                MessageBannerSeverity.INFO: self.__severity_style(INFO_BANNER_ICON_RESOURCE, INFO_COLOR),
                MessageBannerSeverity.ERROR: self.__severity_style(ERROR_BANNER_ICON_RESOURCE, ERROR_COLOR),
            }
        )
        self.__main_window: MainWindow | None = None

    @staticmethod
    def __severity_style(icon_resource: str, color: str) -> MessageBannerSeverityStyle:  # pragma: no cover
        """Build one inline-notice-banner severity's style: its icon (recolored from ``icon_resource``)
        and the same ``color`` for the row's left-border accent.

        Reachable only from ``__init__`` (see its own untestability note) -- never called on its own.

        :param icon_resource: qrc path to the severity's source SVG icon.
        :param color: the accent color, for both the icon and the border.
        :returns: the built style.
        """
        return MessageBannerSeverityStyle(
            margin_color=color, icon=recolored_svg_icon(read_resource_bytes(icon_resource), QColor(color))
        )

    @override
    def event(self, event: QEvent) -> bool:
        if isinstance(event, QFileOpenEvent):  # macOS double-click/"Open With" delivery, not argv
            self.open_path(event.file())
            return True
        return super().event(event)  # pragma: no cover  (see __init__: no real instance to hit this on)

    def show_main_window(self) -> MainWindow:
        """Build the main window on first call, then bring it to the foreground every time.

        :returns: the single main window.
        """
        if self.__main_window is None:
            # must run before this process's first CDockManager, whichever window ends up
            # constructing it -- config flags only take effect if set before then. Set here
            # rather than in any one window's own __init__: show_main_window() is currently the
            # earliest point that builds a window at all, and the only one reached solely by the
            # primary instance -- if some other QtAds-based window is ever built before
            # MainWindow, move this call ahead of that construction instead.
            config_flags = QtAds.CDockManager.eConfigFlag
            QtAds.CDockManager.setConfigFlags(
                config_flags.AllTabsHaveCloseButton
                | config_flags.DockAreaHasTabsMenuButton
                | config_flags.MiddleMouseButtonClosesTab
            )
            self.__main_window = MainWindow()
        self.__main_window.raise_and_activate()
        return self.__main_window

    def open_path(self, path: str) -> None:
        """Open ``path`` in the main window's document dock, bringing the window forward.

        :param path: filesystem path to a ``.rehu`` file, or to a directory-scoped resource's
            directory ([[data-model#resource-scoping]], e.g. from the "Open with Rehuco" folder/
            folder-background shell verbs, #43) -- see :meth:`MainWindow.open_path`.
        """
        self.show_main_window().open_path(path)


def run(argv: list[str]) -> int:
    """Claim the single-instance role (or forward to the existing one) and start the event loop.

    :param argv: process argv (``sys.argv``); ``argv[1:]`` are ``.rehu``/directory paths to open
        immediately (see :meth:`Application.open_path`).
    :returns: process exit code; ``0`` immediately if this process forwarded to a running primary.
    """
    setup_console_logging()
    LOG.info("Settings file: %s", persistent_settings().fileName())
    app = Application(argv)
    singleton = ApplicationSingleton(app)
    if not singleton.setup(APP_ID):
        # not primary: setup() already forwarded this process's argv to the existing primary
        return 0

    def open_forwarded(paths: list[str]) -> None:
        for path in paths:
            app.open_path(path)

    # connected before show_main_window() so a forward arriving during startup is never missed
    singleton.other_instance_run.connect(open_forwarded)
    app.show_main_window()
    open_forwarded(argv[1:])  # this (primary) process's own paths, e.g. from Windows ProgID "%1"

    return app.exec()
