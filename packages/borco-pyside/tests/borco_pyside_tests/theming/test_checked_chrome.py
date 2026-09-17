"""Tests for CheckedToolButtonChrome."""

from collections.abc import Callable

from borco_pyside.theming.checked_chrome import CheckedToolButtonChrome
from borco_pyside.theming.contrast import perceived_brightness
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication


def test_a_dark_palette_gets_a_light_glyph(drive_palette: Callable[..., QPalette]) -> None:
    """Measuring a dark checked button's fill yields a light glyph color.

    **Test steps:**

    * drive the palette to the Windows 11 dark theme's button/window colors
    * ask for the checked glyph color
    * verify it is light
    """
    palette = drive_palette("#3c3c3c", "#1e1e1e")

    color = CheckedToolButtonChrome.glyph_color(palette, enabled=True)

    assert perceived_brightness(color) > 0.5


def test_a_light_palette_gets_a_dark_glyph(drive_palette: Callable[..., QPalette]) -> None:
    """And the mirror image, so the answer genuinely tracks the palette rather than being fixed.

    **Test steps:**

    * drive the palette to the Windows 11 light theme's button/window colors
    * ask for the checked glyph color
    * verify it is dark
    """
    palette = drive_palette("#ffffff", "#f3f3f3")

    color = CheckedToolButtonChrome.glyph_color(palette, enabled=True)

    assert perceived_brightness(color) <= 0.5


def test_the_answer_is_memoized_per_style_palette_and_enabledness() -> None:
    """A repeat request is served from the memo rather than painting a probe again.

    A themed icon asks for this on its way to every first paint under a new palette, so the render is
    paid for once per (style, palette, enabled-ness) rather than per icon.

    **Test steps:**

    * ask twice for the same palette and enabled-ness
    * verify one entry was memoized, and the second answer matches the first
    """
    palette = QApplication.palette()

    first = CheckedToolButtonChrome.glyph_color(palette, enabled=True)
    entries = len(CheckedToolButtonChrome.colors)
    second = CheckedToolButtonChrome.glyph_color(palette, enabled=True)

    assert len(CheckedToolButtonChrome.colors) == entries
    assert second.name() == first.name()


def test_enabled_and_disabled_are_measured_separately() -> None:
    """The disabled corner gets its own memo entry, not the enabled one's answer.

    Several styles fill a *disabled* checked button with a neutral shade rather than the accent they
    use when it is enabled, so the two cannot share a measurement.

    **Test steps:**

    * ask for both the enabled and the disabled color under one palette
    * verify two entries were memoized
    """
    palette = QApplication.palette()

    CheckedToolButtonChrome.glyph_color(palette, enabled=True)
    CheckedToolButtonChrome.glyph_color(palette, enabled=False)

    assert len(CheckedToolButtonChrome.colors) == 2
