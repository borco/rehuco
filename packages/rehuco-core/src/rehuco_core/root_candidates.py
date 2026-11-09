"""What a list of picked paths would add to a catalog as roots -- the plan the Add Roots dialog shows before anything
is written ([[mounts-and-storage#rehuroot]], #578).

A pick is an existing ``.rehuroot``, which joins the catalog with its own label, location, layouts and fallbacks, or
a folder, which becomes a new ``.rehuroot``. :meth:`RootPlanner.plan` reads every picked root file, resolves every
location and compares every folder with the catalog's roots and with each other through their links, so it **may
block** on a share and is never run on a GUI thread. It writes nothing.
"""

import os
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from uuid import UUID, uuid4

from .path_keys import path_key
from .rehuco_file import DEFAULT_ROOT_FILE_STEM, RehucoFile
from .rehuroot_file import REHUROOT_SUFFIX, RehurootFile, RehurootFileError
from .root_location import location_of, resolve_location
from .root_mappings import MappedRoot
from .root_overlap import RootOverlap
from .sanitized_names import location_stem

ALREADY_A_ROOT = "Already a root of this catalog."
"""Why a pick whose location the catalog already lists cannot be added."""

SAME_ROOT_ABOVE = "The same root as a line above: this catalog would list it twice."
"""Why a root file carrying the id of one picked before it cannot be added."""

SAME_LOCATION_ABOVE = "The same location as a line above: this catalog would list it twice."
"""Why a pick at the location of one picked before it cannot be added."""


class CandidateKind(StrEnum):
    """What a picked path is."""

    FILE = "file"
    """An existing ``.rehuroot``, which joins the catalog as it is."""

    FOLDER = "folder"
    """A folder, which becomes a new ``.rehuroot``."""


@dataclass(frozen=True, slots=True)
class RootPick:
    """One path picked to become a root, with what the user typed for it.

    :param path: the ``.rehuroot`` or the folder, as picked.
    :param label: a folder's label as typed; ``None`` or empty takes the folder's name. Ignored for a ``.rehuroot``.
    :param root_file: where a folder's new ``.rehuroot`` goes, as typed; ``None`` names it after the folder's location
        (:func:`~rehuco_core.sanitized_names.location_stem`), beside the ``.rehuco``. Ignored for a ``.rehuroot``.
    """

    path: Path
    label: str | None = None
    root_file: Path | None = None


# a value: one line of the plan, each field shown or used by the add
@dataclass(frozen=True, slots=True)
class RootCandidate:  # pylint: disable=too-many-instance-attributes
    """One pick, as it would join the catalog.

    :param pick: the pick it comes from.
    :param kind: an existing root file, or a folder.
    :param label: the root's label: the file's, or the one a folder gets.
    :param location: where the root is, spelled the same on every machine; empty for a file that cannot be read.
    :param root_file: the ``.rehuroot``: the one picked, or where a folder's new one goes.
    :param folder: where the root is on this machine -- the folder picked, or where a file's location resolves;
        ``None`` for a file this machine cannot resolve, which joins unmapped.
    :param layouts: a file's layouts; for a folder, empty as planned -- the caller fills in the ones chosen for it
        before the line is added.
    :param fallbacks: a file's fallbacks; for a folder, likewise.
    :param problem: why it cannot be added; ``""`` when it can.
    :param root: a file as read, which the add takes as it is, reading nothing again; ``None`` for a folder or a
        file that could not be read.
    """

    pick: RootPick
    kind: CandidateKind
    label: str
    location: str
    root_file: Path
    folder: Path | None
    layouts: dict[str, str] = field(default_factory=dict)
    fallbacks: dict[str, str] = field(default_factory=dict)
    problem: str = ""
    root: RehurootFile | None = field(default=None, compare=False)

    @property
    def addable(self) -> bool:
        """Whether OK adds it."""
        return not self.problem


