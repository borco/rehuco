"""An image that takes the width it is given and keeps its proportions (#378)."""

from typing import override

from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QImage, QPainter, QPaintEvent
from PySide6.QtWidgets import QSizePolicy, QWidget


class ScaledImage(QWidget):
    """Draws an image no wider than itself and no larger than it is, centred, with the height that keeps its
    proportions.

    Its width comes from the layout and never from the image -- the policy is ``Ignored`` horizontally and the minimum
    is nothing -- so showing a large picture cannot widen the pane it is in; only its height follows, through
    :meth:`heightForWidth`. A small image is drawn as it is, not stretched.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__image: QImage | None = None
        policy = QSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    @property
    def image(self) -> QImage | None:
        """The image shown, or ``None``."""
        return self.__image

    def set_image(self, image: QImage | None) -> None:
        """Show an image, or nothing.

        :param image: the image; ``None`` or a null image shows nothing and takes no height.
        """
        self.__image = None if image is None or image.isNull() else image
        self.updateGeometry()
        self.update()

    @override
    def hasHeightForWidth(self) -> bool:  # noqa: N802  (Qt API name)
        return True

    @override
    def heightForWidth(self, width: int) -> int:  # noqa: N802  (Qt API name)
        image = self.__image
        if image is None:
            return 0
        return max(1, round(image.height() * min(width, image.width()) / image.width()))

    @override
    def sizeHint(self) -> QSize:  # noqa: N802  (Qt API name)
        return QSize(0, self.heightForWidth(self.width()))

    @override
    def minimumSizeHint(self) -> QSize:  # noqa: N802  (Qt API name)
        return QSize(0, 0)

    @override
    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802  (Qt API name)
        del event
        image = self.__image
        if image is None:
            return
        width = min(self.width(), image.width())
        height = self.heightForWidth(self.width())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(QRect((self.width() - width) // 2, 0, width, height), image)
        painter.end()

    def drawn_size(self) -> QSize:
        """How large the image is drawn at the width the widget has now.

        :returns: the size; empty with no image.
        """
        image = self.__image
        if image is None:
            return QSize(0, 0)
        return QSize(min(self.width(), image.width()), self.heightForWidth(self.width()))
