"""What a tutorial's duration scan is run with ([[field-schema#duration-size]], #225).

`rehuco_core.rehu_content_duration.content_duration` takes both the probe that reads a container and the
extensions it recognizes as parameters rather than reading a setting, so this is where the two come from.
The counterpart of `ReferenceImagesSettings`, which supplies the other plugin's scan the same way.

An ``engine`` key names a registry member; one naming a backend this build does not have -- an ``.ini``
written by a newer version -- selects the default rather than raising, the way `ImageViewerSettings` already
treats an unrecognized ``mode``. Where the external backend's FFmpeg lives is not kept here: it is the Tools
page's ([[packaging-deployment#external-tools]], #521), read through `ToolsSettings`.

A plain ``@dataclass``, like `ReferenceImagesSettings` and `ExcludedFilesSettings`: both values are read
only when a scan runs, so nothing on screen changes when they do and there is nothing to watch them
change.
"""

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Final, cast

from PySide6.QtCore import QSettings
from rehuco_core import (
    DEFAULT_DURATION_PROBE,
    DURATION_PROBES,
    EXTERNAL_TOOLS,
    FFMPEG_LIBRARIES_TOOL,
    FFMPEG_TOOL,
    VIDEO_EXTENSIONS,
    VLC_TOOL,
    DurationProbe,
    FfprobeDurationProbe,
    WatchRules,
)

from .extension_lists import normalize_extensions as normalize_extension_list
from .persistent_settings import persistent_settings, read_stored_strings
from .tools_settings import shared_tools_settings

GROUP: Final = "videos"
ENGINE_KEY: Final = "engine"
EXTENSIONS_KEY: Final = "extensions"
PLAYER_KEY: Final = "player"
MARK_FILE_VIEWED_KEY: Final = "mark_file_viewed_at_end"
MARK_TUTORIAL_VIEWED_KEY: Final = "mark_tutorial_viewed_on_last_file"
MATCH_RENAMED_BY_SIZE_KEY: Final = "match_renamed_by_size"
ADD_NOTE_EDITS_KEY: Final = "add_note_edits"

IN_APP_PLAYER: Final = "in_app"
"""The player dock a document hosts ([[plugins#in-app-player]])."""

VLC_PLAYER: Final = VLC_TOOL.ID
"""The in-app player decoding with the user's own VLC, its libvlc loaded into the player dock (#319) -- named after the
tool that supplies it. Read as a video is selected, so it applies to the next video played, in every open
document."""

FFMPEG_LIBRARIES_PLAYER: Final = FFMPEG_LIBRARIES_TOOL.ID
"""The in-app player decoding with an external FFmpeg's libraries (#580); applied at the next start, so a double-click
opens it in the same player as :data:`IN_APP_PLAYER`."""

PLAYERS: Final = (
    IN_APP_PLAYER,
    *((FFMPEG_LIBRARIES_PLAYER,) if FFMPEG_LIBRARIES_PLAYER in EXTERNAL_TOOLS else ()),
    VLC_PLAYER,
)
"""Where a double-clicked video can open and what decodes it (#318, #580): the names ``player`` may hold. The libraries
are Windows-only, as their tool is."""

DEFAULT_PLAYER: Final = IN_APP_PLAYER


def normalize_extensions(values: object) -> tuple[str, ...]:
    """Normalize a video-extension list into the form the duration scan matches against.

    The shared extension-list rule (:func:`~rehuco_agent.settings.extension_lists.normalize_extensions`)
    under this section's own fallback: a list holding no usable entry at all resolves to
    :data:`~rehuco_core.VIDEO_EXTENSIONS`, since a list left empty must not silently measure every
    tutorial as zero.

    :param values: the entries as edited or as stored.
    :returns: the recognized extensions, lower-cased and dot-prefixed, in the order first seen, or the
        shipped set when ``values`` names none.
    """
    return normalize_extension_list(values, VIDEO_EXTENSIONS)


def read_extensions(value: object) -> tuple[str, ...]:
    """Coerce the stored value into the entry list it was saved as.

    Reading the stored shape at all -- including the ini backend's habit of handing a single-element
    list back as a bare string -- is
    :func:`~rehuco_agent.settings.persistent_settings.read_stored_strings`'s job; all this adds is
    dropping a blank entry, which is a row the editor would show as nothing.

    :param value: the raw stored value.
    :returns: the entries, otherwise as typed.
    """
    return tuple(entry for entry in read_stored_strings(value) if entry)


def read_engine(value: object) -> str:
    """Resolve a stored ``engine`` value to a probe this build actually ships.

    An unrecognized name is the ordinary consequence of an ``.ini`` written by a newer version, or of a
    backend dropped from a build; it selects :data:`~rehuco_core.DEFAULT_DURATION_PROBE` rather than
    raising, so a downgrade still measures durations instead of failing to open the page.

    :param value: the raw stored value.
    :returns: the name of a probe in :data:`~rehuco_core.DURATION_PROBES`.
    """
    return value if isinstance(value, str) and value in DURATION_PROBES else DEFAULT_DURATION_PROBE


def read_player(value: object) -> str:
    """Resolve a stored ``player`` value to a player this build knows.

    An unrecognized name -- an ``.ini`` written by a newer version -- selects :data:`DEFAULT_PLAYER` rather than
    raising, the way :func:`read_engine` treats ``engine``.

    :param value: the raw stored value.
    :returns: a member of :data:`PLAYERS`.
    """
    return value if isinstance(value, str) and value in PLAYERS else DEFAULT_PLAYER


