"""Shared color tokens for the field toolkit ([[plugins#field-toolkit]])."""

from typing import Final

WARNING_COLOR: Final = "#F4511E"
"""Coral, the brand accent ([[architecture-design]] palette): reads on both light and dark themes.
Shared by any field that needs to draw attention to a value (e.g. ``BooleanField``'s ``complete``
warning, ``RatingField``'s negative stars)."""
