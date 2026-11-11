"""Where a record would live under a root, by the root's layouts -- or why it may not live there at all
([[mounts-and-storage#rehuroot]], #577).

A root's ``layouts`` map a type's main key, or ``*`` for any type not named, to a **path template**: the Locations
grammar (:class:`~rehuco_core.location_pattern.LocationPattern`) plus ``/`` as a level separator. The value ``*`` keeps
the record's current folder name, at the root's top -- or, under the root the record is already in, where it is
(#636). A type with no entry and no ``*`` is not admitted.

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

from .location_pattern import LocationPattern, known_placeholders_for, location_values
from .rehu_document import RehuDocument
from .rehuroot_file import ANY_TYPE, KEEP_NAME
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
    def layouts(self) -> Mapping[str, str]:  # pyright: ignore[reportReturnType]
        """The path template of each type's main key, ``*`` for any type not named."""

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


def layout_template(root: LaidOutRoot, main_key: str) -> str | None:
    """The path template a root gives a type: the type's own, else the ``*`` one (#639).

    :param root: the root, its layouts.
    :param main_key: the record's type, as its plugin's main key.
    :returns: the template as written, or ``None`` when the root takes no such type.
    """
    return root.layouts.get(main_key, root.layouts.get(ANY_TYPE))


def destination(
    root: LaidOutRoot,
    record: RecordNaming,
    rules: Sequence[ReplacementRule],
    current: PurePosixPath | None = None,
) -> PurePosixPath | Refusal:
    """Where a record would live under a root, relative to the root's folder.

    :param root: the root, its layouts and fallbacks.
    :param record: what the layouts read of the record.
    :param rules: the Location Replacements, applied to each level before it is sanitized.
    :param current: where the record is now, relative to this root's folder, when this is the root it is under: ``*``
        keeps it there rather than moving it to the root's top (#636).
    :returns: the path, one segment per level; or why the root does not take the record.
    """
    name = root.label or root.location
    template = layout_template(root, record.main_key)
    if template is None:
        return Refusal(f"{name} does not take a {record.main_key}: its layouts name no such type, and no '*'.")
    if template.strip() == KEEP_NAME:
        return PurePosixPath(record.folder_name) if current is None else current
    pattern = LocationPattern(template, record.placeholders)
    if pattern.problem:
        return Refusal(f"{name}'s layout for a {record.main_key} cannot be used: {pattern.problem}")
    missing = pattern.missing(record.values, root.fallbacks)
    if missing:
        return Refusal(f"The record has no {', '.join(missing)}, and {name} names no fallback for it.")
    held = {key: value.replace(LEVEL_SEPARATOR, SEPARATOR_STAND_IN) for key, value in record.values.items()}
    held_fallbacks = {key: value.replace(LEVEL_SEPARATOR, SEPARATOR_STAND_IN) for key, value in root.fallbacks.items()}
    segments: list[str] = []
    for raw in pattern.render(held, held_fallbacks).split(LEVEL_SEPARATOR):
        segment = sanitize_name(apply_location_replacements(raw.replace(SEPARATOR_STAND_IN, LEVEL_SEPARATOR), rules))
        if segment is None:
            return Refusal(f"{name}'s layout for a {record.main_key} renders a folder with no name.")
        segments.append(segment)
    return PurePosixPath(*segments)
