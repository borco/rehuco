"""Shared plumbing for `QIconEngine` subclasses that render fresh on every request."""

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QIcon, QIconEngine, QPainter, QPixmap


def painted_pixmap(engine: QIconEngine, size: QSize, mode: QIcon.Mode, state: QIcon.State) -> QPixmap:
    """Build a transparent pixmap of ``size`` and paint ``engine``'s content into it.

    The shared body every "render fresh, nothing cached at a fixed resolution" icon engine in this
    module needs for its own ``pixmap()`` override -- ``QIconEngine``'s inherited default does not
    clear the pixmap to transparent first, so ``paint()``'s anti-aliased edges blend against whatever
    garbage was already in the newly-allocated pixmap (confirmed empirically wrong without this).

    :param engine: the icon engine to paint, via its own :meth:`~PySide6.QtGui.QIconEngine.paint`.
    :param size: the pixmap's size.
    :param mode: the icon mode to paint (``Normal``, ``Disabled``, ...).
    :param state: the icon state to paint (``Off``, ``On``).
    :returns: the rendered pixmap.
    """
    pixmap = QPixmap(size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    engine.paint(painter, QRect(0, 0, pixmap.width(), pixmap.height()), mode, state)
    painter.end()
    return pixmap
