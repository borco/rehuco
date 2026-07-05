"""QApplication wiring: single-instance guard, argv/QFileOpenEvent routing to the main window
([[nodes#single-instance]]).
"""

import logging
from typing import Final, override

import PySide6QtAds as QtAds
from borco_pyside.core import ApplicationSingleton
from PySide6.QtCore import QEvent
from PySide6.QtGui import QFileOpenEvent, QIcon
from PySide6.QtWidgets import QApplication

from rehuco_agent import main_rc  # noqa: F401  # pylint: disable=unused-import  # registers :/icons/... resources
from rehuco_agent.main_window import MainWindow

LOG: Final = logging.getLogger(__name__)

APP_ID: Final = "rehuco-agent"
"""Stable per-app identifier for :class:`ApplicationSingleton`'s local-server name."""

ICON_RESOURCE: Final = ":/icons/rehuco-agent.svg"
"""qrc path to the app icon, registered by importing :mod:`rehuco_agent.main_rc`."""


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
        self.__main_window: MainWindow | None = None

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
            # constructing it: the CDockFocusController that emits focusedDockWidgetChanged
            # (which DocumentsDock listens to) is only built when this flag is set -- off by
            # default, per typings/PySide6QtAds/__init__.pyi's focusedDockWidgetChanged docstring.
            # Set here rather than in any one window's own __init__: show_main_window() is
            # currently the earliest point that builds a window at all, and the only one reached
            # solely by the primary instance -- if some other QtAds-based window is ever built
            # before MainWindow, move this call ahead of that construction instead.
            QtAds.CDockManager.setConfigFlag(QtAds.CDockManager.FocusHighlighting, True)
            self.__main_window = MainWindow()
        self.__main_window.raise_and_activate()
        return self.__main_window

    def open_path(self, path: str) -> None:
        """Open ``path`` in the main window's document dock, bringing the window forward.

        :param path: filesystem path to a ``.rehu`` file.
        """
        self.show_main_window().open_file(path)


def run(argv: list[str]) -> int:
    """Claim the single-instance role (or forward to the existing one) and start the event loop.

    :param argv: process argv (``sys.argv``); ``argv[1:]`` are ``.rehu`` paths to open immediately.
    :returns: process exit code; ``0`` immediately if this process forwarded to a running primary.
    """
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
