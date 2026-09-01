"""Which naming rules a legacy `.tc`'s screenshots are recognized by
([[acquisition-tooling#screenshot-schemes]], #53).

`rehuco_core.tc_screenshots.scan_tc_screenshots` takes the rules as a parameter rather than reading a
constant, so this is where that set comes from -- and the conversion, the wizard's dry run and the
content walk all take it from here, because a file the conversion renames aside but the walk counts as
content is the bug the single set exists to prevent: `current_size` would move purely because a
resource was converted.

**A rule is a series, not a filename pattern** (`rehuco_core.LegacyScreenshotRule`): a cover, and a
template for the files after it. Two rules can differ *only* in their cover -- an ``image-00``-first
series and an ``image-01``-first one share the same ``image-##`` template -- so the order they are
tried in decides which one claims a directory, and reordering the list is a real edit rather than a
cosmetic one.

The **tie-break** between files landing on one slot (largest pixel area, then ``.jpg``/``.jpeg``, then
the alphabetically first name) is not stored here and is not the user's, for the reason
`ExcludedFilesSettings` gives about its own structural tier: it applies whatever this list says.

A plain ``@dataclass``, like `ExcludedFilesSettings` and for the same reason: the rules are read only
when a scan runs, so nothing on screen changes when they do and there is nothing to watch them change.
"""

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Final

from PySide6.QtCore import QSettings
from rehuco_core import LEGACY_SCREENSHOT_RULES, LegacyScreenshotRule, LegacyScreenshotRuleMatcher

from .persistent_settings import persistent_settings

GROUP: Final = "legacy_screenshots"
RULES_KEY: Final = "rules"
COVER_KEY: Final = "cover"
REST_KEY: Final = "rest"


def normalize_legacy_screenshot_rules(rules: object) -> tuple[LegacyScreenshotRule, ...]:
    """Coerce a stored or edited rule list into the form a scan is handed.

    Both fields are trimmed; a rule core cannot compile is dropped, which is the same check the scan
    itself would apply (:class:`~rehuco_core.LegacyScreenshotRuleMatcher`) rather than a second spelling
    of it here. Duplicates are dropped case-insensitively, since matching is case-insensitive, and the
    order the rules were given in is kept -- it decides which rule claims a directory.

    A value naming no usable rule at all falls back to
    :data:`~rehuco_core.LEGACY_SCREENSHOT_RULES` rather than to *recognize nothing*: an empty set would
    silently convert every legacy resource without carrying a single screenshot across.

    :param rules: the stored rules, or the rules as edited.
    :returns: the usable rules in the order first seen, or the shipped defaults when there are none.
    """
    normalized: list[LegacyScreenshotRule] = []
    seen: set[tuple[str, str]] = set()
    for rule in rules if isinstance(rules, (list, tuple)) else ():
        if not isinstance(rule, LegacyScreenshotRule):
            continue
        trimmed = LegacyScreenshotRule(rule.cover.strip(), rule.rest.strip())
        key = (trimmed.cover.lower(), trimmed.rest.lower())
        if key in seen:
            continue
        try:
            LegacyScreenshotRuleMatcher(trimmed)
        except ValueError:
            continue
        seen.add(key)
        normalized.append(trimmed)
    return tuple(normalized) or LEGACY_SCREENSHOT_RULES


@dataclass
class LegacyScreenshotsSettings:
    """The naming rules every legacy screenshot scan is handed (#53).

    One stored field, raw as the page left it; what everything else consumes is
    :attr:`legacy_screenshot_rules`, the effective set it resolves to.
    """

    rules: tuple[LegacyScreenshotRule, ...] = field(default_factory=tuple)
    """The rules as stored -- empty on a fresh install, where the effective set is the shipped default
    one rather than nothing."""

    @property
    def legacy_screenshot_rules(self) -> tuple[LegacyScreenshotRule, ...]:
        """The effective set a scan is handed: :attr:`rules` normalized, falling back to
        :data:`~rehuco_core.LEGACY_SCREENSHOT_RULES` when it names nothing usable
        (:func:`normalize_legacy_screenshot_rules`)."""
        return normalize_legacy_screenshot_rules(self.rules)

    def load(self, settings: QSettings) -> None:
        """Replace the stored rules with what's in persistent storage.

        Read as a ``QSettings`` array rather than as a flat string list, because a rule is two fields
        and pairing them by position in one list would make a half-written entry unreadable. The value
        is normalized on the way in, so a never-saved or unreadable one comes back as the shipped
        defaults rather than as an empty set a later save would then persist.

        :param settings: the ``QSettings`` to read from.
        """
        settings.beginGroup(GROUP)
        stored: list[LegacyScreenshotRule] = []
        for index in range(settings.beginReadArray(RULES_KEY)):
            settings.setArrayIndex(index)
            cover = settings.value(COVER_KEY)
            rest = settings.value(REST_KEY)
            if isinstance(cover, str) and isinstance(rest, str):
                stored.append(LegacyScreenshotRule(cover, rest))
        settings.endArray()
        settings.endGroup()
        self.rules = normalize_legacy_screenshot_rules(stored)

    def save(self, settings: QSettings) -> None:
        """Save the rules to persistent storage, as an array of cover/rest pairs.

        :param settings: the ``QSettings`` to write to.
        """
        settings.beginGroup(GROUP)
        settings.beginWriteArray(RULES_KEY, len(self.rules))
        for index, rule in enumerate(self.rules):
            settings.setArrayIndex(index)
            settings.setValue(COVER_KEY, rule.cover)
            settings.setValue(REST_KEY, rule.rest)
        settings.endArray()
        settings.endGroup()


@lru_cache(maxsize=1)
def shared_legacy_screenshots_settings() -> LegacyScreenshotsSettings:
    """The single, process-wide `LegacyScreenshotsSettings` instance, loaded from persistent storage on
    first call -- the same shape, and for the same reason, as
    :func:`~rehuco_agent.settings.excluded_files_settings.shared_excluded_files_settings`: the settings
    page's Save must be what the next scan reads, and the conversion and the content walk must read the
    *same* object rather than a copy each.

    :returns: the shared instance.
    """
    settings = LegacyScreenshotsSettings()
    settings.load(persistent_settings())
    return settings