# a namespace for plan() and the private steps it takes, which a module could not keep private
class RootPlanner:  # pylint: disable=too-few-public-methods
    """Plans what picks would add to a catalog; :meth:`plan` is the one entry."""

    @staticmethod
    def plan(
        file: RehucoFile, picks: Sequence[RootPick], mapped: Sequence[MappedRoot], unreachable: Collection[UUID] = ()
    ) -> tuple[RootCandidate, ...]:
        """What each pick would add, in order -- **may block**, so never on a GUI thread.

        A folder that a picked ``.rehuroot`` resolves to is the same root twice: only the file is kept, whichever was
        picked first. Every other pick gets a line, one that cannot be added saying why: a file that cannot be read
        or that the catalog already lists, a location already a root, a folder that overlaps a root or a line before
        it, a root file already there.

        :param file: the catalog the roots would join; it must have been saved, so its folder is known.
        :param picks: the paths picked, in the order they were.
        :param mapped: the catalog's roots this machine reaches.
        :param unreachable: the ids of roots known unreachable, which a comparison through links does not wait on.
        :returns: one candidate per pick kept, in the picks' order.
        :raises ValueError: the catalog was never saved.
        """
        planned = [RootPlanner.__plan_one(file, pick) for pick in picks]
        resolved = {path_key(line.folder) for line in planned if line.kind is CandidateKind.FILE and line.folder}
        kept = [line for line in planned if line.kind is CandidateKind.FILE or path_key(line.pick.path) not in resolved]
        return tuple(RootPlanner.__judge(file, kept, mapped, unreachable))

    @staticmethod
    def __plan_one(file: RehucoFile, pick: RootPick) -> RootCandidate:
        """One pick, read and resolved, its own problems found; a folder's root file is left to :meth:`__judge`.

        :param file: the catalog.
        :param pick: the pick.
        :returns: its line.
        """
        if pick.path.suffix.casefold() == REHUROOT_SUFFIX:
            return RootPlanner.__plan_file(file, pick)
        location = location_of(pick.path)
        label = pick.label if pick.label else RehucoFile.default_label(pick.path)
        problem = "" if pick.path.is_dir() else f"Not a folder: {pick.path}"
        if not problem and RootPlanner.__listed_location(file, location):
            problem = ALREADY_A_ROOT
        return RootCandidate(pick, CandidateKind.FOLDER, label, location, Path(), pick.path, problem=problem)

    @staticmethod
    def __plan_file(file: RehucoFile, pick: RootPick) -> RootCandidate:
        """An existing ``.rehuroot``, read and resolved.

        :param file: the catalog.
        :param pick: the pick naming the file.
        :returns: its line; one that cannot be read, or whose root the catalog already has, says so.
        """
        path = Path(os.path.normpath(pick.path))
        try:
            root = RehurootFile.load(path)
        except (OSError, RehurootFileError) as error:
            problem = f"The root file cannot be read: {error}"
            return RootCandidate(pick, CandidateKind.FILE, path.stem, "", path, None, problem=problem)
        problem = ""
        if any(listed.file is not None and path_key(listed.file) == path_key(path) for listed in file.roots):
            problem = "This catalog already lists this root file."
        elif any(listed.root_id == root.root_id for listed in file.roots):
            problem = "This catalog already lists this root, through another root file."
        elif RootPlanner.__listed_location(file, root.location):
            problem = ALREADY_A_ROOT
        folder = resolve_location(root.location)
        return RootCandidate(
            pick,
            CandidateKind.FILE,
            root.label,
            root.location,
            path,
            folder,
            dict(root.layouts),
            dict(root.fallbacks),
            problem,
            root,
        )

    @staticmethod
    def __listed_location(file: RehucoFile, location: str) -> bool:
        """Whether a readable root of the catalog is already at a location, in any case.

        :param file: the catalog.
        :param location: the location.
        :returns: whether one is.
        """
        folded = location.casefold()
        return any(root.readable and root.location.casefold() == folded for root in file.roots)

    @staticmethod
    def __judge(
        file: RehucoFile, lines: Sequence[RootCandidate], mapped: Sequence[MappedRoot], unreachable: Collection[UUID]
    ) -> list[RootCandidate]:
        """Give each folder its root file, and refuse a line that is the root of a line before it -- the same id, or
        the same location -- or overlaps a root or a line before it, through links too, or whose root file is taken.

        :param file: the catalog.
        :param lines: the lines kept, in order.
        :param mapped: the catalog's roots this machine reaches.
        :param unreachable: the roots not to resolve.
        :returns: the lines, judged.
        """
        judged: list[RootCandidate] = []
        roots = list(mapped)
        taken: list[Path] = []
        ids: set[UUID] = set()
        locations: set[str] = set()
        for planned in lines:
            line = planned
            if line.kind is CandidateKind.FOLDER:
                line = RootPlanner.__with_root_file(file, line, taken)
            if line.addable and line.root is not None and line.root.root_id in ids:
                line = replace(line, problem=SAME_ROOT_ABOVE)
            if line.addable and line.location.casefold() in locations:
                line = replace(line, problem=SAME_LOCATION_ABOVE)
            if line.addable and line.folder is not None:
                overlap = RootOverlap.find(line.folder, roots) or RootOverlap.find_resolved(
                    line.folder, roots, unreachable
                )
                if overlap is not None:
                    line = replace(line, problem=overlap.message)
            if line.addable:
                taken.append(line.root_file)
                locations.add(line.location.casefold())
                if line.root is not None:
                    ids.add(line.root.root_id)
                if line.folder is not None:
                    roots.append(MappedRoot(uuid4(), line.label, line.location, line.folder))
            judged.append(line)
        return judged

    @staticmethod
    def __with_root_file(file: RehucoFile, line: RootCandidate, taken: Sequence[Path]) -> RootCandidate:
        """A folder's line with the root file it would get: the one typed -- refused when it is no ``.rehuroot``, or
        when a file, a root of the catalog or a line before has it -- or one named after its location, free of all
        three.

        :param file: the catalog.
        :param line: the folder's line.
        :param taken: the root files of the lines before it.
        :returns: the line.
        """
        chosen = line.pick.root_file
        if chosen is None:
            stem = location_stem(line.location) or DEFAULT_ROOT_FILE_STEM
            return replace(line, root_file=file.free_root_file(stem, taken))
        if not chosen.is_absolute() and file.path is not None:
            # a bare name is meant beside the .rehuco, never wherever the process happens to run
            chosen = file.path.parent / chosen
        chosen = Path(os.path.normpath(chosen))
        line = replace(line, root_file=chosen)
        if not line.addable:
            return line
        if chosen.suffix.casefold() != REHUROOT_SUFFIX:
            return replace(line, problem=f"A root file ends in {REHUROOT_SUFFIX}: {chosen}")
        keys = {path_key(path) for path in taken} | {path_key(root.file) for root in file.roots if root.file}
        if path_key(chosen) in keys or chosen.exists():
            return replace(line, problem=f"A root file is already there: {chosen}")
        return line
