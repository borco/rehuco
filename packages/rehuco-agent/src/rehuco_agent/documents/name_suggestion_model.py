"""The rename-suggestion **compute** role, extracted out of `RehuDocumentModel`
([[plugins#field-toolkit]], §13.2.1, #46): the source `PathField` displays and the view-model's
`rename_location` ultimately executes.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Final
from uuid import UUID

from borco_pyside.core import SimpleProperty
from PySide6.QtCore import QObject, Signal
from rehuco_core import (
    MappedRoot,
    RecordNaming,
    Refusal,
    apply_location_replacements,
    destination,
    is_directory_scoped,
    known_placeholders_for,
    layout_template,
    location_values,
    path_key,
    render_location_pattern,
)

from ..settings.location_replacements_settings import shared_location_replacements_settings
from ..settings.location_templates_settings import shared_location_templates_settings
from .catalog_roots import CatalogRoots
from .rehu_document_model import RehuDocumentModel

NAME_SUGGESTION_SOURCE_FIELDS: Final = ("title", "authors", "publisher", "released", "advertised_count")
"""The fields a pattern from `LocationTemplatesSettings` interpolates; a change to any of them re-emits
:attr:`NameSuggestionModel.changed` so a `PathField` re-pulls the suggestions live."""

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
    """

    label: str
    relative: PurePosixPath
    root: Path
    root_id: UUID
    here: bool
    source_root: Path | None
    source_root_id: UUID | None
    template: str = ""

    @property
    def same_root(self) -> bool:
        """Whether the place is in the root the record is under now."""
        return self.root_id == self.source_root_id

    @property
    def into(self) -> Path:
        """The folder the record's own entry -- its folder, or its file set -- lands in."""
        return self.root.joinpath(*self.relative.parts[:-1])

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
    each root's layout puts the record, the root holding it first, then every other this machine maps and reaches, in
    the catalog's order. Only a place that can be built is offered -- a root this machine does not reach, and one whose
    layout does not take the record's type or needs a field the record leaves empty with no fallback, offer none. A
    record under no root is offered every root's place; one under a root that cannot be reached now, none. A ``*``
    layout keeps the record where it is under its own root (#636), at that root's top under any other.

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
    (:data:`NAME_SUGGESTION_SOURCE_FIELDS`, the document's type or path, the Locations settings, or the catalog's
    roots), so a `PathField` can re-pull them live."""

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
        for name in NAME_SUGGESTION_SOURCE_FIELDS:
            signal_name = SimpleProperty.notify_signal_name(type(model), name)
            getattr(model, signal_name).connect(self.__on_source_field_changed)
        model.resource_type_changed.connect(self.changed)  # type: ignore[attr-defined]
        model.path_changed.connect(self.__on_source_field_changed)  # type: ignore[attr-defined]
        shared_location_templates_settings().patterns_changed.connect(self.changed)
        shared_location_replacements_settings().rules_changed.connect(self.changed)
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
        values = location_values(model.title, model.publisher, model.authors, model.released, model.advertised_count)
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
        return list(dict.fromkeys(name for name in rendered if name))

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
            current = None if root is not own else PurePosixPath(*folder.parts[len(root.path.parts) :], current_name)
            relative = destination(root, naming, rules, current)
            if isinstance(relative, Refusal):
                continue
            here = path_key(root.path.joinpath(*relative.parts)) == path_key(folder / current_name)
            places.append(
                RootDestination(
                    root.label or root.location,
                    relative,
                    root.path,
                    root.root_id,
                    here,
                    None if own is None else own.path,
                    None if own is None else own.root_id,
                    (layout_template(root, naming.main_key) or "").strip(),
                )
            )
        return tuple(places)

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

    def __on_source_field_changed(self) -> None:
        """Announce that a field the suggestions are built from changed.

        A bound method rather than a lambda, so Qt drops the model's connections to it when this object
        is destroyed -- the model may outlive the view this serves (#375). Takes no arguments: Qt lets a
        slot accept fewer than the notify signal emits.
        """
        self.changed.emit()
