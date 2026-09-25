"""Which patterns a legacy `.tc`'s screenshots are recognized by
([[acquisition-tooling#screenshot-schemes]], #53, #287).

`rehuco_core.tc_screenshots.scan_tc_screenshots` takes the patterns as a parameter rather than reading a
constant, so this is where that set comes from -- and the conversion, the wizard's dry run and the
content walk all take it from here, because a file the conversion treats as a screenshot but the walk
counts as content is the bug the single set exists to prevent: `current_size` would move purely because
a resource was converted.

**A pattern is an ordinary regular expression** with a slot convention (`rehuco_core.ScreenshotNamePattern`):
one capture group names the slot the match belongs to, read as an integer; no capture group means slot
``0``. Patterns are an ordered list -- first match wins, and the earlier pattern's file also takes a slot
two names want (#288) -- so reordering the list is a real edit rather than a cosmetic one.

What happens **when two names want one slot** -- the earlier pattern wins, one stem under several
extensions resolves by pixel area, and everything else keeps its own name -- is not stored here and is
not the user's, for the reason `ExcludedFilesSettings` gives about its own structural tier: it applies
whatever this list says.

A reactive ``QObject`` (``SimpleProperty`` fields), not the plain dataclass this used to be
([[appendices.settings-pages#reacting-to-changes]]): an open document's `RehuDocumentModel` follows
:attr:`ScreenshotPatternsSettings.patterns_changed` and rebuilds its image scanner on it (#281), so a
saved pattern change moves files into and out of an already-open document's screenshot set.
"""

from functools import lru_cache
from typing import Final

from borco_pyside.core import SimpleProperty
from PySide6.QtCore import QObject, QSettings, Signal
from rehuco_core import SCREENSHOT_NAME_PATTERNS, ScreenshotNamePattern, ScreenshotNamePatterns

from .persistent_settings import persistent_settings, read_stored_strings

GROUP: Final = "screenshot_patterns"
PATTERNS_KEY: Final = "patterns"
SAMPLES_KEY: Final = "samples"
"""The try-it table's sample filenames -- the key #287 first wrote them under, so a list typed back then
comes back rather than being orphaned."""

DEFAULT_SAMPLES: Final = ("cover.jpg", "sample-03.jpg", "image-07.jpg")
"""What the settings page's try-it table starts out holding -- real matches of the shipped patterns, so
a fresh page shows the convention working rather than an empty table."""


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
    """Coerce a stored or edited pattern list into its **stored** shape.

    Each entry is trimmed; blank ones go, and duplicates are dropped by exact string match after
    trimming -- not case-insensitively, since regex casing matters syntactically -- with the order the
    patterns were given in kept, since it decides which pattern matches first. One that does not
    compile is **kept**: dropping it on save would make a typo cost the whole row, and the settings page
    flags it in place instead (#322). What skips it is the effective set,
    :attr:`ScreenshotPatternsSettings.screenshot_name_patterns`.

    A value naming no pattern at all falls back to :data:`~rehuco_core.SCREENSHOT_NAME_PATTERNS` rather
    than to *recognize nothing*: an empty set would silently convert every legacy resource without
    carrying a single screenshot across.

    Reading the stored shape at all -- including the ini backend's habit of handing a single-element
    list back as a bare string -- is
    :func:`~rehuco_agent.settings.persistent_settings.read_stored_strings`'s job; what is left here is
    the policy this list applies on top of it.

    :param patterns: the stored patterns, or the patterns as edited.
    :returns: the patterns in the order first seen, or the shipped defaults when there are none.
    """
    normalized: list[str] = []
    for entry in read_stored_strings(patterns):
        pattern = entry.strip()
        if not pattern or pattern in normalized:
            continue
        normalized.append(pattern)
    return tuple(normalized) or tuple(pattern.pattern for pattern in SCREENSHOT_NAME_PATTERNS)


def normalize_screenshot_samples(samples: object) -> tuple[str, ...]:
    """Coerce a stored or edited try-it sample list into its **stored** shape.

    Blank entries go, and the order is kept; a list left with nothing falls back to
    :data:`DEFAULT_SAMPLES`, the same policy :func:`normalize_screenshot_name_patterns` applies. Dropping
    blanks is what lets a freshly inserted row sit open for typing under "Apply changes as they're made":
    as long as it is blank it is not a change, so no commit reloads the table out from under its editor
    (#53's hazard, which the patterns avoid the same way).

    :param samples: the stored samples, or the samples as edited.
    :returns: the non-blank samples in order, or :data:`DEFAULT_SAMPLES` when there are none.
    """
    return tuple(sample for sample in read_stored_strings(samples) if sample.strip()) or DEFAULT_SAMPLES


class ScreenshotPatternsSettings(QObject):
    """The naming patterns every legacy screenshot scan is handed (#53, #287).

    Two stored fields. **Patterns**, raw as the page left it: the page stages against
    :attr:`stored_patterns`; every scan consumes :attr:`screenshot_name_patterns`, the effective set the
    patterns resolve to. **Samples**, the page's try-it filenames: staged, dirtied and applied like the
    patterns, so the table reopens on the names last applied. Nothing but the page's try-it table reads
    them.

    :param parent: optional Qt parent.
    """

    patterns = SimpleProperty[tuple[str, ...]](())
    """The patterns as stored -- empty on a fresh install, where the effective set is the shipped default
    one rather than nothing."""

    samples_changed = Signal(object)
    """Fires whenever :attr:`samples` changes -- a tuple value, hence ``Signal(object)``."""

    samples = SimpleProperty[tuple[str, ...]](DEFAULT_SAMPLES)
    """The try-it sample filenames as stored -- :data:`DEFAULT_SAMPLES` until any is applied."""

    @property
    def stored_patterns(self) -> tuple[str, ...]:
        """The normalized **stored** list -- uncompilable rows included, since the settings page shows
        and re-shows them until they are fixed (:func:`normalize_screenshot_name_patterns`)."""
        return normalize_screenshot_name_patterns(self.patterns)

    @property
    def screenshot_name_patterns(self) -> tuple[ScreenshotNamePattern, ...]:
        """The **effective** set a scan is handed: :attr:`stored_patterns` without the rows that do not
        compile, falling back to :data:`~rehuco_core.SCREENSHOT_NAME_PATTERNS` when none does."""
        usable = tuple(pattern for pattern in self.stored_patterns if pattern_is_valid(pattern))
        return tuple(ScreenshotNamePattern(pattern) for pattern in usable) or SCREENSHOT_NAME_PATTERNS

    def load(self, settings: QSettings) -> None:
        """Replace the stored patterns and try-it samples with what's in persistent storage.

        Both are normalized on the way in, so a never-saved, empty, or unreadable one comes back as the
        shipped defaults rather than as an empty list that a later save would then persist
        (:func:`normalize_screenshot_name_patterns`, :func:`normalize_screenshot_samples`).

        :param settings: the ``QSettings`` to read from.
        """
        settings.beginGroup(GROUP)
        self.patterns = normalize_screenshot_name_patterns(settings.value(PATTERNS_KEY))
        self.samples = normalize_screenshot_samples(settings.value(SAMPLES_KEY))
        settings.endGroup()

    def save(self, settings: QSettings) -> None:
        """Save the patterns and try-it samples to persistent storage, as lists the ini backend can
        round-trip.

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
