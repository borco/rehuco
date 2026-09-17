"""Generic PySide6 theming helpers: theme switching, SVG recoloring, and themed action icons."""

from .action_icon_theme_handler import ActionIconThemeHandler
from .application_palette_change_notifier import ApplicationPaletteChangeNotifier
from .checked_chrome import CheckedToolButtonChrome
from .contrast import perceived_brightness, readable_color_on
from .glyph_action_icon_handler import GlyphActionIconThemeHandler
from .glyph_icon import Glyph, glyph_icon
from .svg_recolor import recolor_svg, recolored_svg_icon
from .theme_manager import ThemeManager
from .theme_menu import ThemeMenu
from .theme_model import ThemeModel
from .themed_icons import ThemedIcons, themed_glyph_icon, themed_svg_icon
from .utils import as_drawn_icon, read_resource_bytes

__all__ = [
    "ActionIconThemeHandler",
    "ApplicationPaletteChangeNotifier",
    "CheckedToolButtonChrome",
    "Glyph",
    "GlyphActionIconThemeHandler",
    "ThemeManager",
    "ThemeMenu",
    "ThemeModel",
    "ThemedIcons",
    "as_drawn_icon",
    "glyph_icon",
    "perceived_brightness",
    "read_resource_bytes",
    "readable_color_on",
    "recolor_svg",
    "recolored_svg_icon",
    "themed_glyph_icon",
    "themed_svg_icon",
]
