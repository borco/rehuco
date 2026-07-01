"""Spike (issue #1, Windows half): ProgID file association + AUMID app identity.

Answers the sharp question: can a ``uv tool``-generated ``rehuco-agent.exe`` launcher
achieve a correct HKCU ProgID default double-click handler for ``.rehu``, a correct
taskbar icon/pin/running indicator via AUMID, and single-instance routing of a second
double-click — all without a frozen PyInstaller binary?

Uses ``.rehuspike`` (not ``.rehu``) as the test extension to avoid polluting any real
``.rehu`` association while the spike is in play.

Keep the *lesson* (README wiring notes); delete this toy GUI afterwards.
"""

import argparse
import ctypes
import logging
import sys
from pathlib import Path
from typing import Final

from borco_pyside.core.application_singleton import ApplicationSingleton
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QPlainTextEdit, QVBoxLayout, QWidget
from registry import register_folder_open, register_progid, unregister_folder_open, unregister_progid

# ---------------------------------------------------------------------------
# Spike constants
# ---------------------------------------------------------------------------

AUMID: Final = "Rehuco.Agent.Spike"
"""Application User Model ID used for taskbar grouping and jump-list identity.

This is a throwaway value for the spike; it does not pre-decide the production AUMID
(that is Briefcase's job, per §16.8).
"""

APP_ID: Final = "win-file-assoc-identity-spike"
"""Stable per-app identifier for ApplicationSingleton's local-server name.

Deliberately not ``"rehuco-agent"`` so this spike's server never collides with a real
future agent process running on the same machine.
"""

PROGID: Final = "Rehuco.SpikeFile"
EXTENSION: Final = "rehuspike"

_SPIKE_DIR: Final = Path(__file__).parent
ICO_PATH: Final = _SPIKE_DIR / "rehuco-spike.ico"

logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s: %(message)s")


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------


class SpikeWindow(QMainWindow):
    """Minimal window that shows which path was opened and logs forwarded paths.

    Enough to verify: (a) the correct icon appears in the taskbar, (b) a second
    double-click routes here rather than spawning a new process.

    :param opened_path: the file path this instance was launched with, if any.
    """

    def __init__(self, opened_path: str) -> None:
        super().__init__()
        self.setWindowTitle(f"rehuco file-assoc spike — {opened_path or '(no file)'}")
        if ICO_PATH.exists():
            self.setWindowIcon(QIcon(str(ICO_PATH)))

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        self.__header: Final = QLabel(f"Opened: {opened_path or '(launched directly, no file)'}")
        layout.addWidget(self.__header)

        layout.addWidget(QLabel("Second-instance paths forwarded here:"))
        self.__log: Final = QPlainTextEdit()
        self.__log.setReadOnly(True)
        layout.addWidget(self.__log)

        self.resize(640, 400)

    def append_forwarded(self, args: list[str]) -> None:
        """Append a forwarded argv from a second instance to the on-screen log.

        :param args: ``sys.argv[1:]`` of the second instance (typically the file path).
        """
        self.__log.appendPlainText(" ".join(args) if args else "(empty argv)")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    """Run the spike: register, unregister, or show the GUI.

    AUMID is set here as the very first executable statement, before constructing
    QApplication or any widget.  Windows binds the AUMID to a process's first
    top-level HWND at window-creation time (used for taskbar grouping and jump lists);
    calling SetCurrentProcessExplicitAppUserModelID after a window already exists has
    no retroactive effect.  QApplication's constructor does not itself create a window,
    but the first QMainWindow().show() call does — so the safe rule is: call before
    everything.

    :returns: process exit code.
    """
    # Must be the very first statement — see docstring.
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(AUMID)

    parser = argparse.ArgumentParser(description="rehuco Windows file-assoc + AUMID spike")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--register", action="store_true", help="write HKCU ProgID and extension binding, then exit")
    group.add_argument("--unregister", action="store_true", help="remove HKCU ProgID and extension binding, then exit")
    parser.add_argument("file", nargs="?", default="", help="file path passed by Explorer on double-click")
    args = parser.parse_args()

    python_exe = str(Path(sys.executable).resolve())
    script = str(Path(__file__).resolve())

    if args.register:
        if not ICO_PATH.exists():
            print(f"ERROR: icon not found at {ICO_PATH}", file=sys.stderr)
            print("Run the magick convert command from the README first.", file=sys.stderr)
            return 1
        register_progid(PROGID, python_exe, script, str(ICO_PATH), EXTENSION, AUMID, "Rehuco File")
        register_folder_open("Open with Rehuco", str(ICO_PATH), python_exe, script)
        print(f"Registered .{EXTENSION} → {PROGID} and folder context menu")
        return 0

    if args.unregister:
        unregister_progid(PROGID, EXTENSION)
        unregister_folder_open()
        print(f"Unregistered .{EXTENSION} / {PROGID} and folder context menu")
        return 0

    # GUI path: enforce single-instance, then show the window.
    app = QApplication(sys.argv)

    singleton = ApplicationSingleton()
    if not singleton.setup(APP_ID):
        # A primary is already running; it received our argv via the socket.
        return 0

    window = SpikeWindow(args.file)
    singleton.other_instance_run.connect(window.append_forwarded)
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
