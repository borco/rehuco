"""Every icon-font glyph used across the app -- each its own codepoint/font-family pair -- kept in one
place so the in-use codepoint/weight set can be audited without grepping every field/widget module
(#37). Currently all Phosphor, but nothing here assumes a single icon-font family.
"""

from typing import Final, NamedTuple


class Glyph(NamedTuple):
    """A single glyph codepoint paired with the font family/weight it resolves in -- distinct glyphs
    can come from distinct Phosphor weights, so the family is never assumed shared across a module.

    :param codepoint: the glyph character.
    :param family: the font family ``codepoint`` resolves in; must already be loaded application-wide
        (``app.py``).
    """

    codepoint: str
    family: str


CLEAR_ACTION_GLYPH: Final = Glyph("\ue0ae", "Phosphor-Bold")
"""Phosphor's "backspace" glyph, the app-wide `QLineEdit` clear action's icon
([[plugins#field-toolkit]], ``app.py``)."""

CALENDAR_ACTION_GLYPH: Final = Glyph("\ue108", "Phosphor-Bold")
"""Phosphor's "calendar" glyph, `DateField`'s popup-calendar trailing action icon."""

EXPAND_ACTION_GLYPH: Final = Glyph("\ue3d4", "Phosphor-Bold")
"""Phosphor's "plus" glyph, `PathField`'s suggestions-panel expand toggle (collapsed state)."""

COLLAPSE_ACTION_GLYPH: Final = Glyph("\ue32a", "Phosphor-Bold")
"""Phosphor's "minus" glyph, `PathField`'s suggestions-panel collapse toggle (expanded state); shares
:data:`EXPAND_ACTION_GLYPH`'s font family, so the toggle button sets its font once and only swaps text."""

POSITIVE_RATING_GLYPH: Final = Glyph("\ue46a", "Phosphor-Fill")
"""Phosphor's "star" glyph, filled, for `RatingField`'s positive-rating stars; shares
:data:`NEGATIVE_RATING_GLYPH`'s codepoint, so only the font-family swap (fill vs. outline) tells the
two apart."""

NEGATIVE_RATING_GLYPH: Final = Glyph("\ue46a", "Phosphor")
"""Phosphor's "star" glyph, outline, for `RatingField`'s negative-rating stars -- see
:data:`POSITIVE_RATING_GLYPH`."""
