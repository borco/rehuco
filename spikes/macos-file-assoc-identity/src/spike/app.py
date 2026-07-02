"""Spike (issue #13, macOS half of #1): .app bundle file association + QFileOpenEvent + single-instance.

Answers the sharp question: can a double-clicked ``.rehuspike`` file reliably open in a
*single running* PySide6 instance, with correct native app identity, on macOS?

Uses ``.rehuspike`` (not ``.rehu``) as the test extension so the throwaway UTI/CFBundleDocumentTypes
registration this spike's Briefcase build performs never collides with a real future ``.rehu``
association.

Keep the *lesson* (README wiring notes); delete this toy GUI afterwards.
"""

import logging
import sys
from typing import Final, override

from borco_pyside.core.application_singleton import ApplicationSingleton
from PySide6.QtCore import QEvent
from PySide6.QtGui import QFileOpenEvent
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QPlainTextEdit, QVBoxLayout, QWidget

logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s: %(message)s")
LOG: Final = logging.getLogger(__name__)

APP_ID: Final = "macos-file-assoc-identity-spike"
"""Stable per-app identifier for :class:`ApplicationSingleton`'s local-server name.

Deliberately not ``"rehuco-agent"`` so this spike's server never collides with a real
future agent process running on the same machine.
"""


class SpikeWindow(QMainWindow):
    """Minimal window that shows which path was opened and logs forwarded paths.

    Enough to verify: (a) a ``QFileOpenEvent`` delivers the double-clicked path, (b) a
    second double-click (or forwarded open) routes here rather than spawning a new process.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("rehuco macOS file-assoc spike")

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        self.__header: Final = QLabel("(no file opened yet)")
        layout.addWidget(self.__header)

        layout.addWidget(QLabel("All opened paths (QFileOpenEvent + forwarded second instances):"))
        self.__log: Final = QPlainTextEdit()
        self.__log.setReadOnly(True)
        layout.addWidget(self.__log)

        self.resize(640, 400)

    def append_opened(self, path: str) -> None:
        """Record a newly opened path in the header and the running log.

        :param path: filesystem path delivered via ``QFileOpenEvent`` or argv forwarding.
        """
        self.__header.setText(f"Last opened: {path}")
        self.__log.appendPlainText(path)
        LOG.info("opened: %s", path)

    def append_forwarded(self, args: list[str]) -> None:
        """Append paths forwarded from a second instance to the on-screen log.

        :param args: ``sys.argv[1:]`` of the second instance.
        """
        for path in args:
            self.append_opened(path)


class Application(QApplication):
    """The single ``QApplication``; routes ``QFileOpenEvent`` (macOS double-click delivery) to the window.

    :param argv: process argv, forwarded to the ``QApplication`` base constructor.
    """

    def __init__(self, argv: list[str]) -> None:
        super().__init__(argv)
        self.window: Final = SpikeWindow()

    @override
    def event(self, event: QEvent) -> bool:
        if isinstance(event, QFileOpenEvent):
            self.window.append_opened(event.file())
            return True
        return super().event(event)


def main() -> int:
    """Claim the single-instance role (or forward to the existing one) and start the event loop.

    :returns: process exit code; ``0`` immediately if this process forwarded to a running primary.
    """
    app = Application(sys.argv)

    singleton = ApplicationSingleton()
    if not singleton.setup(APP_ID):
        # A primary is already running; it received our argv via the socket.
        return 0

    singleton.other_instance_run.connect(app.window.append_forwarded)
    for path in sys.argv[1:]:
        app.window.append_opened(path)

    app.window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
