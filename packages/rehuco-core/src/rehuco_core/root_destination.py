"""Where a record would live under a root, by the root's layouts -- or why it may not live there at all
([[mounts-and-storage#rehuroot]], #577).

A root's ``layouts`` map a type's main key, or ``*`` for any type not named, to **path templates** in the order they are
offered (#638), each the Locations grammar (:class:`~rehuco_core.location_pattern.LocationPattern`) plus ``/`` as a
level separator. The value ``*`` keeps
the record's current folder name, at the root's top, under the record's own root too (#643). A type with no
entry and no ``*`` is not admitted.

Rendering follows the order a name is made in today -- fields into the pattern, the Location Replacements, then the
sanitize step -- per level: the rendered template is cut at its own ``/``, and each segment is replaced and sanitized
on its own, so a ``/`` a field or a fallback holds (``AC/DC``) never opens a level. A placeholder outside every
optional group that the record leaves empty, with no fallback on the root, **forbids** the root for that record, and
the answer says why; so does a level that renders to nothing, or to a name starting with a dot (#680).

**A ``{buckets}`` level** ([[mounts-and-storage#buckets]], #680) is no folder of its own but the prefix buckets of the
level after it, which only the disk can say. So it renders to nothing here: the place is the path without it, and
:attr:`Placement.bucketed` says which of its levels is bucketed, for whoever reads the disk to resolve
(:mod:`rehuco_core.prefix_buckets`). It is a whole level by itself, outside every optional group, never the last level
and never right after another.

Pure: no disk, no Qt. The path row and the Roots view ask it (#579).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Final, Protocol

from .location_pattern import (
    BUCKETS_PLACEHOLDER,
    KNOWN_PLACEHOLDERS,
    PLACEHOLDERS,
    LocationPattern,
    known_placeholders_for,
    location_values,
)
from .path_keys import path_key
from .plugins import DEFAULT_PLUGIN_REGISTRY, PluginRegistry
from .rehu_document import RehuDocument
from .rehudb import CatalogRecord
from .rehuroot_file import ANY_TYPE, KEEP_NAME, Layouts
from .replacement_rule import ReplacementRule, apply_location_replacements
from .sanitized_names import location_name_problem, sanitize_name

LEVEL_SEPARATOR: Final = "/"
"""What separates two levels of a path template."""

SEPARATOR_STAND_IN: Final = chr(0xE000)
"""What a field's or a fallback's own ``/`` is held as while the rendered template is cut into levels: a private-use
character no field holds, put back before the replacements and the sanitize step see the segment."""

BUCKETS_STAND_IN: Final = chr(0xE001)
"""What ``{buckets}`` renders as while the template is cut into levels: a private-use character no field holds, so a
level that is exactly it is the buckets' level."""

BUCKETS_SHOWN: Final = "…"
"""How a bucketed place shows the buckets it has not resolved (#680): the path row and the layout preview draw it in
their place."""

STRUCTURE_SAMPLE: Final = "x"
"""What every other placeholder renders as when a template's ``{buckets}`` levels are checked: any one-level name."""

BUCKETS_IN_GROUP_PROBLEM: Final = "{buckets} cannot sit inside a {{ ... }} group: the buckets are never optional."
BUCKETS_NOT_A_LEVEL_PROBLEM: Final = "{buckets} must be a level of its own, between two / or at the start."
BUCKETS_LAST_PROBLEM: Final = "{buckets} must be followed by the level it buckets."
BUCKETS_TWICE_PROBLEM: Final = "{buckets} cannot follow another {buckets}: one level is bucketed once."


class LaidOutRoot(Protocol):
    """What a layout is read off: a root's name, its layouts and its fallbacks -- a root of the ``.rehuco`` as every
    machine reads it, or one this machine maps (#579)."""

    @property
    def label(self) -> str:  # pyright: ignore[reportReturnType]
        """The root's name; empty when it has none."""

    @property
    def location(self) -> str:  # pyright: ignore[reportReturnType]
        """Where the root is, the name when it has no label."""

    @property
    def layouts(self) -> Layouts:  # pyright: ignore[reportReturnType]
        """The path templates of each type's main key, ``*`` for any type not named, in offer order."""

    @property
    def fallbacks(self) -> Mapping[str, str]:  # pyright: ignore[reportReturnType]
        """What each placeholder renders as when a record leaves it empty."""


