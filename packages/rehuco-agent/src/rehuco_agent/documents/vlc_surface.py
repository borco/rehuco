"""The native window libvlc draws into ([[plugins#in-app-player]], #315, #319)."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QWidget


class VlcSurface(QWidget):
    """A plain widget with a native window of its own, handed to libvlc once by its window id.

    Qt re-parents the same native window through every dock move -- floating, re-docking, tabbing, pinning -- so the
    id never changes and libvlc keeps drawing (#315). Black, like a video surface, so the moment before the first frame
    is not the window's background.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors)
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(Qt.GlobalColor.black))
        self.setPalette(palette)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
