"""Which patterns a legacy `.tc`'s screenshots are recognized by
([[acquisition-tooling#screenshot-schemes]], #53, #287).

`rehuco_core.tc_screenshots.scan_tc_screenshots` takes the patterns as a parameter rather than reading a
constant, so this is where that set comes from -- and the conversion, the wizard's dry run and the
content walk all take it from here, because a file the conversion renames aside but the walk counts as
content is the bug the single set exists to prevent: `current_size` would move purely because a
resource was converted.

**A pattern is an ordinary regular expression** with a slot convention (`rehuco_core.ScreenshotNamePattern`):
one capture group names the slot the match belongs to, read as an integer; no capture group means slot
``0``. Patterns are an ordered list -- first match wins -- so reordering the list is a real edit rather
than a cosmetic one.

The **tie-break** between files landing on one slot (largest pixel area, then ``.jpg``/``.jpeg``, then
the alphabetically first name) is not stored here and is not the user's, for the reason
`ExcludedFilesSettings` gives about its own structural tier: it applies whatever this list says.

A plain ``@dataclass``, like `ExcludedFilesSettings` and for the same reason: the patterns are read only
when a scan runs, so nothing on screen changes when they do and there is nothing to watch them change.
"""

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Final

from PySide6.QtCore import QSettings
from rehuco_core import SCREENSHOT_NAME_PATTERNS, ScreenshotNamePattern, ScreenshotNamePatterns

from .persistent_settings import persistent_settings, read_stored_strings

GROUP: Final = "screenshot_patterns"
PATTERNS_KEY: Final = "patterns"
SAMPLES_KEY: Final = "samples"

DEFAULT_SAMPLES: Final = ("cover.jpg", "sample-03.jpg", "image-07.jpg")
"""The try-it table's seeded sample filenames -- real matches of the shipped patterns, so a fresh page
shows the convention working rather than an empty table."""


def pattern_is_valid(pattern: str) -> bool:
    """Whether ``pattern`` would compile as a usable screenshot name pattern.

    The same check :class:`~rehuco_core.ScreenshotNamePatterns` applies internally -- a blank pattern,
    one that fails to compile, or one carrying more than one capture group is not usable -- exposed here
    so :func:`normalize_screenshot_name_patterns` and the settings page's per-row validity flag (#287)
    share one spelling of it rather than two.

    :param pattern: the raw pattern string, trimmed or not.
    :returns: whether it is blank, or would be dropped by :class:`~rehuco_core.ScreenshotNamePatterns`.
    """
    if not pattern.strip():
        return False
    return not ScreenshotNamePatterns((ScreenshotNamePattern(pattern),)).invalid


def normalize_screenshot_name_patterns(patterns: object) -> tuple[str, ...]:
    """Coerce a stored or edited pattern list into the form a scan is handed.

    Each entry is trimmed; one that does not compile as a valid single-or-no-group regex is dropped, the
    same check `rehuco_core.ScreenshotNamePatterns` itself applies rather than a second spelling of it
    here. Duplicates are dropped by exact string match after trimming -- not case-insensitively, since
    regex casing matters syntactically -- and the order the patterns were given in is kept, since it
    decides which pattern matches first.

    A value naming no usable pattern at all falls back to
    :data:`~rehuco_core.SCREENSHOT_NAME_PATTERNS` rather than to *recognize nothing*: an empty set would
    silently convert every legacy resource without carrying a single screenshot across.

    Reading the stored shape at all -- including the ini backend's habit of handing a single-element
    list back as a bare string -- is
    :func:`~rehuco_agent.settings.persistent_settings.read_stored_strings`'s job; what is left here is
    the policy this list applies on top of it.

    :param patterns: the stored patterns, or the patterns as edited.
    :returns: the usable patterns in the order first seen, or the shipped defaults when there are none.
    """
    normalized: list[str] = []
    for entry in read_stored_strings(patterns):
        pattern = entry.strip()
        if not pattern or pattern in normalized or not pattern_is_valid(pattern):
            continue
        normalized.append(pattern)
    return tuple(normalized) or tuple(pattern.pattern for pattern in SCREENSHOT_NAME_PATTERNS)


