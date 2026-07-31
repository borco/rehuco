"""Which files a resource's content scan leaves out ([[data-model#checksums]], #226).

`rehuco_core.rehu_content_files.enumerate_content_files` takes the excluded-name globs as a parameter
rather than reading a constant, so this is where that set comes from -- and the size scan and the
checksums both take it from here, because a file counted by one and skipped by the other is the bug the
single set exists to prevent.

Only the **junk** tier is stored here. The structural exclusions -- every ``<record>.rehu`` a scan finds,
with its ``<record>NN`` screenshots and its ``<record>.sfv``/``.md5``/``.sha256`` manifest -- are derived
inside core and are deliberately not offered: [[data-model#checksums]] defines all three as editable at
any moment, so counting them would make every size and checksum need recomputing after an ordinary
metadata edit, and a user able to add the ``.rehu`` back could reintroduce exactly that.

A plain ``@dataclass``, like `ReferenceImagesSettings` and for the same reason: the set is read only when
a scan runs, so nothing on screen changes when it does and there is nothing to watch it change.
"""

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Final

from PySide6.QtCore import QSettings
from rehuco_core import EXCLUDED_FILE_PATTERNS

from .persistent_settings import persistent_settings, read_stored_strings

GROUP: Final = "excluded_files"
PATTERNS_KEY: Final = "patterns"


def normalize_patterns(value: object) -> tuple[str, ...]:
    """Coerce a stored or edited pattern list into the form a scan is handed.

    Surrounding whitespace is trimmed, blank entries and duplicates are dropped, and the order the
    patterns were given in is kept. A value that names no usable pattern at all -- absent, empty, or of a
    type a list was never stored as -- falls back to
    :data:`~rehuco_core.constants.EXCLUDED_FILE_PATTERNS` rather than to *no exclusions*: an empty set
    would silently start counting every share's ``Thumbs.db``, churning sizes and checksums on resources
    nobody touched, which is the failure this list exists to prevent.

    Reading the stored shape at all -- including the ini backend's habit of handing a single-element
    list back as a bare string -- is
    :func:`~rehuco_agent.settings.persistent_settings.read_stored_strings`'s job; what is left here is
    the policy this list applies on top of it.

    :param value: the raw stored value, or the patterns as edited.
    :returns: the usable patterns in the order first seen, or the shipped defaults when there are none.
    """
    patterns: list[str] = []
    for entry in read_stored_strings(value):
        pattern = entry.strip()
        if pattern and pattern not in patterns:
            patterns.append(pattern)
    return tuple(patterns) or EXCLUDED_FILE_PATTERNS


@dataclass
class ExcludedFilesSettings:
    """The filename globs left out of every directory-scoped resource's content scan (#226).

    One stored field, raw as the page left it; what everything else consumes is
    :attr:`excluded_file_patterns`, the effective set it resolves to.
    """

    patterns: tuple[str, ...] = field(default_factory=tuple)
    """The junk-file globs as stored -- empty on a fresh install, where the effective set is the shipped
    default one rather than nothing."""

    @property
    def excluded_file_patterns(self) -> tuple[str, ...]:
        """The effective set a content scan is handed: :attr:`patterns` normalized, falling back to
        :data:`~rehuco_core.constants.EXCLUDED_FILE_PATTERNS` when it names nothing usable
        (:func:`normalize_patterns`)."""
        return normalize_patterns(self.patterns)

    def load(self, settings: QSettings) -> None:
        """Replace the stored patterns with what's in persistent storage.

        The value is normalized on the way in, so a never-saved, empty, or unreadable one comes back as
        the shipped defaults rather than as an empty set that a later save would then persist
        (:func:`normalize_patterns`).

        :param settings: the ``QSettings`` to read from.
        """
        settings.beginGroup(GROUP)
        self.patterns = normalize_patterns(settings.value(PATTERNS_KEY))
        settings.endGroup()

    def save(self, settings: QSettings) -> None:
        """Save the patterns to persistent storage, as a list the ini backend can round-trip.

        :param settings: the ``QSettings`` to write to.
        """
        settings.beginGroup(GROUP)
        settings.setValue(PATTERNS_KEY, list(self.patterns))
        settings.endGroup()


@lru_cache(maxsize=1)
def shared_excluded_files_settings() -> ExcludedFilesSettings:
    """The single, process-wide `ExcludedFilesSettings` instance, loaded from persistent storage on first
    call -- the same shape, and for the same reason, as
    :func:`~rehuco_agent.settings.reference_images_settings.shared_reference_images_settings`: the
    settings page's Save must be what the next scan reads, and the size scan and the checksums must read
    the *same* object rather than a copy each.

    :returns: the shared instance.
    """
    settings = ExcludedFilesSettings()
    settings.load(persistent_settings())
    return settings
