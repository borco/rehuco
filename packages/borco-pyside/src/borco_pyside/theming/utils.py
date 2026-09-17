"""Shared plumbing for theming: reading a resource's raw bytes, and `QIconEngine` subclasses that
render fresh on every request.
"""

from PySide6.QtCore import QFile, QIODevice, QRect, QSize, Qt
from PySide6.QtGui import QIcon, QIconEngine, QPainter, QPixmap


def as_drawn_icon(path: str) -> QIcon:
    """Build a ``QIcon`` straight from ``path``, exactly as drawn -- no recolor, no palette subscription.

    The opt-out :func:`~borco_pyside.theming.recolor_svg`'s own docstring calls for: a genuinely
    multi-color source collapses to one flat color under it, so a glyph that is deliberately colored
    (e.g. a red action icon among an otherwise monochrome set) must never reach
    :class:`~borco_pyside.theming.ActionIconThemeHandler` at all. Unlike that handler's icon, this one
    is built once and never rebuilt on a theme change -- the whole point being that nothing here reads
    the palette.

    :param path: the icon to load, Qt resource or filesystem.
    :returns: the icon, unrecolored.
    """
    return QIcon(path)


def read_resource_bytes(path: str) -> bytes:
    """Read ``path`` (Qt resource or filesystem) fully into memory.

    :param path: the file to read, e.g. a ``:/...`` Qt resource path or a plain filesystem path.
    :returns: the file's full contents.
    :raises RuntimeError: if ``path`` cannot be opened for reading.
    """
    file = QFile(path)
    if not file.open(QIODevice.OpenModeFlag.ReadOnly):
        raise RuntimeError(f"cannot open {path!r} for reading")
    try:
        return bytes(file.readAll().data())
    finally:
        file.close()


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
