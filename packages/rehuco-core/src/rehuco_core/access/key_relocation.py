"""Where keys went once a rename ran: :class:`~rehuco_core.Relocation`, over keys instead of paths (#413)."""

from dataclasses import dataclass
from typing import Self

from ..relocation import Relocation
from .keys import LocalKey, ResourceKey


@dataclass(frozen=True, slots=True)
class KeyRelocation:
    """The ``(source, destination)`` pairs one rename carried out, and the rule that reads them back.

    The same rule as :class:`~rehuco_core.Relocation` -- **a key at or beneath a renamed source lands at the same
    offset beneath its destination**, the unmoved tail keeping the candidate's own spelling -- with each key kind
    deciding what "beneath" means (:meth:`~rehuco_core.access.LocalKey.is_at_or_beneath`). An empty relocation moves
    nothing.

    :param pairs: the executed renames, in the order they ran.
    """

    pairs: tuple[tuple[ResourceKey, ResourceKey], ...] = ()

    @classmethod
    def from_local(cls, relocation: Relocation) -> Self:
        """The key form of a rename this machine ran.

        :param relocation: the rename's executed plan, over absolute paths.
        :returns: the same pairs as :class:`~rehuco_core.access.LocalKey` objects.
        """
        return cls(tuple((LocalKey(source), LocalKey(destination)) for source, destination in relocation.pairs))

    def relocate(self, candidate: ResourceKey) -> ResourceKey:
        """Where ``candidate`` ended up once the rename ran, or ``candidate`` itself if it did not move.

        :param candidate: any key -- a job's content file, a record, a listing's row.
        :returns: the key ``candidate`` now has.
        """
        for source, destination in self.pairs:
            if candidate.is_at_or_beneath(source):
                return destination.joinpath(*candidate.parts[len(source.parts) :])
        return candidate

    def touches(self, folder: ResourceKey) -> bool:
        """Whether the rename moved ``folder`` itself, something above it, or anything at or beneath it.

        Both ends of a pair count, in both directions, as in :meth:`~rehuco_core.Relocation.touches`.

        :param folder: the folder whose subtree is in question.
        :returns: whether ``folder`` is at or beneath either end of a pair, or either end is at or beneath it.
        """
        return any(folder.is_at_or_beneath(end) or end.is_at_or_beneath(folder) for pair in self.pairs for end in pair)
