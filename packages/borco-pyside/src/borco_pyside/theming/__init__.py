"""Generic PySide6 theming helpers: theme switching, SVG recoloring, and themed action icons."""

from .action_icon_theme_handler import ActionIconThemeHandler
from .application_palette_change_notifier import ApplicationPaletteChangeNotifier
from .glyph_action_icon_handler import GlyphActionIconThemeHandler
from .glyph_icon import Glyph, glyph_icon
from .svg_recolor import recolor_svg, recolored_svg_icon
from .theme_manager import ThemeManager
from .theme_menu import ThemeMenu
from .theme_model import ThemeModel
from .utils import as_drawn_icon, read_resource_bytes

__all__ = [
    "ActionIconThemeHandler",
    "ApplicationPaletteChangeNotifier",
    "Glyph",
    "GlyphActionIconThemeHandler",
    "ThemeManager",
    "ThemeMenu",
    "ThemeModel",
    "as_drawn_icon",
    "glyph_icon",
    "read_resource_bytes",
    "recolor_svg",
    "recolored_svg_icon",
]
