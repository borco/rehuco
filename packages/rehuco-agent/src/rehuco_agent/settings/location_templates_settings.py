"""Which name patterns the rename-suggestion list offers, one ordered list per resource type (#322).

`NameSuggestionModel` used to format every type's suggestions from one shared constant; this is where
that constant becomes one list per resource type, keyed by the type's plugin main key, so a
reference-images pack can prefer `{publisher} - {title}` while a tutorial leads with
`{authors} - {title}` without either list carrying the other's shapes.

Keyed by an open-ended type string rather than an enum of today's three types, the same way
`DefaultLayoutSettings` keys its per-type layout state (#320): a plugin this build doesn't know about yet
(Daz3D and beyond) needs no change here, on either the storage or the read side -- it just starts out
reading as "nothing customized yet" the same as any type that has never been saved.

A reactive ``QObject`` (`SimpleProperty` fields), the same shape `ScreenshotPatternsSettings` moved to
([[appendices.settings-pages#reacting-to-changes]]): an open document's `NameSuggestionModel` follows
:attr:`LocationTemplatesSettings.patterns_changed` and re-emits its own `changed`, so a saved pattern
change updates an already-open document's suggestion list without a reopen.
"""

import string
from functools import lru_cache
from typing import Final

from borco_pyside.core import SimpleProperty
from PySide6.QtCore import QObject, QSettings, Signal

from .persistent_settings import persistent_settings, read_stored_strings

GROUP: Final = "location_templates"
PATTERNS_KEY: Final = "patterns"

NAME_SUGGESTION_PATTERNS: Final = (
    "{title}",
    "{publisher} - {title}",
    "{title} [{year}]",
    "{authors} - {title}",
)
"""The shipped default pattern list, offered for every type until customized -- moved here from
`rehuco_agent.documents.name_suggestion_model` (#46), which now reads a type's *effective* list through
:meth:`LocationTemplatesSettings.patterns_for` instead of this constant directly."""

KNOWN_PLACEHOLDERS: Final = frozenset({"title", "publisher", "authors", "year"})
"""The four fields a pattern may interpolate ([[field-schema#field-mapping]]) -- adding placeholders is
out of scope for #322, so this set is exactly what `location_pattern_is_valid` checks a pattern against."""


def location_pattern_is_valid(pattern: str) -> bool:
    """Whether ``pattern`` names only known placeholders and is otherwise a well-formed format string.

    A blank pattern, one that fails to parse as a format string, or one naming a placeholder outside
    :data:`KNOWN_PLACEHOLDERS` (including a positional or blank ``{}``) is not usable -- exposed here so
    :func:`normalize_location_templates` and the settings page's per-row validity flag share one spelling
    of it rather than two.

    :param pattern: the raw pattern string, trimmed or not.
    :returns: whether it is blank, or names a placeholder :meth:`str.format` would refuse or this
        settings class does not recognize.
    """
    if not pattern.strip():
        return False
    try:
        fields = [field_name for _, field_name, _, _ in string.Formatter().parse(pattern) if field_name is not None]
    except ValueError:
        return False
    return all(field_name in KNOWN_PLACEHOLDERS for field_name in fields)


def normalize_location_templates(patterns: object, defaults: tuple[str, ...]) -> tuple[str, ...]:
    """Coerce a stored or edited pattern list into the form :meth:`LocationTemplatesSettings.patterns_for`
    hands out.

    Each entry is trimmed; one that names an unknown placeholder or fails to parse is dropped, the same
    check :func:`location_pattern_is_valid` applies rather than a second spelling of it here. Duplicates
    are dropped by exact string match after trimming, and the order the patterns were given in is kept,
    since it decides which suggestion is offered first.

    A value naming no usable pattern at all falls back to ``defaults`` rather than to *offer nothing*.

    :param patterns: the stored patterns, or the patterns as edited.
    :param defaults: what to fall back to when nothing usable remains.
    :returns: the usable patterns in the order first seen, or ``defaults`` when there are none.
    """
    normalized: list[str] = []
    for entry in read_stored_strings(patterns):
        pattern = entry.strip()
        if not pattern or pattern in normalized or not location_pattern_is_valid(pattern):
            continue
        normalized.append(pattern)
    return tuple(normalized) or defaults


