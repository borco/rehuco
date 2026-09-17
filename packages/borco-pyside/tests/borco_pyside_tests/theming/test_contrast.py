"""Tests for the contrast helpers."""

from borco_pyside.theming.contrast import perceived_brightness, readable_color_on
from PySide6.QtGui import QColor, QPalette

WIN11_LIGHT_CHROME = "#0067c0"
"""What the `windows11` style fills a checked tool button with under the light theme (measured)."""

WIN11_DARK_CHROME = "#4cc2ff"
"""And under the dark one -- a *pale* blue, which is what made ``HighlightedText`` wrong there."""

FUSION_LIGHT_CHROME = "#dcdcdc"
"""`Fusion` fills with a neutral shade of ``Button`` instead, and uses no accent at all."""

FUSION_DARK_CHROME = "#414141"
"""The same neutral fill under `Fusion`'s dark palette."""


def palette_with(highlighted_text: str, button_text: str) -> QPalette:
    """Build a palette carrying just the two roles the chooser reads.

    :param highlighted_text: the ``HighlightedText`` color.
    :param button_text: the ``ButtonText`` color.
    :returns: the palette.
    """
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(highlighted_text))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(button_text))
    return palette


def test_perceived_brightness_spans_black_to_white() -> None:
    """Brightness runs 0 for black to 1 for white.

    **Test steps:**

    * weigh black and white
    * verify they land at the ends of the scale
    """
    assert perceived_brightness(QColor("#000000")) == 0
    assert perceived_brightness(QColor("#ffffff")) == 1


def test_perceived_brightness_reads_a_saturated_blue_as_dark() -> None:
    """A saturated mid blue reads dark, which ``lightness()`` does not agree with.

    That disagreement is the whole reason for this weighting: ``#0067c0`` is the fill a checked tool
    button gets under the Windows 11 light theme, and a glyph on it has to be light.

    **Test steps:**

    * weigh the measured light-theme chrome fill
    * verify it reads as dark, below the midpoint
    """
    assert perceived_brightness(QColor(WIN11_LIGHT_CHROME)) < 0.5


def test_a_dark_backdrop_takes_highlighted_text() -> None:
    """Over a dark fill the first candidate role, ``HighlightedText``, is light enough and is used.

    **Test steps:**

    * choose a color over the measured Windows 11 light-theme chrome
    * verify it is the palette's own ``HighlightedText``
    """
    palette = palette_with("#ffffff", "#000000")

    chosen = readable_color_on(QColor(WIN11_LIGHT_CHROME), palette, QPalette.ColorGroup.Active)

    assert chosen.name() == "#ffffff"


def test_a_light_backdrop_falls_through_to_button_text() -> None:
    """Over a light fill ``HighlightedText`` is skipped and ``ButtonText`` is used instead.

    `Fusion` fills a checked button with a neutral ``#dcdcdc`` and draws its text in ``ButtonText``;
    forcing ``HighlightedText`` there is white on near-white.

    **Test steps:**

    * choose a color over the measured `Fusion` light chrome
    * verify it is the palette's own ``ButtonText``
    """
    palette = palette_with("#ffffff", "#000000")

    chosen = readable_color_on(QColor(FUSION_LIGHT_CHROME), palette, QPalette.ColorGroup.Active)

    assert chosen.name() == "#000000"


def test_a_light_backdrop_with_no_dark_role_falls_back_to_black() -> None:
    """With every candidate role light, a light fill still gets a dark glyph.

    Not a corner case: this is the Windows 11 **dark** palette exactly. It fills a checked tool button
    with ``#4cc2ff`` while holding *both* ``HighlightedText`` and ``ButtonText`` at ``#ffffff``, and
    Qt's own style draws that button's text black. Taking ``HighlightedText`` on faith here is half of
    what #304 was.

    **Test steps:**

    * choose a color over the measured Windows 11 dark chrome, with both roles white
    * verify it falls back to black rather than returning white
    """
    palette = palette_with("#ffffff", "#ffffff")

    chosen = readable_color_on(QColor(WIN11_DARK_CHROME), palette, QPalette.ColorGroup.Active)

    assert chosen.name() == "#000000"


def test_a_dark_backdrop_with_no_light_role_falls_back_to_white() -> None:
    """The mirror image: with every candidate role dark, a dark fill gets a white glyph.

    **Test steps:**

    * choose a color over the measured `Fusion` dark chrome, with both roles black
    * verify it falls back to white
    """
    palette = palette_with("#000000", "#000000")

    chosen = readable_color_on(QColor(FUSION_DARK_CHROME), palette, QPalette.ColorGroup.Active)

    assert chosen.name() == "#ffffff"


def test_the_requested_color_group_is_the_one_read() -> None:
    """Candidate roles are read from the group asked for, not the active one.

    A disabled control's glyph has to come from the ``Disabled`` group, which is a different color in
    every real palette.

    **Test steps:**

    * build a palette whose ``Disabled`` ``ButtonText`` differs from its active one
    * choose a color over a light fill, in the ``Disabled`` group
    * verify the disabled color was used
    """
    palette = palette_with("#ffffff", "#000000")
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#333333"))

    chosen = readable_color_on(QColor(FUSION_LIGHT_CHROME), palette, QPalette.ColorGroup.Disabled)

    assert chosen.name() == "#333333"
