"""A maximized screenshot or video as the session remembers it ([[plugins#session-restore]], #576)."""

from dataclasses import dataclass
from typing import Any, Final

LIGHTBOX_KIND: Final = "lightbox"
"""A maximized screenshot: an image lightbox."""

PLAYER_KIND: Final = "player"
"""A maximized video: the player's stage and bar over a surface."""

CURATED_SET: Final = "curated"
FOLDER_SET: Final = "folder"
CONTENT_SET: Final = "content"
CURATING_SET: Final = "curating"
"""The four sets a lightbox opens against: the strip's curated screenshots, a folder's images from the Files sub-dock, a
pack's content images, and every row of the screenshots editor."""

LIGHTBOX_SETS: Final = (CURATED_SET, FOLDER_SET, CONTENT_SET, CURATING_SET)


@dataclass(frozen=True, slots=True)
class MaximizedView:
    """One document's maximized view, enough to open it again once the document has loaded.

    :param kind: :data:`LIGHTBOX_KIND` or :data:`PLAYER_KIND`.
    :param key: the image's key as its source names it -- a path relative to the record's folder, or an archive member's
        key -- or the video's content key.
    :param mode: the surface, an ``OverlayMode`` value.
    :param source: for a lightbox, the set it navigated (:data:`LIGHTBOX_SETS`); empty for a player.
    :param info: for a lightbox, whether its info overlay was shown; ``None`` for the setting's.
    :param strip: for a lightbox, whether its thumbnail row was shown; ``None`` for the setting's.
    """

    kind: str
    key: str
    mode: str
    source: str = ""
    info: bool | None = None
    strip: bool | None = None

    def to_json(self) -> dict[str, Any]:
        """This view as the session file stores it.

        :returns: a JSON object, readable by :meth:`from_json`.
        """
        return {
            "kind": self.kind,
            "key": self.key,
            "mode": self.mode,
            "source": self.source,
            "info": self.info,
            "strip": self.strip,
        }

    @classmethod
    def from_json(cls, entry: object) -> MaximizedView | None:
        """Read a view back, leniently: a field of the wrong type costs the view, never the session.

        :param entry: what the session file holds.
        :returns: the view, or ``None`` if ``entry`` is not one.
        """
        if not isinstance(entry, dict):
            return None
        kind, key, mode = entry.get("kind"), entry.get("key"), entry.get("mode")
        if kind not in (LIGHTBOX_KIND, PLAYER_KIND) or not isinstance(key, str) or not key:
            return None
        if not isinstance(mode, str):
            return None
        source = entry.get("source", "")
        if not isinstance(source, str):
            return None
        if kind == LIGHTBOX_KIND and source not in LIGHTBOX_SETS:
            return None
        info, strip = entry.get("info"), entry.get("strip")
        return cls(
            kind,
            key,
            mode,
            source,
            info if isinstance(info, bool) else None,
            strip if isinstance(strip, bool) else None,
        )
