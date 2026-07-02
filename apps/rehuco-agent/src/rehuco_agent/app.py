"""QApplication wiring: single-instance guard, argv/QFileOpenEvent routing to viewer windows (§5.4)."""

import logging
from typing import Final, override

from borco_pyside.core import ApplicationSingleton
from PySide6.QtCore import QEvent
from PySide6.QtGui import QFileOpenEvent, QIcon
from PySide6.QtWidgets import QApplication

from rehuco_agent import main_rc  # noqa: F401  # pylint: disable=unused-import  # registers :/icons/... resources
from rehuco_agent.viewer_window import ViewerWindow

LOG: Final = logging.getLogger(__name__)

APP_ID: Final = "rehuco-agent"
"""Stable per-app identifier for :class:`ApplicationSingleton`'s local-server name."""

ICON_RESOURCE: Final = ":/icons/rehuco-agent.svg"
"""qrc path to the app icon, registered by importing :mod:`rehuco_agent.main_rc`."""


class Application(QApplication):
    """The single ``QApplication``, opening one :class:`ViewerWindow` per requested path.

    Handles both argv-based opens (Windows ProgID ``"%1"`` forwarding) and ``QFileOpenEvent``
    (macOS double-click delivery) -- see §5.4.

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
        self.__windows: list[ViewerWindow] = []
        """Open viewer windows, kept alive by this list (Qt does not own top-level widgets)."""

    @override
    def event(self, event: QEvent) -> bool:
        if isinstance(event, QFileOpenEvent):
            self.open_path(event.file())
            return True
        return super().event(event)  # pragma: no cover  (see __init__: no real instance to hit this on)

    def open_path(self, path: str) -> ViewerWindow:
        """Open ``path`` in a new :class:`ViewerWindow` and show it.

        :param path: filesystem path to a ``.rehu`` file.
        :returns: the newly created window.
        """
        window = ViewerWindow(path)
        window.show()
        self.__windows.append(window)
        return window


def run(argv: list[str]) -> int:
    """Claim the single-instance role (or forward to the existing one) and start the event loop.

    :param argv: process argv (``sys.argv``); ``argv[1:]`` are ``.rehu`` paths to open immediately.
    :returns: process exit code; ``0`` immediately if this process forwarded to a running primary.
    """
    app = Application(argv)
    singleton = ApplicationSingleton(app)
    if not singleton.setup(APP_ID):
        return 0

    def open_forwarded(paths: list[str]) -> None:
        for path in paths:
            app.open_path(path)

    singleton.other_instance_run.connect(open_forwarded)
    open_forwarded(argv[1:])

    return app.exec()
