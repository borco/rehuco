"""What the path row marks a place with (#649): one icon per fact about moving the record there."""

from enum import Flag, auto
from typing import Final


class PlaceMarker(Flag):
    """The facts the path row draws as icons after a place or a name, in the order they are drawn.

    Iterating a value yields its members in definition order, so that order is the icons'; a new marker is one more
    member and its entries in :data:`PLACE_MARKER_ICONS` and :data:`PLACE_MARKER_TOOLTIPS`.
    """

    NETWORK = auto()
    """The move goes over the network, the record's folder or the place being on a share: it is slow."""
    COPY = auto()
    """The move copies, the place being on another volume, rather than renames."""
    VERIFIED = auto()
    """The move verifies the record's checksums."""
    BLOCKED = auto()
    """Something already sits there, so it cannot be chosen."""


PLACE_MARKER_ICONS: Final[dict[PlaceMarker, str]] = {
    PlaceMarker.NETWORK: ":/icons/location_network.svg",
    PlaceMarker.COPY: ":/icons/location_copy.svg",
    PlaceMarker.VERIFIED: ":/icons/location_verified.svg",
    PlaceMarker.BLOCKED: ":/icons/location_blocked.svg",
}
"""The resource each marker is drawn from."""

PLACE_MARKER_TOOLTIPS: Final[dict[PlaceMarker, str]] = {
    PlaceMarker.NETWORK: "Goes over the network, so it is slow.",
    PlaceMarker.COPY: "Copies the record to another volume, then removes the original.",
    PlaceMarker.VERIFIED: "Verifies the record's checksums.",
    PlaceMarker.BLOCKED: "Something is already there.",
}
"""What each marker means, in a sentence, for the row's tooltip."""

NO_MARKERS: Final = PlaceMarker(0)
"""A row with nothing to say."""
