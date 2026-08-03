"""The padding a log row is drawn with, shared by the two delegates that draw its halves."""

from typing import Final

TEXT_HPADDING: Final = 9
"""Horizontal inset of a cell's text from its rect, in pixels.

Held here rather than in either delegate because both draw text into the same row and must inset it
identically -- the level and the message would otherwise sit on different baselines' worth of margin
and read as two tables side by side."""

TEXT_VPADDING: Final = 4
"""Vertical inset of a cell's text from its rect, in pixels; see :data:`TEXT_HPADDING`."""

SERIAL_HPADDING: Final = 3
"""Horizontal inset of the serial number drawn in the level cell's top-right corner.

Tighter than :data:`TEXT_HPADDING`: the serial is a marginal annotation rather than a column of its
own, so it sits nearer the edge than the text it annotates."""

SERIAL_VPADDING: Final = 3
"""Vertical inset of the serial number; see :data:`SERIAL_HPADDING`."""

SERIAL_POINT_SIZE_REDUCTION: Final = 2
"""How many points smaller than the view's font the serial is drawn at.

A reduction rather than a fixed size, so the annotation follows the application font instead of
becoming unreadably small (or overwhelming the level name) whenever that font is not the one this
was measured against."""
