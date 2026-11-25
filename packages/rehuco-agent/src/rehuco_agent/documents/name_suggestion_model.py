"""The rename-suggestion **compute** role, extracted out of `RehuDocumentModel`
([[plugins#field-toolkit]], §13.2.1, #46): the source `PathField` displays and the view-model's
`rename_location` ultimately executes.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Final, cast
from uuid import UUID

from borco_pyside.core import SimpleProperty
from PySide6.QtCore import QObject, Signal
from rehuco_core import (
    MappedRoot,
    Placement,
    RecordNaming,
    Refusal,
    apply_location_replacements,
    destinations,
    is_bucket_chain,
    is_bucketed_template,
    is_directory_scoped,
    is_split,
    known_placeholders_for,
    layout_templates,
    location_name_problem,
    location_values,
    path_key,
    place_holds,
    render_location_pattern,
    resolve_buckets,
    shown_place,
    temporary_prefix,
    ungoverned_reason,
)

from ..settings.location_replacements_settings import shared_location_replacements_settings
from ..settings.location_templates_settings import shared_location_templates_settings
from ..settings.move_settings import shared_move_settings
from .catalog_roots import CatalogRoots
from .rehu_document_model import RehuDocumentModel

NAME_SUGGESTION_SOURCE_FIELDS: Final = ("title", "authors", "publisher", "released", "advertised_count")
"""The fields a pattern from `LocationTemplatesSettings` interpolates; a change to any of them re-emits
:attr:`NameSuggestionModel.changed` so a `PathField` re-pulls the suggestions live. The primary source's ``site_id``
is one more, with no property of its own: the model follows it through the sources."""

FALLBACK_RESOURCE_TYPE: Final = "tutorial"
"""What a foreign or typeless document's suggestions fall back to (#322): a type no installed plugin here
claims still gets a usable list rather than an empty one."""


@dataclass(frozen=True, slots=True)
class RootDestination:  # pylint: disable=too-many-instance-attributes
    """Where a root's layout puts the record (#579, #339): one place the path row offers under its names.

    :param label: the root's name, its location when it has none.
    :param relative: the place, relative to the root's folder, one segment per level.
    :param root: the root's folder on this machine.
    :param root_id: the root.
    :param here: whether the record already sits there.
    :param source_root: the folder of the root the record is under now, or ``None`` for a record under no root.
    :param source_root_id: that root, or ``None``.
    :param template: the path template that rendered the place, ``*`` included; empty for the root itself (#639).
    :param bucketed: the indices of the levels of ``relative`` put in prefix buckets, not read off the disk (#680); none
        for a place with no buckets, or one with its buckets read (:meth:`NameSuggestionModel.resolved`).
    :param blocked: why nothing may be put there, once its buckets are read: its path leads into a folder split where
        its template has no ``{buckets}`` (#681); empty when something may.
    """

    label: str
    relative: PurePosixPath
    root: Path
    root_id: UUID
    here: bool
    source_root: Path | None
    source_root_id: UUID | None
    template: str = ""
    bucketed: tuple[int, ...] = ()
    blocked: str = ""

    @property
    def same_root(self) -> bool:
        """Whether the place is in the root the record is under now."""
        return self.root_id == self.source_root_id

    @property
    def into(self) -> Path:
        """The folder the record's own entry -- its folder, or its file set -- lands in; for a bucketed place, that
        folder without its buckets."""
        return self.root.joinpath(*self.relative.parts[:-1])

    @property
    def shown(self) -> PurePosixPath:
        """The place as the path row draws it: its buckets as an ellipsis while not read (#680), and a temporary bucket
        as the one it is being built for."""
        shown = shown_place(self.relative, self.bucketed)
        return PurePosixPath(*(temporary_prefix(level) or level for level in shown.parts))

    @property
    def name(self) -> str:
        """The name the record's own entry takes there."""
        return self.relative.name


class NameSuggestionModel(QObject):
    """Builds rename-candidate names from a `RehuDocumentModel`'s record fields ([[plugins#field-toolkit]]).

    Subscribes to :data:`NAME_SUGGESTION_SOURCE_FIELDS`' notify signals on ``model``, to
    ``model.resource_type_changed``, to `LocationTemplatesSettings.patterns_changed`, and to
    `LocationReplacementsSettings.rules_changed` (#350), so :attr:`changed` fires whenever a field
    :meth:`suggestions` is built from changes -- editing ``authors``, switching the document's type, or
    applying a Locations or Location Replacements settings page all update the offered names without a
    reopen (#322). This is the **compute** role in the field toolkit's
    compute/present-command/execute split (§13.2.1): a `PathField` presents :meth:`suggestions` and
    forwards a clicked one as a command, and ``model.rename_location`` executes it -- this class
    never touches the filesystem.

    **The roots' places** (#579, #339), :meth:`root_destinations`, are the second group the path row offers: where
    each root's layout puts the record -- one place for each of its templates that renders, in row order, a place two
    render once (#638) -- the root holding it first, then every other this machine maps and reaches, in
    the catalog's order. Only a place that can be built is offered -- a root this machine does not reach, and one whose
    layout does not take the record's type or needs a field the record leaves empty with no fallback, offer none. A
    record under no root is offered every root's place; one under a root that cannot be reached now, none. A ``*``
    layout keeps the record's folder name, at the root's top, under its own root too (#643). **The place the record
    sits at** is a row of its own, first and ``here``, whenever its own root's layout puts it somewhere else or
    refuses it.

    **A bucketed place** (#680) is offered without its buckets, and the record sits there when its folders are the
    place's with any chain of its buckets at each bucketed level; nothing is read to tell. A move reads the buckets
    itself as it starts; :meth:`resolved` reads them for the row to be drawn by (#681). Where the record's own name is
    bucketed (:meth:`bucket_place`), a rename moves it to its new name's bucket.

    **A record that is its root's folder** (``<root>/info.rehu``, #641) is not moved or renamed from here: its own
    root is the one place offered, by the root's label alone and already there, no other root offers one, and no name
    is suggested -- a rename would rename the root's folder, a move put a whole root inside another.

    :param model: the record fields (``title`` / ``publisher`` / ``authors`` / ``released`` / ``advertised_count`` /
        ``resource_type``) to build suggestions from.
    :param catalog_roots: the open catalog's roots, for :meth:`root_destinations`; ``None`` offers no root's place.
    :param parent: optional Qt parent; the caller parents this to the view it serves, which the model
        may outlive (#375) -- every subscription here is severed when this object is destroyed.
    """

    changed = Signal()
    """Fires when a field :meth:`suggestions` or :meth:`root_destinations` is built from changes
    (:data:`NAME_SUGGESTION_SOURCE_FIELDS`, the document's type or path, the Locations or move settings, or the
    catalog's roots), so a `PathField` can re-pull them live."""

    def __init__(
        self, model: RehuDocumentModel, catalog_roots: CatalogRoots | None = None, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self.__model: Final = model
        self.__catalog_roots: Final = catalog_roots
        self.__unreachable: frozenset[UUID] | None = None
        """The roots that cannot be reached, as last asked; ``None`` until asked, and again once the catalog says its
        roots or their reach changed. Kept because asking reads the cache (~2 ms), and the place is asked for on every
        keystroke in a field it is built from."""
        self.__site_id = model.document.site_id
        """The primary source's site id as last announced: the sources change with every edit of a title or a
        publisher too, which those fields announce themselves."""
        model.sources_changed.connect(self.__on_sources_changed)  # type: ignore[attr-defined]
        for name in NAME_SUGGESTION_SOURCE_FIELDS:
            signal_name = SimpleProperty.notify_signal_name(type(model), name)
            getattr(model, signal_name).connect(self.__on_source_field_changed)
        model.resource_type_changed.connect(self.changed)  # type: ignore[attr-defined]
        model.path_changed.connect(self.__on_source_field_changed)  # type: ignore[attr-defined]
        shared_location_templates_settings().patterns_changed.connect(self.changed)
        shared_location_replacements_settings().rules_changed.connect(self.changed)
        shared_move_settings().changed.connect(self.changed)  # the places' verified marker reads it (#649)
        if catalog_roots is not None:
            catalog_roots.roots_changed.connect(self.__on_roots_changed)
            catalog_roots.root_reachable.connect(self.__on_roots_changed)

    def suggestions(self) -> list[str]:
        """Build the rename-candidate names via this document type's `LocationTemplatesSettings` list.

        Interpolated from ``title`` / ``publisher`` / joined ``authors`` / the released ``year`` / the
        advertised ``count``, then run through `LocationReplacementsSettings.rules` (#350) -- but still
        unsanitized; the `PathField` editor transliterates and filesystem-sanitizes them before display,
        and drops any that reduce to nothing. ``released`` may be ``None`` (absent,
        [[field-schema#deferred-items]]) -- the year is empty then, same as for a too-short ``released``
        string, and a pattern's ``{{ [{year}]}}`` group drops out with it.

        Two patterns rendering the same name are **merged** here, where the names are computed: a
        title-only record renders every shipped default to the bare title, which is one suggestion,
        not four. A pattern rendering to nothing at all is dropped for the same reason.

        ``count`` is always in ``values`` -- the model carries `~RehuDocumentModel.advertised_count`
        whatever the type -- but only a type declaring it (ReferenceImages, #349) has it among its
        :func:`~rehuco_core.known_placeholders_for`, so a pattern
        naming ``{count}`` never reaches here for any other type.

        A record that is its root's folder (:meth:`is_root_folder`, #641) is suggested no name.

        :returns: the distinct candidate strings, in the order their patterns first produced them.
        """
        model = self.__model
        if self.is_root_folder():
            return []
        values = location_values(
            model.title,
            model.publisher,
            model.authors,
            model.released,
            model.advertised_count,
            site_id=model.document.site_id,
        )
        plugins = self.__model.document.plugins
        main_key = plugins.main_key(self.__model.resource_type)
        if main_key not in plugins:
            main_key = FALLBACK_RESOURCE_TYPE
        known_placeholders = known_placeholders_for(plugins.field_names(main_key))
        patterns = shared_location_templates_settings().patterns_for(main_key, known_placeholders)
        rules = shared_location_replacements_settings().rules
        rendered = (
            apply_location_replacements(render_location_pattern(pattern, values, known_placeholders), rules)
            for pattern in patterns
        )
        # a name starting with a dot is never made (#680): not offered, rather than refused once clicked
        return list(dict.fromkeys(name for name in rendered if name and not location_name_problem(name.strip())))

    def bucket_place(self, name: str) -> RootDestination | None:
        """Where a rename moves the record whose name is bucketed where it sits under its own root (#680): the bucket of
        its new name, not beside the buckets of its old one -- whether its fields still render the name it has or were
        edited first, which is what a rename is mostly for (#681). A record no template's place fits any more, another
        field of its path edited too, is told by the disk: it lies in the buckets of its name under a split folder, and
        stays under that folder.

        :param name: the new name.
        :returns: the place; ``None`` when the record's name is not bucketed where it sits.
        """
        home = next(
            (place for place in self.__home_places() if len(place.relative.parts) - 1 in place.bucketed),
            None,
        )
        if home is None:
            home = self.__bucket_on_disk()
        return None if home is None else replace(home, relative=home.relative.with_name(name), here=False)

    def __bucket_on_disk(self) -> RootDestination | None:
        """The place the record sits at when the folders above it are the buckets of its name under a split folder,
        whatever its fields render now.

        :returns: the place, its name bucketed under that folder; ``None`` when it lies in no bucket, or its root
            cannot be reached.
        """
        path, roots = self.__model.path, self.__catalog_roots
        own = None if path is None or roots is None else self.__root_holding(path, roots.mapped_roots())
        if own is None or not self.root_destinations():
            return None
        levels = self.__levels(own.path)
        for count in range(1, len(levels)):
            layout = levels[: len(levels) - 1 - count]
            chain = [temporary_prefix(level) or level for level in levels[len(layout) : -1]]
            if is_bucket_chain(chain, levels[-1]) and is_split(own.path.joinpath(*layout)):
                relative = PurePosixPath(*layout, levels[-1])
                return RootDestination(
                    own.label or own.location,
                    relative,
                    own.path,
                    own.root_id,
                    True,
                    own.path,
                    own.root_id,
                    "",
                    (len(layout),),
                )
        return None

    def rename_blocked(self) -> str:
        """Why the record may not be renamed (#681): it lies in a folder that is split where no template that puts it
        there has ``{buckets}``. One at no template's place is asked about only when its type's templates have none at
        all: its fields were edited past recognition, or no template takes it, and its own layout may well bucket the
        folder.

        :returns: the reason; empty when it may.
        """
        places = self.__home_places()
        if not any(place.template for place in places) and self.__buckets_its_type():
            return ""
        reasons = [self.__read(place).blocked for place in places]
        return reasons[0] if reasons and all(reasons) else ""

    def resolved(self, place: RootDestination) -> RootDestination:
        """A place with its buckets as they are on the disk now, and whether anything may be put there, for a row to be
        drawn by (#681): where the record already sits, its own folders, nothing read. A click still moves by the place
        itself, whose buckets the move reads as it starts.

        :param place: the place, as :meth:`root_destinations` offered it.
        :returns: the place, its buckets in its path; as it is when the disk could not be read.
        """
        if not place.here:
            return self.__read(place)
        if not place.relative.parts:
            return place
        return replace(place, relative=PurePosixPath(*self.__levels(place.root)), bucketed=())

    @staticmethod
    def __read(place: RootDestination) -> RootDestination:
        """A place with its buckets read off the disk.

        :param place: the place.
        :returns: the place; as it is when the disk could not be read.
        """
        if not place.root.is_dir():
            # asked once: a share that just went away would otherwise be waited for at each level
            return place
        try:
            resolved = resolve_buckets(place.root, place.relative, place.bucketed)
        except OSError:
            return place
        blocked = "" if resolved.ungoverned is None else ungoverned_reason(resolved.ungoverned)
        return replace(place, relative=resolved.relative, bucketed=(), blocked=blocked)

    def __home_places(self) -> list[RootDestination]:
        """The places under its own root the record sits at, by the name it has: one, or one per template that renders
        its folders; the one no template renders only when it is the only one.

        :returns: the places.
        """
        found = [
            place
            for place in self.root_destinations()
            if place.same_root
            and place.relative.parts
            and place_holds(
                self.__levels(place.root), place.relative.with_name(self.__model.current_name), place.bucketed
            )
        ]
        return [place for place in found if place.template] or found

    def __levels(self, root: Path) -> tuple[str, ...]:
        """The record's own entry, as levels under its root.

        :param root: the root's folder.
        :returns: the levels.
        """
        path = cast(Path, self.__model.path)  # a record with no path has no places
        folder = path.parent.parent if is_directory_scoped(path) else path.parent
        return (*folder.parts, self.__model.current_name)[len(root.parts) :]

    def __buckets_its_type(self) -> bool:
        """Whether a template the record's own root has for its type has ``{buckets}``.

        :returns: whether one has.
        """
        path, roots = self.__model.path, self.__catalog_roots
        own = None if path is None or roots is None else self.__root_holding(path, roots.mapped_roots())
        if own is None:
            return False
        main_key = RecordNaming.of(self.__model.document, self.__model.current_name).main_key
        return any(map(is_bucketed_template, layout_templates(own, main_key)))

    def is_root_folder(self) -> bool:
        """Whether the record describes a root's own folder (``<root>/info.rehu``, #641), which no rename or move
        may touch: it would rename the root's folder, leaving the catalog and this machine's mapping on a folder that
        is gone.

        :returns: whether the record's folder is a root's folder on this machine.
        """
        path, roots = self.__model.path, self.__catalog_roots
        if path is None or roots is None:
            return False
        return self.__at_top_of(self.__root_holding(path, roots.mapped_roots()), path)

    def root_destinations(self) -> tuple[RootDestination, ...]:
        """Where each root's layout puts the record (#579, #339), rendered by :func:`~rehuco_core.destination` from the
        record's fields and the Location Replacements.

        :returns: the places, the record's own root's first; none when there is no catalog, the record has no path,
            or the root holding it cannot be reached.
        """
        roots, path = self.__catalog_roots, self.__model.path
        if roots is None or path is None:
            return ()
        if self.__unreachable is None:
            self.__unreachable = roots.unreachable_roots()
        mapped = roots.mapped_roots()
        own = self.__root_holding(path, mapped)
        if own is not None and own.root_id in self.__unreachable:
            return ()
        if own is not None and self.__at_top_of(own, path):
            return (
                RootDestination(
                    own.label or own.location, PurePosixPath(), own.path, own.root_id, True, own.path, own.root_id
                ),
            )
        others = [root for root in mapped if root is not own and root.root_id not in self.__unreachable]
        current_name = self.__model.current_name
        naming = RecordNaming.of(self.__model.document, current_name)
        rules = shared_location_replacements_settings().rules
        folder = path.parent.parent if is_directory_scoped(path) else path.parent
        places: list[RootDestination] = []
        for root in [*([own] if own is not None else []), *others]:
            offered = destinations(root, naming, rules)
            if isinstance(offered, Refusal):
                offered = ()
            here = [self.__is_here(root, place, folder / current_name, root is own) for place in offered]
            if root is own and not any(here):
                places.append(self.__current_place(root, folder, current_name))
            places.extend(
                RootDestination(
                    root.label or root.location,
                    place.relative,
                    root.path,
                    root.root_id,
                    is_here,
                    None if own is None else own.path,
                    None if own is None else own.root_id,
                    place.template,
                    place.bucketed,
                )
                for place, is_here in zip(offered, here, strict=True)
            )
        return tuple(places)

    @staticmethod
    def __is_here(root: MappedRoot, place: Placement, entry: Path, own: bool) -> bool:
        """Whether the record already sits at a place: at its path, or for a bucketed one under any chain of its
        buckets (#680), which only its own root can hold.

        :param root: the root the place is under.
        :param place: the place.
        :param entry: the record's own entry -- its folder, or its file set's name -- where it is now.
        :param own: whether ``root`` is the root holding the record.
        :returns: whether it is there.
        """
        if place.bucketed:
            levels = entry.parts[len(root.path.parts) :]
            return own and place_holds(levels, place.relative, place.bucketed)
        return path_key(root.path.joinpath(*place.relative.parts)) == path_key(entry)

    @staticmethod
    def __current_place(own: MappedRoot, folder: Path, current_name: str) -> RootDestination:
        """The place the record sits at now, under its own root (#643).

        :param own: the root holding the record.
        :param folder: the folder the record's own entry is in.
        :param current_name: the record's current file or folder name.
        :returns: that place, ``here``, its template empty: no layout rendered it.
        """
        relative = PurePosixPath(*folder.parts[len(own.path.parts) :], current_name)
        return RootDestination(own.label or own.location, relative, own.path, own.root_id, True, own.path, own.root_id)

    @staticmethod
    def __at_top_of(root: MappedRoot | None, path: Path) -> bool:
        """Whether the record's own folder is ``root``'s folder.

        :param root: the root holding the record, or ``None``.
        :param path: the record's ``.rehu``.
        :returns: whether the record is directory-scoped and sits directly in the root's folder.
        """
        return root is not None and is_directory_scoped(path) and path_key(path.parent) == path_key(root.path)

    @staticmethod
    def __root_holding(path: Path, roots: Sequence[MappedRoot]) -> MappedRoot | None:
        """The root whose folder holds ``path``; roots never overlap, so there is at most one.

        :param path: the record's ``.rehu``.
        :param roots: the roots this machine maps.
        :returns: the root, or ``None``.
        """
        for root in roots:
            depth = len(root.path.parts)
            # a root's folder is matched folding case on every OS (#629)
            beneath = tuple(map(path_key, path.parts[:depth])) == tuple(map(path_key, root.path.parts))
            if beneath and len(path.parts) > depth:
                return root
        return None

    def __on_roots_changed(self) -> None:
        """Forget which roots cannot be reached, and announce that the root's place may have changed: the catalog's
        roots changed, or one's reach did. Takes no arguments, as :meth:`__on_source_field_changed`.
        """
        self.__unreachable = None
        self.changed.emit()

    def __on_sources_changed(self) -> None:
        """Announce a primary source's ``site_id`` that changed (#680): a scrape writes it into the sources after
        every other field, so without this a place built from ``{site_id}`` was not offered until something else
        changed. Any other change of the sources is announced by the field it shows in, or changes no name.
        """
        site_id = self.__model.document.site_id
        if site_id != self.__site_id:
            self.__site_id = site_id
            self.changed.emit()

    def __on_source_field_changed(self) -> None:
        """Announce that a field the suggestions are built from changed.

        A bound method rather than a lambda, so Qt drops the model's connections to it when this object
        is destroyed -- the model may outlive the view this serves (#375). Takes no arguments: Qt lets a
        slot accept fewer than the notify signal emits.
        """
        self.changed.emit()
