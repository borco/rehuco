"""Every icon-font glyph used across the app -- each its own codepoint/font-family pair -- kept in one
place so the in-use codepoint/weight set can be audited without grepping every field/widget module
(#37). Currently all Phosphor, but nothing here assumes a single icon-font family.
"""

from typing import Final

from borco_pyside.theming import Glyph

CLEAR_ACTION_GLYPH: Final = Glyph("\ue0ae", "Phosphor-Bold")
"""`QLineEdit` clear action's icon ([[plugins#field-toolkit]], ``app.py``)."""

CALENDAR_ACTION_GLYPH: Final = Glyph("\ue108", "Phosphor-Bold")
"""`DateField`'s popup-calendar trailing action icon."""

POSITIVE_RATING_GLYPH: Final = Glyph("\ue46a", "Phosphor-Fill")
"""Positive-rating stars -- see :data:`NEGATIVE_RATING_GLYPH`."""

NEGATIVE_RATING_GLYPH: Final = Glyph("\ue46a", "Phosphor-Bold")
"""Negative-rating stars -- see :data:`POSITIVE_RATING_GLYPH`."""

TAB_CLOSE_GLYPH: Final = Glyph("\ue4f6", "Phosphor-Bold")
"""Close button on each document/surface tab (a `QtAdsFocusTracker`'s ``close_glyph``); overrides its
plain-Unicode default with the Phosphor ``x`` to match the app's icon set."""
