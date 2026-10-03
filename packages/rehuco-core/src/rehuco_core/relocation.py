"""Where paths went once a rename ran -- the executed plan, seen from the outside (#241, #376).

A rename moves files out from under everyone holding their paths: a job reading a resource, a cache row, an
open document, a listing on screen. Rather than each holder guessing what the rename must have done, the
rename hands them **the plan it actually executed**, and each applies one rule to everything it holds
([[mounts-and-storage#out-of-band]]).
"""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Relocation:
    """The ``(source, destination)`` pairs one rename carried out, and the rule that reads them back.

    Both resource scopes ([[data-model#resource-scoping]]) are one rule -- **a path at or beneath a renamed
    source lands at the same offset beneath its destination**. For a file-scoped resource every source is a
    file, so nothing is ever beneath one and the rule degenerates to exact matching against its sibling set;
    for a directory-scoped one the single source is the directory, so the whole subtree rebases without any of
    it ever being enumerated -- a record nested in a renamed collection folder included.

    Comparison folds case exactly where the filesystem does, through :func:`os.path.normcase` -- the rule the
    rename itself uses to decide whether two paths name the same file -- and the unmoved tail is taken from the
    candidate's **own** parts, so a differently-cased ancestor relocates without rewriting how the rest of the
    name is spelled.

    An empty relocation moves nothing: it is what a rename that did not happen -- a no-op, or one rolled back
    -- answers with.

    :param pairs: the executed renames, in the order they ran.
    """

    pairs: tuple[tuple[Path, Path], ...] = ()

    def relocate(self, candidate: Path) -> Path:
        """Where ``candidate`` ended up once the rename ran, or ``candidate`` itself if it did not move.

        :param candidate: any path -- a job's content file, a record, a listing's row, the ``.rehu`` itself.
        :returns: the path ``candidate`` now has, or ``candidate`` unchanged when the rename did not move it.
        """
        candidate_parts = Relocation.path_parts(candidate)
        for source, destination in self.pairs:
            source_parts = Relocation.path_parts(source)
            if candidate_parts == source_parts:
                return destination
            if candidate_parts[: len(source_parts)] == source_parts:
                return destination.joinpath(*candidate.parts[len(source_parts) :])
        return candidate

    def touches(self, directory: Path) -> bool:
        """Whether the rename moved ``directory`` itself, something above it, or anything at or beneath it --
        what a listing of ``directory``'s subtree asks before reading it again.

        Both ends of a pair count, in both directions: a file renamed *into* the subtree appears in it as
        surely as one renamed out of it disappears, and a folder beneath a destination is one that just
        arrived -- which is where a holder that has already followed the rename (an open document re-pointed
        by its registry) asks from.

        :param directory: the folder whose subtree is in question.
        :returns: whether ``directory`` is at or beneath either end of a pair, or either end is at or beneath
            ``directory``.
        """
        directory_parts = Relocation.path_parts(directory)
        for pair in self.pairs:
            for end in map(Relocation.path_parts, pair):
                if directory_parts[: len(end)] == end or end[: len(directory_parts)] == directory_parts:
                    return True
        return False

    @staticmethod
    def path_parts(path: Path) -> tuple[str, ...]:
        """``path`` split into components, each normalized the way this filesystem normalizes a name.

        :func:`os.path.normcase` does the normalizing -- folding case on Windows and rewriting separators
        there, identity on POSIX -- so two paths that name the same thing come out equal and two that do not,
        do not.

        Split into components rather than left as one normalized string so that a prefix test cannot mistake
        a *sibling whose name merely starts alike* for something inside a directory -- ``/lib/folder2`` starts
        with ``/lib/folder`` as text and is not beneath it as a path.

        :param path: the path to normalize.
        :returns: its normalized components.
        """
        return tuple(os.path.normcase(part) for part in path.parts)
