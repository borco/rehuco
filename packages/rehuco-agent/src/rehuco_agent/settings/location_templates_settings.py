"""Which name patterns the rename-suggestion list offers, one ordered list per resource type (#322).

`NameSuggestionModel` used to format every type's suggestions from one shared constant; this is where
that constant becomes one list per resource type, keyed by the type's plugin main key, so a
reference-images pack can prefer `{publisher} - {title}` while a tutorial leads with
`{authors} - {title}` without either list carrying the other's shapes.

**A pattern is a format string with optional groups.** ``{title}`` / ``{publisher}`` / ``{authors}`` /
``{year}`` interpolate the record's fields, and a ``{{ ... }}`` group is emitted only when every
placeholder inside it has a value -- so ``{title}{{ [{year}]}}`` names a resource ``Title [2026]`` with a
year and plain ``Title`` without one, instead of ``Title []``. Whitespace inside a group is kept
verbatim, which is how a group carries its own separator. This deliberately takes ``{{`` away from
:meth:`str.format`'s literal-brace meaning: a literal brace in a folder name is never wanted, and a
group that can drop out is.

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

import string
from collections.abc import Iterable, Mapping
from functools import lru_cache
from typing import Final

from borco_pyside.core import SimpleProperty
from PySide6.QtCore import QObject, QSettings, Signal

from .persistent_settings import persistent_settings, read_stored_strings

GROUP: Final = "location_templates"
PATTERNS_KEY: Final = "patterns"

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

KNOWN_PLACEHOLDERS: Final = frozenset({"title", "publisher", "authors", "year"})
"""The four fields a pattern may interpolate ([[field-schema#field-mapping]]) -- adding placeholders is
out of scope for #322, so this set is exactly what `location_pattern_problem` checks a pattern against."""

BLANK_PATTERN_PROBLEM: Final = "A pattern is a format string interpolating {title} / {publisher} / {authors} / {year}."
MALFORMED_PATTERN_PROBLEM: Final = (
    "This does not parse as a format string: a { or } is unbalanced, or a placeholder carries a "
    "format spec or conversion, which a name never needs."
)
UNKNOWN_PLACEHOLDER_PROBLEM: Final = "This names a placeholder other than {title} / {publisher} / {authors} / {year}."
EMPTY_GROUP_PROBLEM: Final = "A {{ ... }} group must name at least one placeholder, or it could never be left out."
STRAY_GROUP_MARKER_PROBLEM: Final = (
    "A {{ is not closed, a }} is not opened, or one {{ ... }} group sits inside another."
)


class LocationPattern:
    """One pattern, parsed once into its plain and optional parts (#322).

    Parsing is a single left-to-right scan rather than a regex, because a group's inner text may itself
    hold braces -- ``{{{authors}}}`` is "authors, optional, and nothing else" -- and only a scan that
    knows it is inside a placeholder can tell that pattern's ``}}}`` apart from a group closing early.

    :param pattern: the raw pattern string, trimmed or not.
    """

    def __init__(self, pattern: str) -> None:
        self.__parts: list[tuple[str, bool]] = []
        """Each part's text and whether it is an optional group."""
        self.__placeholders: list[tuple[str, ...]] = []
        """Each part's placeholder names, parallel to :attr:`__parts`."""
        self.__problem: Final = self.__parse(pattern.strip())

    @property
    def problem(self) -> str:
        """Why this pattern cannot render, or ``""`` when it can."""
        return self.__problem

    def render(self, values: Mapping[str, str]) -> str:
        """Interpolate ``values``, emitting each optional group only when every placeholder inside it has
        a non-blank value.

        :param values: the record's fields, keyed by placeholder name; every known placeholder present.
        :returns: the rendered name, possibly empty; ``""`` when the pattern is invalid.
        """
        if self.__problem:
            return ""
        rendered: list[str] = []
        for (text, optional), placeholders in zip(self.__parts, self.__placeholders, strict=True):
            if optional and not all(values[name].strip() for name in placeholders):
                continue
            rendered.append(text.format(**values))
        return "".join(rendered)

    def __parse(self, pattern: str) -> str:
        """Split ``pattern`` into parts and check each one, filling the two part lists.

        :param pattern: the trimmed pattern.
        :returns: the first problem found, or ``""``.
        """
        if not pattern:
            return BLANK_PATTERN_PROBLEM
        problem = self.__split(pattern)
        for text, optional in self.__parts:
            if problem:
                break
            problem = self.__check_part(text, optional)
        return problem

    def __check_part(self, text: str, optional: bool) -> str:
        """Check one part's placeholders, recording their names when the part is fine.

        :param text: the part's text, a plain format string.
        :param optional: whether the part is a ``{{ ... }}`` group.
        :returns: the part's problem, or ``""``.
        """
        try:
            fields = [field for field in string.Formatter().parse(text) if field[1] is not None]
        except ValueError:
            return MALFORMED_PATTERN_PROBLEM
        # a spec or conversion is refused outright rather than passed to `str.format`: `parse` does
        # not look inside a spec, so ``{title:{series}}`` would read as valid here and raise there
        if any(spec or conversion for _, _, spec, conversion in fields):
            return MALFORMED_PATTERN_PROBLEM
        names = tuple(name for _, name, _, _ in fields if name is not None)
        if any(name not in KNOWN_PLACEHOLDERS for name in names):
            return UNKNOWN_PLACEHOLDER_PROBLEM
        if optional and not names:
            return EMPTY_GROUP_PROBLEM
        self.__placeholders.append(names)
        return ""

    def __split(self, pattern: str) -> str:
        """Cut ``pattern`` at its ``{{`` / ``}}`` markers into :attr:`__parts`.

        A double brace only counts as a group marker outside a placeholder: while a single ``{`` is
        open, a ``}`` closes it first, so ``{{{authors}}}`` reads as one group holding ``{authors}``.

        :param pattern: the trimmed pattern.
        :returns: a group-marker problem, or ``""``.
        """
        current: list[str] = []
        in_group = False
        depth = 0
        position = 0
        while position < len(pattern):
            pair = pattern[position : position + 2]
            if pair == "{{" and depth == 0:
                if in_group:
                    return STRAY_GROUP_MARKER_PROBLEM
                self.__flush(current, optional=False)
                in_group = True
                position += 2
                continue
            if pair == "}}" and depth == 0:
                if not in_group:
                    return STRAY_GROUP_MARKER_PROBLEM
                self.__flush(current, optional=True)
                in_group = False
                position += 2
                continue
            char = pattern[position]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth < 0:
                    return MALFORMED_PATTERN_PROBLEM
            current.append(char)
            position += 1
        if in_group:
            return STRAY_GROUP_MARKER_PROBLEM
        if depth != 0:
            return MALFORMED_PATTERN_PROBLEM
        self.__flush(current, optional=False)
        return ""

    def __flush(self, current: list[str], *, optional: bool) -> None:
        """Close the part being gathered, if it holds anything, and start the next.

        :param current: the characters gathered so far; emptied.
        :param optional: whether they form a group.
        """
        if current or optional:
            self.__parts.append(("".join(current), optional))
        current.clear()


def location_pattern_problem(pattern: str) -> str:
    """Why ``pattern`` is unusable, or ``""`` when it is fine -- one spelling shared by
    :func:`normalize_location_templates`, the settings page's per-row flag and its Try-it preview.

    :param pattern: the raw pattern string, trimmed or not.
    :returns: one of the ``*_PROBLEM`` strings, or ``""``.
    """
    return LocationPattern(pattern).problem


def location_pattern_is_valid(pattern: str) -> bool:
    """Whether ``pattern`` renders: names only known placeholders, balances its braces, and gives every
    ``{{ ... }}`` group a placeholder to depend on.

    :param pattern: the raw pattern string, trimmed or not.
    :returns: ``not location_pattern_problem(pattern)``.
    """
    return not location_pattern_problem(pattern)


def render_location_pattern(pattern: str, values: Mapping[str, str]) -> str:
    """Interpolate ``values`` into ``pattern``, dropping every optional group whose placeholders are not
    all filled.

    :param pattern: the raw pattern string.
    :param values: the record's fields, keyed by placeholder name; every known placeholder present.
    :returns: the rendered name, possibly empty; ``""`` for an invalid pattern.
    """
    return LocationPattern(pattern).render(values)


def effective_location_templates(patterns: Iterable[str]) -> tuple[str, ...]:
    """The patterns among ``patterns`` that render, or the shipped set when none does -- the one
    spelling of "what a document is offered", shared by :meth:`LocationTemplatesSettings.patterns_for`
    and the settings page's Try-it preview so the two can never disagree.

    :param patterns: a stored or staged list, invalid rows included.
    :returns: the renderable patterns in order, or :data:`NAME_SUGGESTION_PATTERNS` when there are none.
    """
    usable = tuple(pattern for pattern in patterns if location_pattern_is_valid(pattern))
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
    """The rename-suggestion pattern lists, one per resource type (#322).

    One stored field: every type's list, keyed by its plugin main key, raw as the page left it. The page
    stages against :meth:`stored_for`; everything that *names* a resource consumes :meth:`patterns_for`,
    the effective list a type resolves to. The page's Try-it sample record is deliberately **not** here:
    it previews a list and is not a setting, so it is never saved.

    :param parent: optional Qt parent.
    """

    patterns_changed = Signal(object)
    """Fires whenever any type's pattern list changes -- a dict value, so an explicit ``Signal(object)``
    rather than the auto-synthesized one, per `SimpleProperty`'s own convention -- so `NameSuggestionModel`
    can re-pull an open document's suggestions without a reopen."""

    patterns = SimpleProperty[dict[str, tuple[str, ...]]](default_factory=dict)
    """Every type's list as stored, keyed by plugin main key -- a type absent here has never been
    customized, where the effective list is :data:`NAME_SUGGESTION_PATTERNS`."""

    def stored_for(self, resource_type: str) -> tuple[str, ...]:
        """The normalized **stored** list for ``resource_type`` -- invalid rows included, since the
        settings page shows and re-shows them until they are fixed.

        :param resource_type: a plugin main key (e.g. ``"tutorial"``).
        :returns: the stored patterns, or :data:`NAME_SUGGESTION_PATTERNS` when the type has none.
        """
        return normalize_location_templates(self.patterns.get(resource_type, ()), NAME_SUGGESTION_PATTERNS)

    def patterns_for(self, resource_type: str) -> tuple[str, ...]:
        """The **effective** list for ``resource_type``: :meth:`stored_for` without the rows that cannot
        render.

        No plugin knowledge is needed here: a type this settings class has never seen simply reads as
        "nothing stored yet". Resolving a *foreign* or typeless document's type to a fallback type
        (e.g. ``"tutorial"``) is the caller's job (`NameSuggestionModel`), which is the one place that
        already talks to the plugin registry.

        :param resource_type: a plugin main key (e.g. ``"tutorial"``).
        :returns: the renderable patterns in offer order, or :data:`NAME_SUGGESTION_PATTERNS` when the
            stored list holds none.
        """
        return effective_location_templates(self.stored_for(resource_type))

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
