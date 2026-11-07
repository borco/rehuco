"""Which name patterns the rename-suggestion list offers, one ordered list per resource type (#322).

`NameSuggestionModel` used to format every type's suggestions from one shared constant; this is where
that constant becomes one list per resource type, keyed by the type's plugin main key, so a
reference-images pack can prefer `{publisher} - {title}` while a tutorial leads with
`{authors} - {title}` without either list carrying the other's shapes.

**A pattern is the Locations grammar** (:mod:`rehuco_core.location_pattern`, #577): a format string with optional
``{{ ... }}`` groups, parsed and rendered in core so a root's layouts read it the same way.

**What is stored is not what is used.** The stored list keeps every row the user typed, an invalid one
included, so a typo is fixed in place rather than retyped after Apply silently dropped it; only the
*effective* list (:meth:`LocationTemplatesSettings.patterns_for`) skips a row that would not render.

Keyed by an open-ended type string rather than an enum of today's three types, the same way
`DefaultLayoutSettings` keys its per-type layout state (#320): a plugin this build doesn't know about yet
(Daz3D and beyond) needs no change here, on either the storage or the read side -- it just starts out
reading as "nothing customized yet" the same as any type that has never been saved.

A reactive ``QObject`` (`SimpleProperty` fields), the same shape `ScreenshotPatternsSettings` moved to
([[appendices.settings-pages#reacting-to-changes]]): an open document's `NameSuggestionModel` follows
:attr:`LocationTemplatesSettings.patterns_changed` and re-emits its own `changed`, so a saved pattern
change updates an already-open document's suggestion list without a reopen.
"""

from collections.abc import Iterable
from functools import lru_cache
from typing import Final

from borco_pyside.core import SimpleProperty
from PySide6.QtCore import QObject, QSettings, Signal
from rehuco_core import KNOWN_PLACEHOLDERS, location_pattern_is_valid

from .persistent_settings import persistent_settings, read_stored_strings

GROUP: Final = "location_templates"
PATTERNS_KEY: Final = "patterns"
SAMPLES_GROUP: Final = "location_try_it"
"""Where each type's Try-it sample record lives -- its own group rather than a key under :data:`GROUP`'s
per-type sub-groups, since :meth:`LocationTemplatesSettings.load` reads every one of those as a type
whose patterns were customized, and :meth:`LocationTemplatesSettings.save` prunes the ones
:attr:`~LocationTemplatesSettings.patterns` no longer names."""

SAMPLE_FIELDS: Final = ("title", "publisher", "authors", "year", "count")
"""The Try-it sample record's fields, in the order the page shows them -- also the placeholder each one
fills and the key it is stored under."""

DEFAULT_SAMPLE: Final[tuple[str, ...]] = ("Sample Title", "Sample Publisher", "Jane Doe, John Roe", "2025", "900+")
"""What the Try-it sample record starts out as, in :data:`SAMPLE_FIELDS` order, so a fresh page shows
the patterns naming something rather than an empty preview. ``count`` is seeded the same as the others
even on a type that hides its row (#349): the field is never read for such a type, since no pattern of
its own can name ``{count}``."""

NAME_SUGGESTION_PATTERNS: Final = (
    "{title}",
    "{{{publisher} - }}{title}",
    "{title}{{ [{year}]}}",
    "{{{authors} - }}{title}",
)
"""The shipped default pattern list, offered for every type until customized -- moved here from
`rehuco_agent.documents.name_suggestion_model` (#46), which now reads a type's *effective* list through
:meth:`LocationTemplatesSettings.patterns_for` instead of this constant directly. Every field but the
title sits in an optional group, so a record carrying only a title renders all four to the same name,
which `NameSuggestionModel` then merges into one suggestion."""


def effective_location_templates(
    patterns: Iterable[str], known_placeholders: frozenset[str] = KNOWN_PLACEHOLDERS
) -> tuple[str, ...]:
    """The patterns among ``patterns`` that render, or the shipped set when none does -- the one
    spelling of "what a document is offered", shared by :meth:`LocationTemplatesSettings.patterns_for`
    and the settings page's Try-it preview so the two can never disagree.

    :param patterns: a stored or staged list, invalid rows included.
    :param known_placeholders: the placeholders this type's patterns may name (#349).
    :returns: the renderable patterns in order, or :data:`NAME_SUGGESTION_PATTERNS` when there are none.
    """
    usable = tuple(pattern for pattern in patterns if location_pattern_is_valid(pattern, known_placeholders))
    return usable or NAME_SUGGESTION_PATTERNS


def normalize_location_templates(patterns: object, defaults: tuple[str, ...]) -> tuple[str, ...]:
    """Coerce a stored or edited pattern list into its **stored** shape.

    Each entry is trimmed; blank ones go, and duplicates are dropped by exact string match after
    trimming, the order the patterns were given in kept since it decides which suggestion is offered
    first. An invalid pattern is **kept**: dropping it on save would make a typo cost the whole row,
    and the settings page flags it in place instead. What skips it is the effective list,
    :meth:`LocationTemplatesSettings.patterns_for`.

    A value naming no pattern at all falls back to ``defaults`` rather than to *offer nothing*.

    :param patterns: the stored patterns, or the patterns as edited.
    :param defaults: what to fall back to when nothing remains.
    :returns: the patterns in the order first seen, or ``defaults`` when there are none.
    """
    normalized: list[str] = []
    for entry in read_stored_strings(patterns):
        pattern = entry.strip()
        if not pattern or pattern in normalized:
            continue
        normalized.append(pattern)
    return tuple(normalized) or defaults


