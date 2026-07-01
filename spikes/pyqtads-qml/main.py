"""Spike (issue #4): pyqtads + QML integration regression check.

Throwaway toy GUI that stress-tests the three parts A0 will depend on:

1. a QQuickWidget dock **detaches to a floating window and re-docks** without glitches;
2. a **QWidgets dock and a QML dock coexist** in one CDockManager layout;
3. **layout save/restore** with a QML dock present — including whether **closed/hidden
   docks restore their size** (the known soft spot; this app also tries the stash-size-on-
   close workaround so we can compare with the raw saveState/restoreState blob).

Run:  uv run --python 3.14 --with PySide6 --with PySide6QtAds python main.py
(or use the sibling `.venv` — see README.md).

Keep the *lesson* (README notes) and the tiny wiring snippet; delete this toy GUI afterwards.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Final

import PySide6QtAds as QtAds
from PySide6.QtCore import QByteArray, QObject, QUrl, Signal, Slot
from PySide6.QtGui import QTextCursor
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

QML_FILE: Final = Path(__file__).parent / "qml" / "scene.qml"
LAYOUT_FILE: Final = Path(__file__).parent / "layout_state.bin"


class Bridge(QObject):
    """Context object exposed to QML as `bridge`; proves the wiring survives detach.

    :param parent: owning QObject.
    """

    pinged = Signal(str)
    click_count_changed = Signal(int)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__click_count = 0

    @Slot(str)
    def ping(self, message: str) -> None:
        """Receive a call from QML and bump the click counter.

        :param message: text sent from the QML button.
        """
        self.__click_count += 1
        self.click_count_changed.emit(self.__click_count)
        self.pinged.emit(message)

    def get_click_count(self) -> int:
        """Return the number of pings received.

        :returns: current click count.
        """
        return self.__click_count

    # exposed to QML as `bridge.click_count`
    from PySide6.QtCore import Property  # noqa: PLC0415  (kept local to the spike)

    click_count = Property(int, get_click_count, notify=click_count_changed)  # type: ignore[call-overload]


class QmlDockContent(QWidget):
    """Hosts the QML scene inside a plain QWidget so it can go into a CDockWidget.

    :param bridge: context object injected into the QML root context.
    :param parent: parent widget.
    """

    def __init__(self, bridge: Bridge, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        quick = QQuickWidget(self)
        quick.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        quick.rootContext().setContextProperty("bridge", bridge)
        quick.setSource(QUrl.fromLocalFile(str(QML_FILE)))
        layout.addWidget(quick)


class SpikeWindow(QMainWindow):
    """Main window wiring one QML dock and two QWidget docks under one CDockManager."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("pyqtads + QML spike (issue #4)")
        self.resize(1100, 720)

        self.__bridge: Final = Bridge(self)
        self.__log: Final = QPlainTextEdit()
        self.__log.setReadOnly(True)
        self.__bridge.pinged.connect(lambda msg: self.__append_log(f"QML → Python: {msg}"))

        self.__dock_manager: Final = QtAds.CDockManager(self)
        # remember each dock's containing-splitter sizes at close time, keyed by object
        # name — the workaround for QtAds not restoring hidden-dock size from the blob.
        self.__stashed_sizes: dict[str, list[int]] = {}

        self.__build_docks()
        self.__build_menu()

    def __build_docks(self) -> None:
        """Create the QML dock plus two QWidget docks and place them in the layout."""
        qml_dock = QtAds.CDockWidget("QML view")
        qml_dock.setObjectName("qml_view")
        qml_dock.setWidget(QmlDockContent(self.__bridge))

        table = QTableWidget(6, 3)
        table.setHorizontalHeaderLabels(["A", "B", "C"])
        for r in range(6):
            for c in range(3):
                table.setItem(r, c, QTableWidgetItem(f"{r},{c}"))
        widgets_dock = QtAds.CDockWidget("QWidgets view")
        widgets_dock.setObjectName("widgets_view")
        widgets_dock.setWidget(table)

        log_dock = QtAds.CDockWidget("Event log")
        log_dock.setObjectName("event_log")
        log_dock.setWidget(self.__log)

        # coexistence: QML dock centre, QWidget dock right, log dock bottom
        self.__dock_manager.addDockWidget(QtAds.CenterDockWidgetArea, qml_dock)
        self.__dock_manager.addDockWidget(QtAds.RightDockWidgetArea, widgets_dock)
        self.__dock_manager.addDockWidget(QtAds.BottomDockWidgetArea, log_dock)

        for dock in (qml_dock, widgets_dock, log_dock):
            dock.closeRequested.connect(lambda d=dock: self.__stash_size(d))
            dock.viewToggled.connect(lambda visible, d=dock: self.__restore_size(d) if visible else None)

    def __build_menu(self) -> None:
        """Add Save/Restore-layout and toggle actions to the menu bar."""
        layout_menu = self.menuBar().addMenu("&Layout")
        layout_menu.addAction("&Save layout", self.__save_layout)
        layout_menu.addAction("&Restore layout", self.__restore_layout)

        view_menu = self.menuBar().addMenu("&View")
        for dock in self.__dock_manager.dockWidgetsMap().values():
            view_menu.addAction(dock.toggleViewAction())

    def __stash_size(self, dock: QtAds.CDockWidget) -> None:
        """Record the containing splitter's size distribution before the dock hides.

        The raw layout blob does not restore a closed dock's size (QtAds reopens it at a
        minimal size), so we stash the splitter sizes keyed by object name and re-apply them
        on reopen. Capturing the whole list — rather than one extent — avoids having to map
        the dock to its index within the splitter.

        :param dock: the dock about to close.
        """
        area = dock.dockAreaWidget()
        if area is not None:
            self.__stashed_sizes[dock.objectName()] = self.__dock_manager.splitterSizes(area)
            self.__append_log(
                f"stashed splitter sizes for {dock.objectName()}: {self.__stashed_sizes[dock.objectName()]}"
            )

    def __restore_size(self, dock: QtAds.CDockWidget) -> None:
        """Re-apply the stashed splitter sizes when the dock is shown again.

        :param dock: the dock that just became visible.
        """
        sizes = self.__stashed_sizes.get(dock.objectName())
        area = dock.dockAreaWidget()
        if sizes and area is not None and len(sizes) == len(self.__dock_manager.splitterSizes(area)):
            self.__dock_manager.setSplitterSizes(area, sizes)
            self.__append_log(f"restored splitter sizes for {dock.objectName()}: {sizes}")

    def __save_layout(self) -> None:
        """Persist the dock-manager state blob to disk."""
        state: QByteArray = self.__dock_manager.saveState()
        LAYOUT_FILE.write_bytes(bytes(state.data()))
        self.__append_log(f"saved layout ({state.size()} bytes) → {LAYOUT_FILE.name}")

    def __restore_layout(self) -> None:
        """Restore the dock-manager state blob from disk, if present."""
        if not LAYOUT_FILE.exists():
            self.__append_log("no saved layout to restore")
            return
        state = QByteArray(LAYOUT_FILE.read_bytes())
        ok = self.__dock_manager.restoreState(state)
        self.__append_log(f"restored layout: {'ok' if ok else 'FAILED'}")

    def __append_log(self, text: str) -> None:
        """Append a line to the event-log dock.

        :param text: message to append.
        """
        self.__log.appendPlainText(text)
        self.__log.moveCursor(QTextCursor.MoveOperation.End)


def main() -> int:
    """Launch the spike GUI.

    :returns: process exit code.
    """
    app = QApplication(sys.argv)
    window = SpikeWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
