"""Which folders of a root its layouts bucket, found by the records that sit in them
([[mounts-and-storage#bucket-rebalance]], #681).

A template cannot say it: ``{publisher}/{buckets}/{title}`` fits another layout's publishers as well, and a record's own
folder. So a folder counts only when a record of the catalog's cache sits at the place its own type's layout gives it
there, under any chain of its buckets -- the rule the path row tells *already there* by
(:func:`~rehuco_core.place_holds`).

The other way round, :class:`BucketRules` says which of the split folders the disk holds
(:func:`~rehuco_core.split_folders`) **no layout buckets any more**, because its rule was removed: those a balance
joins whole. Pure: no disk.
"""

from collections.abc import Iterable, Iterator, Sequence
from enum import Enum, auto
from pathlib import Path, PurePosixPath
from typing import Final

from .path_keys import path_key
from .plugins import DEFAULT_PLUGIN_REGISTRY, PluginRegistry
from .prefix_buckets import place_chains
from .rehudb import CatalogRecord
from .replacement_rule import ReplacementRule
from .resource_scoping import is_directory_scoped
from .root_destination import (
    LaidOutRoot,
    Placement,
    RecordNaming,
    Refusal,
    destination,
    has_bucketed_layout,
    is_bucketed_template,
    layout_placeholders,
    layout_template_problem,
    layout_templates,
)


def record_levels(record: CatalogRecord) -> tuple[str, ...]:
    """A record's own entry as levels under its root: its folder for a folder record, its stem for a file record.

    :param record: the record.
    :returns: the levels; none for a record describing the root's own folder.
    """
    path = PurePosixPath(record.path)
    return path.parent.parts if is_directory_scoped(Path(record.path)) else (*path.parent.parts, path.stem)


def bucketed_places(
    records: Iterable[CatalogRecord], root: LaidOutRoot, rules: Sequence[ReplacementRule]
) -> Iterator[tuple[tuple[str, ...], Placement]]:
    """Every bucketed place a root's layouts give its records.

    :param records: the root's records, as the cache has them.
    :param root: the root, its layouts and fallbacks.
    :param rules: the Location Replacements.
    :yields: a record's levels, and one place of it.
    """
    bucketed_templates: dict[str, tuple[str, ...]] = {}
    for record in records:
        levels = record_levels(record)
        if not levels or record.error is not None:
            continue
        naming = RecordNaming.of_record(record, levels[-1])
        templates = bucketed_templates.get(naming.main_key)
        if templates is None:
            templates = tuple(filter(is_bucketed_template, layout_templates(root, naming.main_key)))
            bucketed_templates[naming.main_key] = templates
        for template in templates:
            place = destination(root, template, naming, rules)
            if not isinstance(place, Refusal):
                yield levels, place


def bucketed_folders(
    records: Iterable[CatalogRecord], root: LaidOutRoot, rules: Sequence[ReplacementRule]
) -> tuple[PurePosixPath, ...]:
    """The folders of a root that hold a bucketed level, each relative to the root -- the folder of the level before
    ``{buckets}``, the root's own when there is none.

    :param records: the root's records, as the cache has them.
    :param root: the root, its layouts and fallbacks.
    :param rules: the Location Replacements.
    :returns: the folders, the deepest first: the order they are rebalanced in, since an outer one's step moves the
        inner ones whole.
    """
    found: dict[str, PurePosixPath] = {}
    for levels, place in bucketed_places(records, root, rules):
        for chain in place_chains(levels, place.relative, place.bucketed) or ():
            found.setdefault(path_key(str(chain.folder)), chain.folder)
    return tuple(sorted(found.values(), key=lambda folder: (-len(folder.parts), folder)))


class Bucketing(Enum):
    """Whether a root's layouts bucket a folder that is split."""

    GOVERNED = auto()
    """One does: a record has its bucketed place there."""

    UNGOVERNED = auto()
    """None does any more."""

    UNKNOWN = auto()
    """Nothing says: a layout cannot be used, or some layout has buckets and the cache knows no record beneath the
    folder."""


class BucketRules:
    """What a root's layouts bucket, by the records the cache holds of it (#681).

    A folder counts as governed wherever a record's bucketed place leads into it, whether or not the record sits there:
    a library whose records all drifted from their places is still the library its layout buckets. **No folder is called
    ungoverned by mistake**: a template that cannot be used may be a mistyped ``{buckets}``, so a root with one has
    none; nor has a root with buckets that no scan has read, of which the cache may know one record astray.

    :param records: the root's records, as the cache has them.
    :param root: the root, its layouts and fallbacks.
    :param rules: the Location Replacements.
    :param split: the split folders, relative to the root: what a folder of buckets on the way to another is one of.
    :param scanned: whether a scan has read the root.
    :param plugins: the plugins, which say what a type's templates may name.
    """

    def __init__(  # pylint: disable=too-many-arguments
        self,
        records: Sequence[CatalogRecord],
        root: LaidOutRoot,
        rules: Sequence[ReplacementRule],
        *,
        split: Iterable[PurePosixPath] = (),
        scanned: bool = True,
        plugins: PluginRegistry = DEFAULT_PLUGIN_REGISTRY,
    ) -> None:
        self.__usable: Final = not any(
            layout_template_problem(template, layout_placeholders(main_key, plugins))
            for main_key, templates in root.layouts.items()
            for template in templates
        )
        self.__scanned: Final = scanned
        self.__split: Final = {path_key(str(folder)) for folder in split}
        self.__bucketed: Final = has_bucketed_layout(root.layouts)
        # a record that could not be read has no place, so it says nothing of the folders above it
        self.__levels: Final = tuple(
            tuple(map(path_key, record_levels(record))) for record in records if record.error is None
        )
        self.__folders: Final = {
            PurePosixPath(*place.relative.parts[:index])
            for _levels, place in bucketed_places(records, root, rules)
            for index in place.bucketed
        }
        """Each folder a place buckets, without the buckets on the way to it."""

    def of(self, folder: PurePosixPath) -> Bucketing:
        """Whether the layouts bucket a split folder.

        :param folder: the folder, relative to the root.
        :returns: whether one does.
        """
        if self.governs(folder):
            return Bucketing.GOVERNED
        if not self.__usable:
            return Bucketing.UNKNOWN
        if not self.__bucketed:
            return Bucketing.UNGOVERNED
        own = tuple(map(path_key, folder.parts))
        known = any(levels[: len(own)] == own and len(levels) > len(own) for levels in self.__levels)
        return Bucketing.UNGOVERNED if known and self.__scanned else Bucketing.UNKNOWN

    def governs(self, folder: PurePosixPath) -> bool:
        """Whether a record's bucketed place leads into a folder.

        :param folder: the folder, relative to the root.
        :returns: whether one does.
        """
        return any(self.__leads_into(place, folder) for place in self.__folders)

    def __leads_into(self, place: PurePosixPath, folder: PurePosixPath) -> bool:
        """Whether a folder is one a place buckets, with the buckets an outer level put it in, or has no more, at any of
        its levels.

        :param place: the folder a place buckets, without the buckets on the way to it.
        :param folder: the folder.
        :returns: whether it is that one.
        """
        chains = place_chains(folder.parts, place, range(len(place.parts)))
        return chains is not None and all(
            not chain.chain or path_key(str(chain.folder)) in self.__split for chain in chains
        )
