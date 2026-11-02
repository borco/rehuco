"""What the player's info panel says about the video loaded ([[plugins#player-maximized]], #574)."""

from PySide6.QtCore import QSize

from .clock_text import clock_text
from .player_playlist import PlayerPlaylist


def player_info_text(playlist: PlayerPlaylist, pixel_size: QSize | None, length_ms: int, position_ms: int) -> str:
    """The panel's lines: the video, its pixel size, its length, where it is and how far in, and where it stands in
    the playlist -- the lightbox's info box, for a video.

    :param playlist: the playlist, on the video loaded.
    :param pixel_size: the picture's size, or ``None`` when it is not known.
    :param length_ms: the video's length; ``0`` when it is not known.
    :param position_ms: where the video is.
    :returns: the text, one fact a line.
    """
    size = (
        f"{pixel_size.width()} × {pixel_size.height()} px"
        if pixel_size is not None and not pixel_size.isEmpty()
        else "size unknown"
    )
    length = clock_text(length_ms) if length_ms > 0 else "length unknown"
    position = clock_text(position_ms)
    if length_ms > 0:
        position = f"{position} ({min(position_ms, length_ms) * 100 // length_ms} %)"
    return "\n".join((playlist.current.key, size, length, position, f"[{playlist.position}/{playlist.count}]"))
