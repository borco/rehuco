"""Shared color tokens -- originally the field toolkit's ([[plugins#field-toolkit]]), now also the
inline notice banner's (#94) severity colors, kept in the one place so a value drawing attention
reads consistently everywhere it appears, not just within one field or widget.
"""

from typing import Final

WARNING_COLOR: Final = "#F4511E"
"""Coral, the brand accent ([[architecture-design]] palette): reads on both light and dark themes.
Shared by any field that needs to draw attention to a value (e.g. ``BooleanField``'s ``complete``
warning, ``RatingField``'s negative stars) and by the inline notice banner's ``warning`` severity."""

INFO_COLOR: Final = "#64B5F6"
"""Material Blue 300 -- the same Material palette family as :data:`WARNING_COLOR` (Deep Orange 600)
and :data:`ERROR_COLOR` (Red 800), but a lighter, more pastel step of it: nothing here is wrong or
blocking, so the color reads calmer than the other two rather than matching their full intensity.
The inline notice banner's ``info`` severity."""

ERROR_COLOR: Final = "#C62828"
"""A deeper red than :data:`WARNING_COLOR`'s orange-leaning coral, so the two read as distinct
severities at a glance rather than the same color with a different icon. The inline notice banner's
``error`` severity."""
