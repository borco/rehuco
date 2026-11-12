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
the answer says why; so does a level that renders to nothing.

Pure: no disk, no Qt. The path row and the Roots view ask it (#579).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Final, Protocol

from .location_pattern import KNOWN_PLACEHOLDERS, LocationPattern, known_placeholders_for, location_values
from .path_keys import path_key
from .plugins.plugin_registry import PluginRegistry
from .rehu_document import RehuDocument
from .rehuroot_file import ANY_TYPE, KEEP_NAME, Layouts
from .replacement_rule import ReplacementRule, apply_location_replacements
from .sanitized_names import sanitize_name

LEVEL_SEPARATOR: Final = "/"
"""What separates two levels of a path template."""

SEPARATOR_STAND_IN: Final = chr(0xE000)
"""What a field's or a fallback's own ``/`` is held as while the rendered template is cut into levels: a private-use
character no field holds, put back before the replacements and the sanitize step see the segment."""


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
            document.title, document.publisher, document.authors, document.released, document.advertised_count
        )
        placeholders = known_placeholders_for(plugins.field_names(document.type))
        return cls(plugins.main_key(document.type), folder_name, values, placeholders)


@dataclass(frozen=True, slots=True)
class Refusal:
    """Why a record may not live under a root.

    :param reason: the reason, in a sentence a user reads.
    """

    reason: str


@dataclass(frozen=True, slots=True)
class Placement:
    """One place a root's template puts a record (#638).

    :param relative: the place, relative to the root's folder, one segment per level.
    :param template: the path template that rendered it, as written and stripped; ``*`` included.
    """

    relative: PurePosixPath
    template: str


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
    places: dict[str, Placement] = {}
    refusals: list[Refusal] = []
    for template in templates:
        relative = destination(root, template, record, rules)
        if isinstance(relative, Refusal):
            refusals.append(relative)
        else:
            places.setdefault(path_key(str(relative)), Placement(relative, template.strip()))
    # every template either placed the record or refused it, so no place means a refusal
    return tuple(places.values()) or refusals[0]


def destination(
    root: LaidOutRoot,
    template: str,
    record: RecordNaming,
    rules: Sequence[ReplacementRule],
) -> PurePosixPath | Refusal:
    """Where one of a root's templates puts a record, relative to the root's folder.

    :param root: the root, its fallbacks.
    :param template: the path template, as written.
    :param record: what the layouts read of the record.
    :param rules: the Location Replacements, applied to each level before it is sanitized.
    :returns: the path, one segment per level; or why the template does not take the record.
    """
    name = root.label or root.location
    if template.strip() == KEEP_NAME:
        return PurePosixPath(record.folder_name)
    pattern = LocationPattern(template, record.placeholders)
    if pattern.problem:
        return Refusal(f"{name}'s layout for a {record.main_key} cannot be used: {pattern.problem}")
    missing = pattern.missing(record.values, root.fallbacks)
    if missing:
        return Refusal(f"The record has no {', '.join(missing)}, and {name} names no fallback for it.")
    path = render_layout(pattern, record.values, root.fallbacks, rules)
    if path is None:
        return Refusal(f"{name}'s layout for a {record.main_key} renders a folder with no name.")
    return path


def layout_template_problem(template: str, placeholders: frozenset[str]) -> str:
    """Why a path template cannot be used by a type that accepts ``placeholders``, or ``""`` when it can (#637).

    :param template: the template as written; ``*`` keeps the record's name and is always fine.
    :param placeholders: the placeholders the type's templates may name.
    :returns: the parse problem, or ``""``.
    """
    if template.strip() == KEEP_NAME:
        return ""
    return LocationPattern(template, placeholders).problem


def layout_placeholders(main_key: str, registry: PluginRegistry) -> frozenset[str]:
    """The placeholders a root's template for ``main_key`` may name: the base four under ``*``, which covers every type,
    else the type's own (#637).

    :param main_key: a type's main key, or ``*``.
    :param registry: the plugins, which say what a type declares.
    :returns: the placeholder names.
    """
    if main_key == ANY_TYPE:
        return KNOWN_PLACEHOLDERS
    return known_placeholders_for(registry.field_names(main_key))


def render_layout(
    pattern: LocationPattern,
    values: Mapping[str, str],
    fallbacks: Mapping[str, str],
    rules: Sequence[ReplacementRule],
) -> PurePosixPath | None:
    """Render a valid pattern into a path, one segment per level, each replaced and sanitized on its own.

    :param pattern: the parsed template.
    :param values: the record's fields, every placeholder present.
    :param fallbacks: what a blank placeholder outside a group renders as.
    :param rules: the Location Replacements.
    :returns: the path, or ``None`` when a level renders to nothing.
    """
    held = {key: value.replace(LEVEL_SEPARATOR, SEPARATOR_STAND_IN) for key, value in values.items()}
    held_fallbacks = {key: value.replace(LEVEL_SEPARATOR, SEPARATOR_STAND_IN) for key, value in fallbacks.items()}
    segments: list[str] = []
    for raw in pattern.render(held, held_fallbacks).split(LEVEL_SEPARATOR):
        segment = sanitize_name(apply_location_replacements(raw.replace(SEPARATOR_STAND_IN, LEVEL_SEPARATOR), rules))
        if segment is None:
            return None
        segments.append(segment)
    return PurePosixPath(*segments)
