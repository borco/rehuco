"""The videos a player steps through, and where each one starts ([[plugins#in-app-player]], #317)."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from rehuco_core import ProgressEntry, reached_end


@dataclass(frozen=True)
class PlaylistVideo:
    """One video of the playlist."""

    key: str
    """The video's content key, which its progress is filed under."""

    path: Path
    """Where the file is."""


class PlayerPlaylist:
    """The browsed folder's videos in the order the Files sub-dock draws them, with the one playing.

    Stepping stops at both ends rather than wrapping, as the image lightbox does: the last video of a folder is the
    end of the list, not a way back to the first.

    :param videos: each video's content key and path, in play order.
    :param current_key: the content key of the video to play first.
    :raises ValueError: ``current_key`` is not among ``videos``.
    """

    def __init__(self, videos: Sequence[tuple[str, Path]], current_key: str) -> None:
        self.__videos = tuple(PlaylistVideo(key, path) for key, path in videos)
        try:
            self.__index = next(index for index, video in enumerate(self.__videos) if video.key == current_key)
        except StopIteration:
            raise ValueError(f"Not a video of the playlist: {current_key!r}") from None

    @property
    def current(self) -> PlaylistVideo:
        """The video playing now."""
        return self.__videos[self.__index]

    @property
    def has_previous(self) -> bool:
        """Whether a video comes before the current one."""
        return self.__index > 0

    @property
    def has_next(self) -> bool:
        """Whether a video comes after the current one."""
        return self.__index < len(self.__videos) - 1

    def step(self, delta: int) -> PlaylistVideo | None:
        """Move to the video ``delta`` places away, unless that is past either end.

        :param delta: how many videos forward, or back when negative.
        :returns: the video now current, or ``None`` when the step would leave the list, which moves nothing.
        """
        target = self.__index + delta
        if delta == 0 or not 0 <= target < len(self.__videos):
            return None
        self.__index = target
        return self.__videos[target]

    @staticmethod
    def start_position(entry: ProgressEntry | None, length: float | None = None) -> float:
        """Where a video starts: where it was left, or the beginning when it was never opened or was watched to the
        end -- a viewed video, or one left within the end's tolerance of its length, is watched again from the start
        rather than resumed from its last seconds, with no slider to drag back.

        :param entry: the user's progress on the video, or ``None`` when there is none.
        :param length: the video's length when known, else the one the entry recorded.
        :returns: the position, in seconds.
        """
        if entry is None or entry.viewed:
            return 0.0
        if reached_end(entry.position, length if length is not None else entry.duration):
            return 0.0
        return entry.position
