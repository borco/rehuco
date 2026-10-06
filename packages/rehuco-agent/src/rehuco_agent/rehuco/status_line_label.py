"""A status line of two parts that elides the second first (#462)."""

from typing import override

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget

PARTS_SEPARATOR = " — "
"""What stands between the two parts."""


class StatusLineLabel(QLabel):
    """A one-line label of a **primary** part and an optional **secondary** one after it, elided to whatever width it
    is given: the secondary part shortens first, with ``…`` at its end, and goes altogether before the primary part
    does; only then does the primary part shorten, also at its end. The whole, un-elided line is its tooltip, and
    :attr:`full_text`.

    Its horizontal size policy is ``Ignored``, so a long line never widens its layout.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__primary = ""
        self.__secondary = ""
        self.setTextFormat(Qt.TextFormat.PlainText)
        policy = self.sizePolicy()
        policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
        self.setSizePolicy(policy)

    @property
    def full_text(self) -> str:
        """The whole line, as it reads when it fits."""
        if self.__secondary:
            return f"{self.__primary}{PARTS_SEPARATOR}{self.__secondary}"
        return self.__primary

    def set_parts(self, primary: str, secondary: str = "") -> None:
        """Set the line.

        :param primary: the part that stays readable longest.
        :param secondary: the part that elides first; empty for none, and then no separator is shown either.
        """
        self.__primary = primary
        self.__secondary = secondary
        self.__render()

    @override
    def minimumSizeHint(self) -> QSize:  # noqa: N802  (Qt API name)
        return QSize(0, super().minimumSizeHint().height())

    @override
    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802  (Qt API name)
        super().resizeEvent(event)
        self.__render()

    @override
    def changeEvent(self, event: QEvent) -> None:  # noqa: N802  (Qt API name)
        if event.type() == QEvent.Type.FontChange:
            self.__render()
        super().changeEvent(event)

    def __render(self) -> None:
        """Show the line elided to the current width, and the whole line as the tooltip."""
        full = self.full_text
        metrics, width = self.fontMetrics(), self.width()
        if metrics.horizontalAdvance(full) <= width:
            shown = full
        else:
            head = self.__primary + PARTS_SEPARATOR
            room = width - metrics.horizontalAdvance(head)
            # a stub of the secondary part is no use: past the first letter or two it is the primary part that matters
            if self.__secondary and room >= metrics.horizontalAdvance("…") * 3:
                shown = head + metrics.elidedText(self.__secondary, Qt.TextElideMode.ElideRight, room)
            else:
                shown = metrics.elidedText(self.__primary, Qt.TextElideMode.ElideRight, width)
        self.setText(shown)
        self.setToolTip(full if full else "")
