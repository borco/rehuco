"""A `QRadioButton` that middle-elides its caption to fit its width."""

from typing import override

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QRadioButton, QSizePolicy, QStyle, QWidget


class ElidedRadioButton(QRadioButton):
    """A `QRadioButton` whose caption middle-elides to whatever width it is given, re-eliding on resize, so a long
    caption -- a path -- never forces the button, or the page holding it, wider than the space available.

    The `ElidedLabel` arrangement on a radio: the horizontal size policy is ``Ignored`` and the minimum width is the
    indicator's alone, so the layout decides the width and the caption shortens to fit. The caption is two parts: the
    text, which elides in the middle, and an optional **suffix that never does** -- a version in parentheses after a
    path stays whole however narrow the button gets. Set them with :meth:`set_text`, not ``setText``; while the text
    is shortened, the full caption is the tooltip.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__full = ""
        self.__suffix = ""
        policy = self.sizePolicy()
        policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
        self.setSizePolicy(policy)

    def full_text(self) -> str:
        """The caption as set, suffix included, before any eliding."""
        return self.__full + self.__suffix

    def set_text(self, text: str, suffix: str = "") -> None:
        """Set the caption, then show it elided to the current width.

        :param text: the part that elides.
        :param suffix: the part shown whole after it, however narrow the button.
        """
        self.__full = text
        self.__suffix = suffix
        self.__render()

    @override
    def minimumSizeHint(self) -> QSize:  # noqa: N802  (Qt API name)
        # the indicator's width alone, so a long caption can never force this button (or its layout) wider
        return QSize(self.__indicator_width(), super().minimumSizeHint().height())

    @override
    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802  (Qt API name)
        super().resizeEvent(event)
        self.__render()

    def __indicator_width(self) -> int:
        """The width the indicator and the gap before the caption take.

        :returns: the width in pixels.
        """
        style = self.style()
        return style.pixelMetric(QStyle.PixelMetric.PM_ExclusiveIndicatorWidth, None, self) + style.pixelMetric(
            QStyle.PixelMetric.PM_RadioButtonLabelSpacing, None, self
        )

    def __render(self) -> None:
        """Show the text middle-elided to the width the indicator and the suffix leave, then the suffix, with the full
        caption as the tooltip only while the text is shortened."""
        metrics = self.fontMetrics()
        available = max(0, self.width() - self.__indicator_width() - metrics.horizontalAdvance(self.__suffix))
        elided = metrics.elidedText(self.__full, Qt.TextElideMode.ElideMiddle, available)
        self.setText(elided + self.__suffix)
        self.setToolTip(self.full_text() if elided != self.__full else "")