@dataclass(frozen=True, slots=True)
class RecordNaming:
    """What a layout reads of a record.

    :param main_key: the record's type, as its plugin's main key; a type no plugin claims, as spelled.
    :param folder_name: the record's current file or folder name -- what ``*`` keeps.
    :param values: its fields, keyed by placeholder name, every placeholder present
        (:func:`~rehuco_core.location_pattern.location_values`).
    :param placeholders: the placeholders its type's templates may name.
    """

    main_key: str
    folder_name: str
    values: Mapping[str, str] = field(compare=False)
    placeholders: frozenset[str]

    @classmethod
    def of(cls, document: RehuDocument, folder_name: str) -> RecordNaming:
        """What a layout reads of a document.

        :param document: the record.
        :param folder_name: its current file or folder name.
        :returns: the naming.
        """
        plugins = document.plugins
        values = location_values(
            document.title,
            document.publisher,
            document.authors,
            document.released,
            document.advertised_count,
            site_id=document.site_id,
        )
        placeholders = known_placeholders_for(plugins.field_names(document.type))
        return cls(plugins.main_key(document.type), folder_name, values, placeholders)

    @classmethod
    def of_record(
        cls, record: CatalogRecord, folder_name: str, plugins: PluginRegistry = DEFAULT_PLUGIN_REGISTRY
    ) -> RecordNaming:
        """What a layout reads of a record as the cache has it, no file read (#681).

        :param record: the record.
        :param folder_name: its current file or folder name.
        :param plugins: the plugins, which say what a type declares.
        :returns: the naming.
        """
        values = location_values(
            record.title,
            record.publisher,
            record.authors,
            record.released,
            record.advertised_count,
            # the cache marks no pair as the primary source's, but that source's site is the record's publisher
            site_id=next((site_id for site, site_id in record.site_ids if site == record.publisher), None),
        )
        placeholders = known_placeholders_for(plugins.field_names(record.type))
        return cls(plugins.main_key(record.type), folder_name, values, placeholders)


@dataclass(frozen=True, slots=True)
class Refusal:
    """Why a record may not live under a root.

    :param reason: the reason, in a sentence a user reads.
    """

    reason: str


@dataclass(frozen=True, slots=True)
class Placement:
    """One place a root's template puts a record (#638).

    :param relative: the place, relative to the root's folder, one segment per level, without its buckets.
    :param template: the path template that rendered it, as written and stripped; ``*`` included.
    :param bucketed: the indices of the levels of ``relative`` put in prefix buckets, which sit right before each, in
        ascending order (#680); none for a place with no buckets.
    """

    relative: PurePosixPath
    template: str
    bucketed: tuple[int, ...] = ()

    @property
    def shown(self) -> PurePosixPath:
        """The place as it is drawn before its buckets are resolved: :data:`BUCKETS_SHOWN` before each bucketed
        level."""
        return shown_place(self.relative, self.bucketed)


def shown_place(relative: PurePosixPath, bucketed: Sequence[int]) -> PurePosixPath:
    """A place with :data:`BUCKETS_SHOWN` before each of its bucketed levels (#680).

    :param relative: the place, without its buckets.
    :param bucketed: the indices of its bucketed levels.
    :returns: the place as drawn.
    """
    levels: list[str] = []
    for index, level in enumerate(relative.parts):
        if index in bucketed:
            levels.append(BUCKETS_SHOWN)
        levels.append(level)
    return PurePosixPath(*levels)


def layout_templates(root: LaidOutRoot, main_key: str) -> tuple[str, ...]:
    """The path templates a root gives a type, in offer order: the type's own, else the ``*`` ones (#639, #638).

    :param root: the root, its layouts.
    :param main_key: the record's type, as its plugin's main key.
    :returns: the templates as written; none when the root takes no such type.
    """
    return root.layouts.get(main_key) or root.layouts.get(ANY_TYPE) or ()