class LocationTemplatesSettings(QObject):
    """The rename-suggestion pattern lists, one per resource type (#322), and each type's Try-it sample
    record.

    Two stored fields, both keyed by plugin main key. **Patterns**, raw as the page left it: the page
    stages against :meth:`stored_for`; everything that *names* a resource consumes :meth:`patterns_for`,
    the effective list a type resolves to. **Samples**, the page's Try-it record: staged, dirtied and
    applied like the patterns, so the page reopens on the record last applied rather than on
    :data:`DEFAULT_SAMPLE` every launch. Nothing but the page's preview reads it.

    :param parent: optional Qt parent.
    """

    patterns_changed = Signal(object)
    """Fires whenever any type's pattern list changes -- a dict value, so an explicit ``Signal(object)``
    rather than the auto-synthesized one, per `SimpleProperty`'s own convention -- so `NameSuggestionModel`
    can re-pull an open document's suggestions without a reopen."""

    patterns = SimpleProperty[dict[str, tuple[str, ...]]](default_factory=dict)
    """Every type's list as stored, keyed by plugin main key -- a type absent here has never been
    customized, where the effective list is :data:`NAME_SUGGESTION_PATTERNS`."""

    samples_changed = Signal(object)
    """Fires whenever any type's sample record changes -- a dict value, hence ``Signal(object)``."""

    samples = SimpleProperty[dict[str, tuple[str, ...]]](default_factory=dict)
    """Every type's Try-it sample record as stored, in :data:`SAMPLE_FIELDS` order, keyed by plugin main
    key -- a type absent here shows :data:`DEFAULT_SAMPLE`."""

    def sample_for(self, resource_type: str) -> tuple[str, ...]:
        """The Try-it sample record ``resource_type``'s page shows.

        :param resource_type: a plugin main key (e.g. ``"tutorial"``).
        :returns: the stored record, or :data:`DEFAULT_SAMPLE` when the type has none.
        """
        return self.samples.get(resource_type, DEFAULT_SAMPLE)

    def stored_for(self, resource_type: str) -> tuple[str, ...]:
        """The normalized **stored** list for ``resource_type`` -- invalid rows included, since the
        settings page shows and re-shows them until they are fixed.

        :param resource_type: a plugin main key (e.g. ``"tutorial"``).
        :returns: the stored patterns, or :data:`NAME_SUGGESTION_PATTERNS` when the type has none.
        """
        return normalize_location_templates(self.patterns.get(resource_type, ()), NAME_SUGGESTION_PATTERNS)

    def patterns_for(
        self, resource_type: str, known_placeholders: frozenset[str] = KNOWN_PLACEHOLDERS
    ) -> tuple[str, ...]:
        """The **effective** list for ``resource_type``: :meth:`stored_for` without the rows that cannot
        render.

        No plugin knowledge is needed here: a type this settings class has never seen simply reads as
        "nothing stored yet". Resolving a *foreign* or typeless document's type to a fallback type
        (e.g. ``"tutorial"``), and which placeholders that type accepts beyond the base four
        (:func:`known_placeholders_for`, #349), is the caller's job (`NameSuggestionModel`), which is the
        one place that already talks to the plugin registry.

        :param resource_type: a plugin main key (e.g. ``"tutorial"``).
        :param known_placeholders: the placeholders ``resource_type``'s patterns may name (#349).
        :returns: the renderable patterns in offer order, or :data:`NAME_SUGGESTION_PATTERNS` when the
            stored list holds none.
        """
        return effective_location_templates(self.stored_for(resource_type), known_placeholders)

    def load(self, settings: QSettings) -> None:
        """Replace every type's stored list, and every type's Try-it sample record, with what's in
        persistent storage.

        Each list is normalized on the way in, so a never-saved, empty, or unreadable one comes back as
        :data:`NAME_SUGGESTION_PATTERNS` rather than as an empty list a later save would then persist.
        The type set is read from the stored sub-groups themselves (:meth:`QSettings.childGroups`), the
        same way `DefaultLayoutSettings` enumerates its per-type entries (#320), so a type this build no
        longer installs still round-trips its saved list rather than losing it. The samples are read the
        same way, from :data:`SAMPLES_GROUP`, a field never stored reading as its :data:`DEFAULT_SAMPLE`
        value.

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

        settings.beginGroup(SAMPLES_GROUP)
        samples: dict[str, tuple[str, ...]] = {}
        for resource_type in settings.childGroups():
            settings.beginGroup(resource_type)
            samples[resource_type] = tuple(
                str(settings.value(field, default))
                for field, default in zip(SAMPLE_FIELDS, DEFAULT_SAMPLE, strict=True)
            )
            settings.endGroup()
        settings.endGroup()
        self.samples = samples

    def save(self, settings: QSettings) -> None:
        """Save every type's pattern list, as lists the ini backend can round-trip, and every type's
        Try-it sample record, one key per field.

        A stored type no longer present in :attr:`patterns` (or :attr:`samples`) is dropped, the same
        pruning `DefaultLayoutSettings.save` does -- what decides the type set is always the in-memory
        dict, never what a previous save happened to leave behind. A sample is stored field by field
        rather than as one list: a field is free text, and ``authors`` holds a comma, which the ini
        backend's list encoding would otherwise have to round-trip.

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

        settings.beginGroup(SAMPLES_GROUP)
        for stale in settings.childGroups():
            if stale not in self.samples:
                settings.remove(stale)
        for resource_type, sample in self.samples.items():
            settings.beginGroup(resource_type)
            for field, value in zip(SAMPLE_FIELDS, sample, strict=True):
                settings.setValue(field, value)
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
