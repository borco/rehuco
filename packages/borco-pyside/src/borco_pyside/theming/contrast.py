"""Pick a foreground color that stays legible against whatever a style actually painted behind it."""

from PySide6.QtGui import QColor, QPalette

READABLE_CANDIDATE_ROLES: tuple[QPalette.ColorRole, ...] = (
    QPalette.ColorRole.HighlightedText,
    QPalette.ColorRole.ButtonText,
)
"""The palette's own answers to "text on a filled control", in the order they are preferred.

``HighlightedText`` first because a style that fills with its accent means it; ``ButtonText`` second
for the styles that fill a checked button with a plain shade of ``Button`` instead (`Fusion` does).
"""


def perceived_brightness(color: QColor) -> float:
    """How bright ``color`` looks, on a ``0..1`` scale.

    Perceived brightness, not ``lightness()``: a saturated mid blue reads far darker than its max/min
    average suggests, and it is legibility against such a fill being decided here. The same weights
    this codebase already uses to choose a menu row's text role.

    :param color: the color to weigh.
    :returns: the weighted brightness, ``0`` for black and ``1`` for white.
    """
    return (0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()) / 255


def readable_color_on(backdrop: QColor, palette: QPalette, group: QPalette.ColorGroup) -> QColor:
    """Choose a color from ``palette`` that contrasts with ``backdrop``.

    Takes the first of :data:`READABLE_CANDIDATE_ROLES` whose own brightness falls on the opposite
    side of the midpoint from ``backdrop``'s, so the glyph and the fill can never both be light or
    both be dark. Falls back to plain black or white when neither role does -- which is not a corner
    case: the Windows 11 dark palette fills a checked tool button with ``#4cc2ff`` and has *both*
    roles at ``#ffffff``, and Qt's own style draws that button's text black.

    :param backdrop: the color actually painted behind the glyph, measured rather than assumed.
    :param palette: the palette to take candidate colors from.
    :param group: the palette color group to read, e.g. ``Disabled`` for a disabled control.
    :returns: the color to draw the glyph in.
    """
    wants_dark = perceived_brightness(backdrop) > 0.5
    for role in READABLE_CANDIDATE_ROLES:
        candidate = palette.color(group, role)
        if (perceived_brightness(candidate) <= 0.5) == wants_dark:
            return candidate
    return QColor(0, 0, 0) if wants_dark else QColor(255, 255, 255)
