"""Recolored :class:`QIcon`s for the app's SVGs, kept per (icon, color) pair (#248, #266).

Recoloring rewrites the SVG and builds an icon engine, which is far too much to do on every repaint of
every row -- and a model that draws a glyph per row repaints constantly. So the built icons are held,
keyed by the pair that produced them.

Lives here rather than beside either of its callers: the task queue's State column (#248) was the first
to need it and the file browser's two icon columns (#266) are the second, and a cache of *this app's
SVGs recolored* is neither surface's property. Nothing about it knows which icons exist -- that is each
caller's own mapping, the same division :mod:`rehuco_agent.item_action_icons` keeps.
"""

from borco_pyside.theming import recolored_svg_icon
from borco_pyside.theming.utils import read_resource_bytes
from PySide6.QtGui import QColor, QIcon


# one method is the whole of it: a cache that also decided *which* icon, or what color, would be two
# things -- those are the caller's and the delegate's
# pylint: disable-next=too-few-public-methods
class SvgIconCache:
    """Recolored icons, built once per (resource path, color) pair.

    The pairs are few and bounded -- a handful of glyphs against the handful of colors a theme puts on a
    row -- so holding them all costs nothing, and a theme switch simply asks for colors not seen yet
    rather than needing to be told anything.
    """

    def __init__(self) -> None:
        self.__icons: dict[tuple[str, int], QIcon] = {}

    def icon(self, path: str, color: QColor) -> QIcon:
        """The glyph at ``path``, recolored to ``color``.

        :param path: the icon's resource path.
        :param color: the color to draw it in.
        :returns: the icon, built on first ask and kept.
        """
        key = (path, color.rgba())
        held = self.__icons.get(key)
        if held is None:
            held = recolored_svg_icon(read_resource_bytes(path), color)
            self.__icons[key] = held  # pylint: disable=unsupported-assignment-operation
        return held