class LocationTemplatesSettings(QObject):
    """The rename-suggestion pattern lists, one per resource type (#322).

    One stored field: every type's list, keyed by its plugin main key, raw as the page left it. What
    everything else consumes is :meth:`patterns_for`, the effective list a type resolves to. The page's
    Try-it sample record is deliberately **not** here: it previews a list and is not a setting, so it is
    never saved.

    :param parent: optional Qt parent.
    """

    patterns_changed = Signal(object)
    """Fires whenever any type's pattern list changes -- a dict value, so an explicit ``Signal(object)``
    rather than the auto-synthesized one, per `SimpleProperty`'s own convention -- so `NameSuggestionModel`
    can re-pull an open document's suggestions without a reopen."""

    patterns = SimpleProperty[dict[str, tuple[str, ...]]](default_factory=dict)
    """Every type's list as stored, keyed by plugin main key -- a type absent here has never been
    customized, where the effective list is :data:`NAME_SUGGESTION_PATTERNS`."""

    def patterns_for(self, resource_type: str) -> tuple[str, ...]:
        """The effective, normalized pattern list for ``resource_type``.

        No plugin knowledge is needed here: a type this settings class has never seen simply reads as
        "nothing stored yet" -- the same effective list a recognised type gets when its own stored list
        normalizes to nothing. Resolving a *foreign* or typeless document's type to a fallback type
        (e.g. ``"tutorial"``) is the caller's job (`NameSuggestionModel`), which is the one place that
        already talks to the plugin registry.

        :param resource_type: a plugin main key (e.g. ``"tutorial"``).
        :returns: the usable patterns in offer order, or :data:`NAME_SUGGESTION_PATTERNS` when the type's
            stored list names nothing usable.
        """
        return normalize_location_templates(self.patterns.get(resource_type, ()), NAME_SUGGESTION_PATTERNS)

    def load(self, settings: QSettings) -> None:
        """Replace every type's stored list with what's in persistent storage.

        Each is normalized on the way in, so a never-saved, empty, or unreadable one comes back as
        :data:`NAME_SUGGESTION_PATTERNS` rather than as an empty list a later save would then persist.
        The type set is read from the stored sub-groups themselves (:meth:`QSettings.childGroups`), the
        same way `DefaultLayoutSettings` enumerates its per-type entries (#320), so a type this build no
        longer installs still round-trips its saved list rather than losing it.

        :param settings: the ``QSettings`` to read from.
        """
        settings.beginGroup(GROUP)
        patterns: dict[str, tuple[str, ...]] = {}
        for resource_type in settings.childGroups():
            settings.beginGroup(resource_type)
            patterns[resource_type] = normalize_location_templates(
                settings.value(PATTERNS_KEY), NAME_SUGGESTION_PATTERNS
            )
            settings.endGroup()
        settings.endGroup()
        self.patterns = patterns

    def save(self, settings: QSettings) -> None:
        """Save every type's pattern list to persistent storage, as lists the ini backend can round-trip.

        A stored type no longer present in :attr:`patterns` is dropped, the same pruning
        `DefaultLayoutSettings.save` does -- what decides the type set is always the in-memory dict, never
        what a previous save happened to leave behind.

        :param settings: the ``QSettings`` to write to.
        """
        settings.beginGroup(GROUP)
        for stale in settings.childGroups():
            if stale not in self.patterns:
                settings.remove(stale)
        for resource_type, patterns in self.patterns.items():
            settings.beginGroup(resource_type)
            settings.setValue(PATTERNS_KEY, list(patterns))
            settings.endGroup()
        settings.endGroup()


@lru_cache(maxsize=1)
def shared_location_templates_settings() -> LocationTemplatesSettings:
    """The single, process-wide `LocationTemplatesSettings` instance, loaded from persistent storage on
    first call -- the same shape, and for the same reason, as
    :func:`~rehuco_agent.settings.screenshot_patterns_settings.shared_screenshot_patterns_settings`: the
    settings page's Save must be what the next `NameSuggestionModel` reads, and every open document must
    read the *same* object rather than a copy each.

    :returns: the shared instance.
    """
    settings = LocationTemplatesSettings()
    settings.load(persistent_settings())
    return settings