def destinations(
    root: LaidOutRoot,
    record: RecordNaming,
    rules: Sequence[ReplacementRule],
) -> tuple[Placement, ...] | Refusal:
    """Every place a root's layouts put a record, in row order (#638): a template that cannot be rendered for it is
    skipped, and two rendering the same place offer it once, at the first.

    :param root: the root, its layouts and fallbacks.
    :param record: what the layouts read of the record.
    :param rules: the Location Replacements, applied to each level before it is sanitized.
    :returns: the places; or why the root offers none -- it takes no such type, or the first template's refusal when
        every one refuses.
    """
    templates = layout_templates(root, record.main_key)
    if not templates:
        name = root.label or root.location
        return Refusal(f"{name} does not take a {record.main_key}: its layouts name no such type, and no '*'.")
    places: dict[tuple[str, tuple[int, ...]], Placement] = {}
    refusals: list[Refusal] = []
    for template in templates:
        place = destination(root, template, record, rules)
        if isinstance(place, Refusal):
            refusals.append(place)
        else:
            places.setdefault((path_key(str(place.relative)), place.bucketed), place)
    # every template either placed the record or refused it, so no place means a refusal
    return tuple(places.values()) or refusals[0]


def destination(
    root: LaidOutRoot,
    template: str,
    record: RecordNaming,
    rules: Sequence[ReplacementRule],
) -> Placement | Refusal:
    """Where one of a root's templates puts a record, relative to the root's folder.

    :param root: the root, its fallbacks.
    :param template: the path template, as written.
    :param record: what the layouts read of the record.
    :param rules: the Location Replacements, applied to each level before it is sanitized.
    :returns: the place, one segment per level and its buckets marked; or why the template does not take the record.
    """
    name = root.label or root.location
    if template.strip() == KEEP_NAME:
        return Placement(PurePosixPath(record.folder_name), KEEP_NAME)
    pattern = LocationPattern(template, record.placeholders | {BUCKETS_PLACEHOLDER})
    problem = pattern.problem or buckets_problem(pattern)
    if problem:
        return Refusal(f"{name}'s layout for a {record.main_key} cannot be used: {problem}")
    values = layout_values(record.values)
    missing = pattern.missing(values, root.fallbacks)
    if missing:
        return Refusal(f"The record has no {', '.join(missing)}, and {name} names no fallback for it.")
    laid_out = render_layout(pattern, values, root.fallbacks, rules)
    if isinstance(laid_out, LayoutProblem):
        return Refusal(f"{name}'s layout for a {record.main_key} {laid_out.value}.")
    return Placement(laid_out.relative, template.strip(), laid_out.bucketed)


def layout_template_problem(template: str, placeholders: frozenset[str]) -> str:
    """Why a path template cannot be used by a type that accepts ``placeholders``, or ``""`` when it can (#637).

    :param template: the template as written; ``*`` keeps the record's name and is always fine.
    :param placeholders: the placeholders the type's templates may name, :data:`BUCKETS_PLACEHOLDER` among them when
        the template may bucket (:func:`layout_placeholders`).
    :returns: the parse problem, the ``{buckets}`` problem, or ``""``.
    """
    if template.strip() == KEEP_NAME:
        return ""
    pattern = LocationPattern(template, placeholders)
    return pattern.problem or buckets_problem(pattern)


def buckets_problem(pattern: LocationPattern) -> str:
    """Why a parsed template's ``{buckets}`` cannot be used, or ``""`` when it can or names none (#680): each is a
    whole level, outside every optional group, followed by a level that is not ``{buckets}`` too.

    :param pattern: the template, parsed without a problem.
    :returns: one of the ``BUCKETS_*_PROBLEM`` strings, or ``""``.
    """
    if BUCKETS_PLACEHOLDER not in pattern.placeholders:
        return ""
    if BUCKETS_PLACEHOLDER in pattern.optional_placeholders:
        return BUCKETS_IN_GROUP_PROBLEM
    sample = {name: STRUCTURE_SAMPLE for name in pattern.placeholders} | {BUCKETS_PLACEHOLDER: BUCKETS_STAND_IN}
    levels = [level.strip() for level in pattern.render(sample).split(LEVEL_SEPARATOR)]
    for index, level in enumerate(levels):
        if BUCKETS_STAND_IN not in level:
            continue
        if level != BUCKETS_STAND_IN:
            return BUCKETS_NOT_A_LEVEL_PROBLEM
        if index == len(levels) - 1:
            return BUCKETS_LAST_PROBLEM
        if levels[index + 1] == BUCKETS_STAND_IN:
            return BUCKETS_TWICE_PROBLEM
    return ""