def normalize_screenshot_samples(samples: object) -> tuple[str, ...]:
    """Coerce a stored or edited sample-filename list into the form the try-it table shows.

    Each entry is trimmed, blanks and exact repeats are dropped, and the order is kept. A value naming
    no sample at all falls back to :data:`DEFAULT_SAMPLES` rather than to an empty table: the table
    exists to show the patterns working, and an empty one shows nothing.

    :param samples: the stored samples, or the samples as edited.
    :returns: the samples in the order first seen, or the seeded defaults when there are none.
    """
    normalized: list[str] = []
    for entry in read_stored_strings(samples):
        sample = entry.strip()
        if not sample or sample in normalized:
            continue
        normalized.append(sample)
    return tuple(normalized) or DEFAULT_SAMPLES


@dataclass
class ScreenshotPatternsSettings:
    """The naming patterns every legacy screenshot scan is handed (#53, #287).

    Two stored fields, raw as the page left them: the patterns, and the try-it table's sample
    filenames (#287) -- saved beside the patterns because a set of names worth checking a
    configuration against is worth keeping. What everything else consumes is
    :attr:`screenshot_name_patterns`, the effective set the patterns resolve to.
    """

    patterns: tuple[str, ...] = field(default_factory=tuple)
    """The patterns as stored -- empty on a fresh install, where the effective set is the shipped default
    one rather than nothing."""

    samples: tuple[str, ...] = field(default_factory=tuple)
    """The try-it sample filenames as stored -- empty on a fresh install, where the effective set is
    :data:`DEFAULT_SAMPLES`."""

    @property
    def screenshot_name_patterns(self) -> tuple[ScreenshotNamePattern, ...]:
        """The effective set a scan is handed: :attr:`patterns` normalized, falling back to
        :data:`~rehuco_core.SCREENSHOT_NAME_PATTERNS` when it names nothing usable
        (:func:`normalize_screenshot_name_patterns`)."""
        return tuple(ScreenshotNamePattern(pattern) for pattern in normalize_screenshot_name_patterns(self.patterns))

    @property
    def screenshot_samples(self) -> tuple[str, ...]:
        """The try-it table's effective samples: :attr:`samples` normalized, falling back to
        :data:`DEFAULT_SAMPLES` when it names nothing (:func:`normalize_screenshot_samples`)."""
        return normalize_screenshot_samples(self.samples)

    def load(self, settings: QSettings) -> None:
        """Replace the stored patterns and samples with what's in persistent storage.

        The value is normalized on the way in, so a never-saved, empty, or unreadable one comes back as
        the shipped defaults rather than as an empty set that a later save would then persist
        (:func:`normalize_screenshot_name_patterns`).

        :param settings: the ``QSettings`` to read from.
        """
        settings.beginGroup(GROUP)
        self.patterns = normalize_screenshot_name_patterns(settings.value(PATTERNS_KEY))
        self.samples = normalize_screenshot_samples(settings.value(SAMPLES_KEY))
        settings.endGroup()

    def save(self, settings: QSettings) -> None:
        """Save the patterns and samples to persistent storage, as lists the ini backend can round-trip.

        :param settings: the ``QSettings`` to write to.
        """
        settings.beginGroup(GROUP)
        settings.setValue(PATTERNS_KEY, list(self.patterns))
        settings.setValue(SAMPLES_KEY, list(self.samples))
        settings.endGroup()


@lru_cache(maxsize=1)
def shared_screenshot_patterns_settings() -> ScreenshotPatternsSettings:
    """The single, process-wide `ScreenshotPatternsSettings` instance, loaded from persistent storage on
    first call -- the same shape, and for the same reason, as
    :func:`~rehuco_agent.settings.excluded_files_settings.shared_excluded_files_settings`: the settings
    page's Save must be what the next scan reads, and the conversion and the content walk must read the
    *same* object rather than a copy each.

    :returns: the shared instance.
    """
    settings = ScreenshotPatternsSettings()
    settings.load(persistent_settings())
    return settings
