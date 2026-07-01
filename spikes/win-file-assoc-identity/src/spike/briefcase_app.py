"""Minimal Briefcase-packaged app — AUMID + icon only, no single-instance logic.

Purpose: verify that a Briefcase-generated Windows exe carries an embedded icon so that
pinning to the taskbar shows the rehuco icon, not Python's generic icon (the gap identified
by the uv entry-point launcher test in Q6).

This is the Q6b check from the spike checklist. Keep the module; delete when the spike is done.
"""

import ctypes
import sys
from typing import Final

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow

import spike.resources_rc  # noqa: F401  # type: ignore  # registers Qt resources as side-effect

AUMID: Final = "Rehuco.Agent.Spike"


def main() -> int:
    """Show a minimal window to verify Briefcase exe icon and pin identity.

    :returns: process exit code.
    """
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(AUMID)

    app = QApplication(sys.argv)
    icon = QIcon(":/icon.ico")  # QIcon requires QApplication to exist first
    app.setWindowIcon(icon)

    window = QMainWindow()
    window.setWindowTitle("Rehuco Spike — Briefcase build")
    window.setWindowIcon(icon)
    label = QLabel("Pin this to the taskbar and check the icon identity.")
    label.setMargin(16)
    window.setCentralWidget(label)
    window.resize(480, 120)
    window.show()

    return app.exec()
