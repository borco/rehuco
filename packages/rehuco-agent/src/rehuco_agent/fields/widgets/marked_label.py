"""A line of text with icons right after it (#649)."""

from collections.abc import Sequence
from typing import Final, override

from borco_pyside.theming import read_resource_bytes, recolored_svg_icon
from borco_pyside.widgets import ElidedLabel
from PySide6.QtCore import QEvent, QSize, Signal
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget

TEXT_SLACK: Final = 2
"""Pixels the text's cap is given beyond its advance, so a label exactly as wide as its text never elides it."""


TEXT_STRETCH: Final = 1000
"""The text's stretch against the trailing spacer's 1."""


class MarkedLabel(QWidget):
    """An :class:`~borco_pyside.widgets.ElidedLabel` followed by one icon per marker.

    The text keeps the label's own behaviour -- middle-elided to the width it is given, a link when it has a target --
    but is capped at what the full text needs, so the icons sit right after it rather than at the row's end; when the
    row is squeezed the text elides first and the icons keep their place. The icons are recolored to the palette's
    text color, the disabled one for a disabled widget, and follow a theme switch.

    :param parent: optional Qt parent.
    """

    linkActivated = Signal(str)  # noqa: N815  (mirrors QLabel's)
    """The text's link was clicked, with its target."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__label = ElidedLabel()
        self.__label.linkActivated.connect(self.linkActivated)
        self.__icons: list[QLabel] = []
        self.__paths: tuple[str, ...] = ()
        self.__layout = QHBoxLayout(self)
        self.__layout.setContentsMargins(0, 0, 0, 0)
        # the text outweighs the spacer, so it takes what it needs up to its cap and the spacer takes the rest:
        # without the spacer the capped text is centred in the share it was given
        self.__layout.addWidget(self.__label, TEXT_STRETCH)
        self.__layout.addStretch(1)

    def set_text(self, text: str, href: str = "", tooltip: str = "", icons: Sequence[str] = ()) -> None:
        """Show ``text`` and, after it, an icon for each resource path in ``icons``.

        :param text: the full, un-elided text.
        :param href: the hyperlink target the text links to; empty for plain text.
        :param tooltip: rich text shown over the whole line, icons included, in place of the elided text's own.
        :param icons: the icons' resource paths, drawn in this order.
        """
        self.__label.set_text(text, href, tooltip=tooltip)
        self.__label.setMaximumWidth(self.fontMetrics().horizontalAdvance(text) + TEXT_SLACK)
        self.setToolTip(tooltip)
        self.__paths = tuple(icons)
        self.__show_icons()

    def icon_count(self) -> int:
        """How many icons follow the text."""
        return len(self.__icons)

    @override
    def changeEvent(self, event: QEvent) -> None:  # noqa: N802  (Qt API name)
        """Redraw the icons when their color changes: on a theme switch, and when the widget is enabled or disabled.

        :param event: the Qt change event.
        """
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.EnabledChange):
            self.__show_icons()
        super().changeEvent(event)

    def __show_icons(self) -> None:
        """Draw one icon label per resource path, in the text's current color, reusing the labels already there."""
        while len(self.__icons) > len(self.__paths):
            gone = self.__icons.pop()
            self.__layout.removeWidget(gone)
            gone.deleteLater()
        size = self.fontMetrics().height()
        ratio = self.devicePixelRatioF()
        # the palette's current group is the disabled one while the widget is disabled
        color = self.palette().color(QPalette.ColorRole.WindowText)
        for index, path in enumerate(self.__paths):
            if index == len(self.__icons):
                label = QLabel()
                label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
                label.setFixedSize(size, size)
                self.__layout.insertWidget(self.__layout.count() - 1, label)
                self.__icons.append(label)
            icon = recolored_svg_icon(read_resource_bytes(path), color)
            self.__icons[index].setPixmap(icon.pixmap(QSize(size, size), ratio))
