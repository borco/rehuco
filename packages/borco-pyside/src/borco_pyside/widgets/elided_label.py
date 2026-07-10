"""A `QLabel` that middle-elides its text to fit its width, optionally keeping a hyperlink target."""

import html
from typing import override

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget


class ElidedLabel(QLabel):
    """A `QLabel` that middle-elides its text to whatever width it is given, re-eliding on resize, so
    a long value never forces the label (or its layout neighbors) wider than the space available.

    Its horizontal size policy is ``Ignored`` -- the label takes the width the layout hands it and
    shortens the text to fit, rather than dictating width from its content. Set the content with
    :meth:`set_text`, not ``setText``. When a ``href`` is given, the visible (elided) text is wrapped
    in a hyperlink to the **full** target, so the link stays clickable while only the display is
    shortened (pair with ``setOpenExternalLinks(True)`` or a ``linkActivated`` connection). While the
    text is actually elided, the full text is shown in a tooltip (cleared once it fits again).

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__full = ""
        self.__href = ""
        policy = self.sizePolicy()
        policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
        self.setSizePolicy(policy)

    def set_text(self, text: str, href: str = "") -> None:
        """Set the full text (and optional hyperlink target), then render it elided to the current width.

        :param text: the full, un-elided text.
        :param href: the hyperlink target the elided text links to; empty for plain text.
        """
        self.__full = text
        self.__href = href
        self.__render()

    @override
    def minimumSizeHint(self) -> QSize:  # noqa: N802  (Qt API name)
        # zero-width minimum so a long value can never force this label (or its layout) wider -- the
        # text elides to fit instead; the default QLabel minimum is its longest unbreakable word.
        return QSize(0, super().minimumSizeHint().height())

    @override
    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802  (Qt API name)
        super().resizeEvent(event)
        self.__render()

    def __render(self) -> None:
        """Re-render the label with the full text middle-elided to the current width, showing the
        full text in a tooltip only while it is actually elided."""
        if not self.__full:
            self.setText("")
            self.setToolTip("")
            return
        elided = self.fontMetrics().elidedText(self.__full, Qt.TextElideMode.ElideMiddle, self.width())
        escaped = html.escape(elided)
        self.setText(f'<a href="{html.escape(self.__href)}">{escaped}</a>' if self.__href else escaped)
        self.setToolTip(self.__full if elided != self.__full else "")
