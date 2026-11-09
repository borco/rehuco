"""One line of middle-elided text that is itself the link revealing the location (#621): how the location
reads in the Main Viewer and the Main Editor ([[plugins#field-toolkit]]).
"""

from typing import override

from borco_pyside.widgets import ElidedLabel
from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget

from ..colors import WARNING_COLOR


class LocationLine(ElidedLabel):
    """The location text, middle-elided to fit, drawn as a link while there is something to open.

    The link is underlined in the palette's link color, which `ElidedLabel` re-draws on a palette change,
    so a live theme toggle reaches it. Clicking it emits :attr:`open_requested`; this widget reveals
    nothing itself, its owner decides what "open" means. While :meth:`set_openable` is ``False`` -- a
    document with no local path has nothing to reveal -- the text is plain and nothing is clickable.

    :param hint: the tooltip's second line, naming what a click does.
    :param parent: optional Qt parent.
    """

    open_requested = Signal()

    def __init__(self, hint: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent, rich=True)
        self.__hint = hint
        self.__text = ""
        self.__openable = False
        self.__warning = False
        self.linkActivated.connect(lambda _href: self.open_requested.emit())

    def set_location(self, text: str) -> None:
        """Show ``text`` as the elided location, a link while openable.

        :param text: the full, un-elided text; empty for none.
        """
        self.__text = text
        self.__render()

    @override
    def set_text(self, text: str, href: str = "", hint: str = "") -> None:
        """:meth:`set_location`; the link target and the hint are this line's own, so a caller's are ignored.

        :param text: the full, un-elided text; empty for none.
        :param href: ignored.
        :param hint: ignored.
        """
        self.set_location(text)

    def set_openable(self, openable: bool) -> None:
        """Make the text a link, or plain text again.

        :param openable: whether there is something to open.
        """
        self.__openable = openable
        self.__render()

    def set_warning(self, warning: bool) -> None:
        """Draw the text in the warning color, plain or link; through the markup, never a stylesheet or a
        palette, so a theme change keeps reaching the label (`ElidedLabel.link_color`).

        :param warning: whether to warn.
        """
        self.__warning = warning
        self.__render()

    @override
    def link_color(self) -> QColor:
        return QColor(WARNING_COLOR) if self.__warning else super().link_color()

    @override
    def text_color(self) -> QColor | None:
        return QColor(WARNING_COLOR) if self.__warning else None

    def __render(self) -> None:
        """Hand the text to the label, with the link target while openable and there is text."""
        link = self.__openable and bool(self.__text)
        ElidedLabel.set_text(self, self.__text, href="#open" if link else "", hint=self.__hint)