def is_bucketed_template(template: str) -> bool:
    """Whether a path template buckets one of its levels (#681).

    :param template: the template as written.
    :returns: whether it parses and names ``{buckets}``.
    """
    pattern = LocationPattern(template, frozenset((*PLACEHOLDERS, BUCKETS_PLACEHOLDER)))
    return BUCKETS_PLACEHOLDER in pattern.placeholders


def has_bucketed_layout(layouts: Layouts) -> bool:
    """Whether any of a root's layouts buckets a level, so that a rebalance has something to look at (#681).

    :param layouts: the root's layouts.
    :returns: whether one does.
    """
    return any(is_bucketed_template(template) for templates in layouts.values() for template in templates)


def layout_placeholders(main_key: str, registry: PluginRegistry) -> frozenset[str]:
    """The placeholders a root's template for ``main_key`` may name: the base set under ``*``, which covers every type,
    else the type's own (#637) -- each with :data:`BUCKETS_PLACEHOLDER`, which any type's layout may name (#680).

    :param main_key: a type's main key, or ``*``.
    :param registry: the plugins, which say what a type declares.
    :returns: the placeholder names.
    """
    if main_key == ANY_TYPE:
        return KNOWN_PLACEHOLDERS | {BUCKETS_PLACEHOLDER}
    return known_placeholders_for(registry.field_names(main_key)) | {BUCKETS_PLACEHOLDER}


def layout_values(values: Mapping[str, str]) -> dict[str, str]:
    """A record's values as a layout reads them: every placeholder, ``{buckets}`` held as :data:`BUCKETS_STAND_IN`
    (#680), so it is never missing and its level is found once rendered.

    :param values: the record's fields, every value placeholder present.
    :returns: the values with ``{buckets}``.
    """
    return {**values, BUCKETS_PLACEHOLDER: BUCKETS_STAND_IN}


class LayoutProblem(StrEnum):
    """Why a valid template renders no place for a record's values, worded to follow "<root>'s layout for a <type>"."""

    NAMELESS_LEVEL = "renders a folder with no name"
    """A level drops out, or sanitizes to nothing."""

    HIDDEN_LEVEL = "renders a folder starting with a dot, which no location may"
    """A level's name starts with a dot (#680)."""

    BUCKETS_LAST = "renders no level after {buckets}"
    """The level a ``{buckets}`` buckets dropped out with its optional group (#680)."""


def render_layout(
    pattern: LocationPattern,
    values: Mapping[str, str],
    fallbacks: Mapping[str, str],
    rules: Sequence[ReplacementRule],
) -> Placement | LayoutProblem:
    """Render a valid pattern into a place, one segment per level, each replaced and sanitized on its own, its
    ``{buckets}`` levels left out and marked on the place (#680).

    :param pattern: the parsed template, its ``{buckets}`` problem-free (:func:`buckets_problem`).
    :param values: the record's fields, every placeholder present -- ``{buckets}`` as :func:`layout_values` holds it.
    :param fallbacks: what a blank placeholder outside a group renders as.
    :param rules: the Location Replacements.
    :returns: the place, its template empty; or why it has none.
    """
    held = {key: value.replace(LEVEL_SEPARATOR, SEPARATOR_STAND_IN) for key, value in values.items()}
    held_fallbacks = {key: value.replace(LEVEL_SEPARATOR, SEPARATOR_STAND_IN) for key, value in fallbacks.items()}
    segments: list[str] = []
    bucketed: list[int] = []
    for raw in pattern.render(held, held_fallbacks).split(LEVEL_SEPARATOR):
        if raw.strip() == BUCKETS_STAND_IN:
            bucketed.append(len(segments))
            continue
        segment = sanitize_name(apply_location_replacements(raw.replace(SEPARATOR_STAND_IN, LEVEL_SEPARATOR), rules))
        if segment is None:
            return LayoutProblem.NAMELESS_LEVEL
        if location_name_problem(segment):
            return LayoutProblem.HIDDEN_LEVEL
        segments.append(segment)
    if bucketed and bucketed[-1] == len(segments):
        return LayoutProblem.BUCKETS_LAST
    return Placement(PurePosixPath(*segments), "", tuple(bucketed))
