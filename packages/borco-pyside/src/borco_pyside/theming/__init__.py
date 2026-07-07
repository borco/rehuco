"""Generic PySide6 theming helpers: theme switching, SVG recoloring, and themed action icons."""

from borco_pyside.theming.action_icon_theme_handler import ActionIconThemeHandler
from borco_pyside.theming.svg_recolor import recolor_svg, recolored_svg_icon
from borco_pyside.theming.theme_manager import ThemeManager

__all__ = [
    "ActionIconThemeHandler",
    "ThemeManager",
    "recolor_svg",
    "recolored_svg_icon",
]
