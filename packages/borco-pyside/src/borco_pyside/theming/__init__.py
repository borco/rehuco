"""Generic PySide6 theming helpers: theme switching, SVG recoloring, and themed action icons."""

from borco_pyside.theming.action_icon_theme_handler import ActionIconThemeHandler
from borco_pyside.theming.glyph_action_icon_handler import GlyphActionIconThemeHandler
from borco_pyside.theming.glyph_icon import glyph_icon
from borco_pyside.theming.svg_recolor import recolor_svg, recolored_svg_icon
from borco_pyside.theming.theme_manager import ThemeManager
from borco_pyside.theming.theme_menu import ThemeMenu
from borco_pyside.theming.theme_model import ThemeModel

__all__ = [
    "ActionIconThemeHandler",
    "GlyphActionIconThemeHandler",
    "ThemeManager",
    "ThemeMenu",
    "ThemeModel",
    "glyph_icon",
    "recolor_svg",
    "recolored_svg_icon",
]
