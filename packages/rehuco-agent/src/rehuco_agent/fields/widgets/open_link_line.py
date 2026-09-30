"""One line of elided plain text followed by an ``(open)`` link (#389): how the location reads in the Main
Viewer and the Main Editor ([[plugins#field-toolkit]]).
"""

import html
from typing import Final, override

from borco_pyside.widgets import ElidedLabel
from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget


class OpenLinkLabel(QLabel):
    """The ``(open)`` link: a rich-text label whose anchor is drawn in the palette's link color and
    re-drawn when the palette changes, so a live theme toggle reaches it (a hardcoded anchor color
    would stay blue -- the bug `~borco_pyside.widgets.ElidedLabel`'s own links had).

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTextFormat(Qt.TextFormat.RichText)
        self.__render()

    @override
    def changeEvent(self, event: QEvent) -> None:  # noqa: N802  (Qt API name)
        if event.type() == QEvent.Type.PaletteChange:
            self.__render()
        super().changeEvent(event)

    def __render(self) -> None:
        """Set the anchor around ``open`` in the current link color."""
        color = html.escape(self.palette().color(QPalette.ColorRole.Link).name())
        # the gap from the text rides in the label as a non-breaking space, so it follows the font
        self.setText(f'&nbsp;(<a href="#open" style="color:{color};">open</a>)')


class OpenLinkLine(QWidget):
    """Plain text that middle-elides to fit, then an ``(open)`` link that stays whole: the text is an
    `ElidedLabel` taking the spare width, the link a separate label that is never elided or pushed out.

    The link is hidden while :meth:`set_openable` is ``False`` -- a document with no path yet has nothing
    to reveal. Clicking it emits :attr:`open_requested`; this widget reveals nothing itself, its owner
    decides what "open" means.

    :param hint: the link's tooltip, naming what a click does.
    :param parent: optional Qt parent.
    """

    open_requested = Signal()

    def __init__(self, hint: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__text_label: Final = ElidedLabel()
        self.__link_label: Final = OpenLinkLabel()
        self.__link_label.setToolTip(hint)
        policy = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        # a rich-text label is taller than the plain one beside it: keeping its size while hidden holds the
        # line's height the same with or without a path, which `PathEditor.header_height` promises
        policy.setRetainSizeWhenHidden(True)
        self.__link_label.setSizePolicy(policy)
        self.__link_label.linkActivated.connect(lambda _href: self.open_requested.emit())
        self.__link_label.hide()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.__text_label, 1)
        layout.addWidget(self.__link_label)

    @property
    def text_label(self) -> ElidedLabel:
        """The elided text, for a caller that styles it (the editor's warning color)."""
        return self.__text_label

    @property
    def link_label(self) -> QLabel:
        """The ``(open)`` link label."""
        return self.__link_label

    def set_text(self, text: str) -> None:
        """Show ``text`` as the elided plain text.

        :param text: the full, un-elided text; empty for none.
        """
        self.__text_label.set_text(text)

    def set_openable(self, openable: bool) -> None:
        """Show or hide the ``(open)`` link.

        :param openable: whether there is something to open.
        """
        self.__link_label.setVisible(openable)
