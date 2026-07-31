"""A word-wrapping `QLabel` that reports the height its text actually needs at its current width."""

from typing import override

from PySide6.QtCore import QSize
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget


class WrappingLabel(QLabel):
    """A word-wrapping `QLabel` whose size hints answer with the wrapped height, not the one-line one.

    A `QLabel` with ``wordWrap`` on still computes its ``sizeHint`` as though the text were laid out on
    a single wide line, and a layout allocates from that hint -- so a paragraph is handed one line's
    height and paints past whatever frame holds it. Declaring ``heightForWidth`` on the size policy is
    the documented route and is not enough on its own, because it corrects what the layout asks *after*
    the hint it started from; this reports the wrapped height as the hint as well, the way `RichTextView`
    does for its rendered document.

    The height is measured from the label's *own* width, which is safe only because the hint is
    re-advertised from ``resizeEvent`` and only on a width change: the layout hands out a width, the new
    width is measured, and the corrected height is allocated in the next pass, which changes no width and
    so ends there. Text is set with ``setText`` as on any `QLabel`; the ``parent``-only signature keeps
    this promotable inside a ``.ui``, like `ElidedLabel`.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWordWrap(True)
        policy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    @override
    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802  (Qt API name)
        super().resizeEvent(event)
        # width-only guard: the wrapped height folds on width alone, and answering a height change --
        # which is this widget's own hint being applied -- would re-advertise geometry without end
        if event.size().width() != event.oldSize().width():
            self.updateGeometry()

    @override
    def sizeHint(self) -> QSize:  # noqa: N802  (Qt API name)
        return QSize(self.width(), self.__wrapped_height())

    @override
    def minimumSizeHint(self) -> QSize:  # noqa: N802  (Qt API name)
        # zero minimum width so a long word can never force the label (or its layout) wider -- it wraps
        return QSize(0, self.__wrapped_height())

    def __wrapped_height(self) -> int:
        """The height this label's text needs at its current width.

        :returns: the wrapped height, or `QLabel`'s own hint height while the label has no width to
            wrap to -- wrapping at zero puts one word per line and answers with a useless height.
        """
        if self.width() <= 0:
            return super().sizeHint().height()
        return self.heightForWidth(self.width())
