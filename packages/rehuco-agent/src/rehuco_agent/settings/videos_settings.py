"""What a tutorial's duration scan is run with ([[field-schema#duration-size]], #225).

`rehuco_core.rehu_content_duration.content_duration` takes both the probe that reads a container and the
extensions it recognizes as parameters rather than reading a setting, so this is where the two come from.
The counterpart of `ReferenceImagesSettings`, which supplies the other plugin's scan the same way.

**Each backend's settings are stored side by side**, the shape `MarkdownRenderingSettings` already uses:
an ``engine`` key naming a registry member, and ``ffprobe_executable`` kept whether or not ffprobe is the
selected one, so switching backends and back loses neither. An ``engine`` naming a backend this build
does not have -- an ``.ini`` written by a newer version -- selects the default rather than raising, the
way `ImageViewerSettings` already treats an unrecognized ``mode``.

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
    VIDEO_EXTENSIONS,
    DurationProbe,
    FfprobeDurationProbe,
)

from .extension_lists import normalize_extensions as normalize_extension_list
from .persistent_settings import persistent_settings, read_stored_strings

GROUP: Final = "videos"
ENGINE_KEY: Final = "engine"
FFPROBE_EXECUTABLE_KEY: Final = "ffprobe_executable"
EXTENSIONS_KEY: Final = "extensions"


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


@dataclass
class VideosSettings:
    """How a tutorial's videos are measured: which backend reads a duration, and over which files.

    :attr:`engine` and :attr:`extensions` are stored as the page left them; what a scan consumes is
    :meth:`create_probe` and :attr:`video_extensions`, the values they resolve to.
    """

    engine: str = DEFAULT_DURATION_PROBE
    """Which probe reads a video's duration -- a key of :data:`~rehuco_core.DURATION_PROBES`."""

    ffprobe_executable: str = ""
    """Where the ``ffprobe`` executable lives, or empty to look it up on ``PATH``. Kept whether or not
    ffprobe is the selected backend, so switching to the other and back does not lose it."""

    extensions: tuple[str, ...] = field(default_factory=tuple)
    """The recognized video extensions as stored -- empty on a fresh install, where the effective set is
    the shipped one rather than nothing."""

    @property
    def video_extensions(self) -> tuple[str, ...]:
        """The effective extension set the duration scan is handed ([[field-schema#duration-size]]):
        :attr:`extensions` normalized, falling back to :data:`~rehuco_core.VIDEO_EXTENSIONS` when it
        names nothing usable (:func:`normalize_extensions`)."""
        return normalize_extensions(self.extensions)

    def create_probe(self) -> DurationProbe:
        """Build the selected backend, with its own settings.

        :data:`~rehuco_core.DURATION_PROBES` holds classes rather than instances precisely so this can
        happen: ffprobe is constructed with the path this section keeps for it, and every other backend
        takes none. A fresh instance per scan, since a probe holds no state worth sharing and the
        settings behind it may have changed since the last one.

        :returns: the probe named by :attr:`engine`, or the default one when it names none this build
            has.
        """
        probe_class = DURATION_PROBES[read_engine(self.engine)]
        if issubclass(probe_class, FfprobeDurationProbe):
            return probe_class(self.ffprobe_executable)
        return probe_class()

    def load(self, settings: QSettings) -> None:
        """Replace the current values with what's in persistent storage.

        A never-saved, empty or unreadable extension value comes back as no entries, which resolves to
        the shipped set rather than to no recognized formats at all (:func:`read_extensions`); an
        unrecognized ``engine`` comes back as the default backend (:func:`read_engine`).

        :param settings: the ``QSettings`` to read from.
        """
        settings.beginGroup(GROUP)
        self.engine = read_engine(settings.value(ENGINE_KEY))
        self.ffprobe_executable = cast(str, settings.value(FFPROBE_EXECUTABLE_KEY, "", type=str))
        self.extensions = read_extensions(settings.value(EXTENSIONS_KEY))
        settings.endGroup()

    def save(self, settings: QSettings) -> None:
        """Save the current values to persistent storage, the list as one the ini backend round-trips.

        :param settings: the ``QSettings`` to write to.
        """
        settings.beginGroup(GROUP)
        settings.setValue(ENGINE_KEY, self.engine)
        settings.setValue(FFPROBE_EXECUTABLE_KEY, self.ffprobe_executable)
        settings.setValue(EXTENSIONS_KEY, list(self.extensions))
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
