"""Whether two roots of one ``.rehuco`` overlap -- one inside the other ([[multiplicity#instances]], #498).

A record must be managed by at most one root: a root inside another, or containing one, would scan its records twice
and give each two rows. This is the one place that decides overlap, for the add-time refusal, for a file opened
already nesting, and for whatever later compares roots of different catalogs (#453).

**Spelled and resolved are two separate comparisons, never mixed** (#511). The spelled one is pure string work,
normalized and case-folded where the platform folds case, and is what :meth:`RehucoFile.add_root
<rehuco_core.RehucoFile.add_root>` runs. The resolved one follows links (:func:`os.path.realpath`), so a root that is
a link into another root is caught -- but on Windows ``realpath`` also follows a mapped drive to its share
(``T:\\DATA2`` to ``\\\\Nas\\data_14t\\DATA2``) and waits out the network's timeout on an offline one (#464), so it
runs only where blocking is allowed, compares resolved with resolved alone, and nothing it resolves is ever kept: a
root stays stored and named as the user spelled it.
"""

from collections.abc import Callable, Collection, Iterator, Sequence
from dataclasses import dataclass
from os import path as os_path
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from .rehuco_file import RehucoRoot


def root_path_key(path: Path | str) -> str:
    """A root's folder as overlap compares it: normalized, and case-folded where the platform's paths are.

    :param path: the folder, as spelled.
    :returns: the key; two spellings of one folder that differ only lexically share it.
    """
    return os_path.normcase(os_path.normpath(str(path)))


@dataclass(frozen=True, slots=True)
class RootOverlap:
    """One root overlapping another.

    :param root: the root the other one overlaps, as stored.
    :param other: the overlapping folder -- a candidate root's, or another stored root's -- as spelled.
    :param encloses: whether :attr:`root` contains :attr:`other`; ``False`` when :attr:`other` contains :attr:`root`.
    """

    root: RehucoRoot
    other: Path
    encloses: bool

    @property
    def message(self) -> str:
        """The overlap in a sentence naming both folders as spelled, never a resolved form."""
        if self.encloses:
            return f"{self.other} is inside the root {self.root.label} ({self.root.path})"
        return f"{self.other} contains the root {self.root.label} ({self.root.path})"

    @staticmethod
    def find(candidate: Path | str, roots: Sequence[RehucoRoot]) -> RootOverlap | None:
        """The first root a candidate folder overlaps, compared as spelled -- pure, touching no disk.

        The same folder is not an overlap: that is a duplicate, which :meth:`RehucoFile.add_root
        <rehuco_core.RehucoFile.add_root>` refuses on its own.

        :param candidate: the folder.
        :param roots: the roots to compare it with.
        :returns: the overlap, or ``None`` when the candidate is inside none of them and contains none.
        """
        key = root_path_key(candidate)
        for root in roots:
            encloses = RootOverlap.__relation(root_path_key(root.path), key)
            if encloses is not None:
                return RootOverlap(root, Path(candidate), encloses)
        return None

    @staticmethod
    def find_resolved(
        candidate: Path | str, roots: Sequence[RehucoRoot], skip: Collection[UUID] = ()
    ) -> RootOverlap | None:
        """The first root a candidate folder overlaps once links are followed -- **may block**, so never on a GUI
        thread.

        Each folder is resolved with :func:`os.path.realpath` and the resolved forms compared with each other alone. A
        root in ``skip``, or one whose resolution fails, takes no part; the candidate failing to resolve leaves
        nothing to compare. The spelled comparison is :meth:`find`'s, and a caller runs both.

        :param candidate: the folder.
        :param roots: the roots to compare it with.
        :param skip: the ids of roots not to resolve -- those known unreachable, whose resolution would only wait.
        :returns: the overlap, naming the root as stored and the candidate as spelled, or ``None``.
        """
        key = RootOverlap.__resolved_key(candidate)
        if key is None:
            return None
        for root in roots:
            if root.root_id in skip:
                continue
            root_key = RootOverlap.__resolved_key(root.path)
            if root_key is None:
                continue
            encloses = RootOverlap.__relation(root_key, key)
            if encloses is not None:
                return RootOverlap(root, Path(candidate), encloses)
        return None

    @staticmethod
    def among(roots: Sequence[RehucoRoot]) -> tuple[RootOverlap, ...]:
        """Every pair of roots that already overlap, compared as spelled -- a file opened nesting.

        :param roots: the roots, in display order.
        :returns: one overlap per pair, its :attr:`root` the earlier of the two.
        """
        return tuple(RootOverlap.__pairs(roots, RootOverlap.find))

    @staticmethod
    def among_resolved(roots: Sequence[RehucoRoot], skip: Collection[UUID] = ()) -> tuple[RootOverlap, ...]:
        """Every pair of roots that overlap once links are followed -- **may block**, like :meth:`find_resolved`.

        :param roots: the roots, in display order.
        :param skip: the ids of roots not to resolve.
        :returns: one overlap per pair, its :attr:`root` the earlier of the two.
        """
        reachable = [root for root in roots if root.root_id not in skip]
        return tuple(RootOverlap.__pairs(reachable, RootOverlap.find_resolved))

    @staticmethod
    def __pairs(
        roots: Sequence[RehucoRoot], find: Callable[[Path, Sequence[RehucoRoot]], RootOverlap | None]
    ) -> Iterator[RootOverlap]:
        """Each root against every earlier one, one overlap per pair.

        :param roots: the roots, in display order.
        :param find: how one candidate is compared with a list of roots.
        :yields: the overlaps found.
        """
        for at, root in enumerate(roots):
            for earlier in roots[:at]:
                overlap = find(root.path, [earlier])
                if overlap is not None:
                    yield overlap

    @staticmethod
    def __relation(root_key: str, key: str) -> bool | None:
        """How a folder relates to a root, both as keys.

        :param root_key: the root's key.
        :param key: the folder's key.
        :returns: ``True`` when the root contains the folder, ``False`` when the folder contains the root, ``None``
            when neither does -- or when they are one folder.
        """
        if RootOverlap.__contains(root_key, key):
            return True
        if RootOverlap.__contains(key, root_key):
            return False
        return None

    @staticmethod
    def __contains(outer: str, inner: str) -> bool:
        """Whether ``inner`` is strictly inside ``outer``, compared on whole components so ``lib`` holds not
        ``lib2``."""
        if outer == inner:
            return False
        prefix = outer if outer.endswith(os_path.sep) else outer + os_path.sep
        return inner.startswith(prefix)

    @staticmethod
    def __resolved_key(path: Path | str) -> str | None:
        """A folder's key once links are followed, or ``None`` when it will not resolve.

        On Windows a folder that cannot be reached -- an offline share -- resolves to its own spelling rather than
        failing (``realpath`` is not strict), after waiting out the network's timeout; such a root compares as spelled
        and cannot be found inside a share nothing else resolves into, so the mixed pair costs a missed overlap at
        worst, never a false one. A caller spares the wait by naming the roots it knows unreachable in ``skip``.
        """
        try:
            return root_path_key(os_path.realpath(str(path)))
        except OSError, ValueError:
            return None
