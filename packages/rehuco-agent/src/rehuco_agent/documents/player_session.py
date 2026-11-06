"""Whether the player holds a video's file, and why ([[plugins#in-app-player]])."""

from enum import Enum, auto


class Session(Enum):
    """Whether the player holds a video's file, and why."""

    NONE = auto()
    """No source is open: the file is not held, and the OS may rename its folder."""

    GRAB = auto()
    """The file is open, paused, only to take a frame of it and learn its length -- a moment, then it is let go."""

    PLAY = auto()
    """The video is playing, and the file is held for as long as it does."""

    HELD = auto()
    """The video is paused in the player with its file held, so it resumes on the very frame it stopped on -- the
    libvlc engine's pause (#319), where reopening and seeking landed a few frames off. A rename of this resource
    lets the file go first (`PlayerView`)."""

    SCRUB = auto()
    """The seek bar's handle is being dragged: the file is open, paused and silent, to show the frames the handle passes
    (#613). What the player reports meanwhile is nobody's progress."""