@dataclass
class VideosSettings:
    """How a tutorial's videos are measured -- which backend reads a duration, and over which files -- and how
    watching them is tracked ([[field-schema#watch-progress]], #316).

    :attr:`engine` and :attr:`extensions` are stored as the page left them; what a scan consumes is
    :meth:`create_probe` and :attr:`video_extensions`, the values they resolve to.

    :attr:`player` is read where a video is double-clicked, so a change applies to documents already open.
    """

    engine: str = DEFAULT_DURATION_PROBE
    """Which probe reads a video's duration -- a key of :data:`~rehuco_core.DURATION_PROBES`."""

    extensions: tuple[str, ...] = field(default_factory=tuple)
    """The recognized video extensions as stored -- empty on a fresh install, where the effective set is
    the shipped one rather than nothing."""

    player: str = DEFAULT_PLAYER
    """Where a double-clicked video opens and what decodes it -- a member of :data:`PLAYERS`. The tools' own paths are
    the Tools page's."""

    mark_file_viewed_at_end: bool = True
    """Reaching the end of a video marks it viewed ([[field-schema#watch-progress]])."""

    mark_tutorial_viewed_on_last_file: bool = True
    """A video becoming viewed marks the tutorial viewed when every video now is."""

    match_renamed_by_size: bool = True
    """A renamed video takes its progress by size alone when no checksum is recorded for it."""

    add_note_edits: bool = True
    """Adding a note from the player (#573) pauses the video and opens the notes for editing; off, it only adds the line
    and leaves playback and the notes dock as they are."""

    @property
    def video_extensions(self) -> tuple[str, ...]:
        """The effective extension set the duration scan is handed ([[field-schema#duration-size]]):
        :attr:`extensions` normalized, falling back to :data:`~rehuco_core.VIDEO_EXTENSIONS` when it
        names nothing usable (:func:`normalize_extensions`)."""
        return normalize_extensions(self.extensions)

    @property
    def watch_rules(self) -> WatchRules:
        """The two auto-viewed rules core's watch-progress write takes as parameters
        ([[field-schema#watch-progress]], #316)."""
        return WatchRules(self.mark_file_viewed_at_end, self.mark_tutorial_viewed_on_last_file)

    def create_probe(self) -> DurationProbe:
        """Build the selected backend, with its own settings.

        :data:`~rehuco_core.DURATION_PROBES` holds classes rather than instances precisely so this can
        happen: ffprobe is constructed with the FFmpeg path the Tools page keeps, and every other backend
        takes none. A fresh instance per scan, since a probe holds no state worth sharing and the
        settings behind it may have changed since the last one.

        :returns: the probe named by :attr:`engine`, or the default one when it names none this build
            has.
        """
        probe_class = DURATION_PROBES[read_engine(self.engine)]
        if issubclass(probe_class, FfprobeDurationProbe):
            tools = shared_tools_settings()
            return probe_class(tools.path(FFMPEG_TOOL.ID), tools.detection(FFMPEG_TOOL.ID).installs)
        return probe_class()

    def load(self, settings: QSettings) -> None:
        """Replace the current values with what's in persistent storage.

        A never-saved, empty or unreadable extension value comes back as no entries, which resolves to
        the shipped set rather than to no recognized formats at all (:func:`read_extensions`); an
        unrecognized ``engine`` comes back as the default backend (:func:`read_engine`), and an unrecognized
        ``player`` as the default player (:func:`read_player`).

        :param settings: the ``QSettings`` to read from.
        """
        settings.beginGroup(GROUP)
        self.engine = read_engine(settings.value(ENGINE_KEY))
        self.extensions = read_extensions(settings.value(EXTENSIONS_KEY))
        self.player = read_player(settings.value(PLAYER_KEY))
        self.mark_file_viewed_at_end = cast(bool, settings.value(MARK_FILE_VIEWED_KEY, True, type=bool))
        self.mark_tutorial_viewed_on_last_file = cast(bool, settings.value(MARK_TUTORIAL_VIEWED_KEY, True, type=bool))
        self.match_renamed_by_size = cast(bool, settings.value(MATCH_RENAMED_BY_SIZE_KEY, True, type=bool))
        self.add_note_edits = cast(bool, settings.value(ADD_NOTE_EDITS_KEY, True, type=bool))
        settings.endGroup()

    def save(self, settings: QSettings) -> None:
        """Save the current values to persistent storage, the list as one the ini backend round-trips.

        :param settings: the ``QSettings`` to write to.
        """
        settings.beginGroup(GROUP)
        settings.setValue(ENGINE_KEY, self.engine)
        settings.setValue(EXTENSIONS_KEY, list(self.extensions))
        settings.setValue(PLAYER_KEY, self.player)
        settings.setValue(MARK_FILE_VIEWED_KEY, self.mark_file_viewed_at_end)
        settings.setValue(MARK_TUTORIAL_VIEWED_KEY, self.mark_tutorial_viewed_on_last_file)
        settings.setValue(MATCH_RENAMED_BY_SIZE_KEY, self.match_renamed_by_size)
        settings.setValue(ADD_NOTE_EDITS_KEY, self.add_note_edits)
        settings.endGroup()


@lru_cache(maxsize=1)
def shared_videos_settings() -> VideosSettings:
    """The single, process-wide `VideosSettings` instance, loaded from persistent storage on first
    call -- the same shape, and for the same reason, as
    :func:`~rehuco_agent.settings.reference_images_settings.shared_reference_images_settings`: the
    settings page's Save must be what the next duration scan reads, not a disconnected per-reader copy.

    :returns: the shared instance.
    """
    settings = VideosSettings()
    settings.load(persistent_settings())
    return settings
