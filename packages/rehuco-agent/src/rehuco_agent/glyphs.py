"""Every icon-font glyph used across the app -- each its own codepoint/font-family pair -- kept in one
place so the in-use codepoint/weight set can be audited without grepping every field/widget module
(#37). Currently all Phosphor, but nothing here assumes a single icon-font family.
"""

from typing import Final

from borco_pyside.theming import Glyph

CALENDAR_ACTION_GLYPH: Final = Glyph("\ue108", "Phosphor-Bold")
"""`DateField`'s popup-calendar trailing action icon."""

COPY_ACTION_GLYPH: Final = Glyph("", "Phosphor-Bold")
"""Copy an image out of the app, on the Content Images toolbar (#395): Phosphor's ``copy``."""

FIND_HOLDERS_GLYPH: Final = Glyph("\ue30c", "Phosphor-Bold")
"""Find what holds a refused rename's files, on its banner row (`RenameHoldersDialog`, #505): Phosphor's
``magnifying-glass``."""

FILTER_PROBLEM_GLYPH: Final = Glyph("\ue4e0", "Phosphor-Bold")
"""A table browser's filter line, while part of it could not be applied (`TableBrowser`, #398): Phosphor's
``warning``, its tooltip saying what."""

POSITIVE_RATING_GLYPH: Final = Glyph("\ue46a", "Phosphor-Fill")
"""Positive-rating stars -- see :data:`NEGATIVE_RATING_GLYPH`."""

NEGATIVE_RATING_GLYPH: Final = Glyph("\ue46a", "Phosphor-Bold")
"""Negative-rating stars -- see :data:`POSITIVE_RATING_GLYPH`."""

FAVORITE_GLYPH: Final = Glyph("\ue46a", "Phosphor-Fill")
"""The star on a video the user starred, in the video tree (#572)."""

LIGHTBOX_CLOSE_GLYPH: Final = Glyph("\ue4f6", "Phosphor-Bold")
"""Close affordance in the maximized image viewer (`ImageLightbox`, #160). The same codepoint as
:data:`TAB_CLOSE_GLYPH`, kept as its own name because it is drawn a fixed white on the viewer's dark
backdrop rather than palette-themed like the tab's -- two uses that can drift apart."""

TAB_CLOSE_GLYPH: Final = Glyph("\ue4f6", "Phosphor-Bold")
"""Close button on each document/surface tab (a `QtAdsFocusTracker`'s ``close_glyph``); overrides its
plain-Unicode default with the Phosphor ``x`` to match the app's icon set."""

TAB_MAXIMIZE_GLYPH: Final = Glyph("\ue0a2", "Phosphor-Bold")
"""Maximize toggle on each document/surface tab, beside :data:`TAB_CLOSE_GLYPH` (a
`QtAdsMaximizeHandler`'s glyph, #341): Phosphor's ``arrows-out``, drawn as text the same way, so the
tracker's stylesheet recolours both on the current tab. Swapped for :data:`TAB_RESTORE_GLYPH` while the
tab is maximized."""

TAB_RESTORE_GLYPH: Final = Glyph("\ue09a", "Phosphor-Bold")
"""The same toggle while its tab is maximized: Phosphor's ``arrows-in``, the way back."""

PLAYER_PLAY_GLYPH: Final = Glyph("\ue3d0", "Phosphor-Bold")
"""Play, on the in-app player's transport bar (`PlayerView`, #317): Phosphor's ``play``."""

PLAYER_PAUSE_GLYPH: Final = Glyph("\ue39e", "Phosphor-Bold")
"""Pause, in the same place as :data:`PLAYER_PLAY_GLYPH`: Phosphor's ``pause``."""

PLAYER_PREVIOUS_GLYPH: Final = Glyph("\ue5a4", "Phosphor-Bold")
"""The previous video of the player's playlist: Phosphor's ``skip-back``."""

PLAYER_NEXT_GLYPH: Final = Glyph("\ue5a6", "Phosphor-Bold")
"""The next video of the player's playlist: Phosphor's ``skip-forward``."""

PLAYER_BACK_GLYPH: Final = Glyph("\ue6a8", "Phosphor-Bold")
"""Five seconds back in the playing video: Phosphor's ``rewind``."""

PLAYER_FORWARD_GLYPH: Final = Glyph("\ue6a6", "Phosphor-Bold")
"""Five seconds forward in the playing video: Phosphor's ``fast-forward``."""
