"""What one backend saw happen under a watched folder, before it is coalesced into the change feed's events (#511)."""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class RawChangeKind(StrEnum):
    """What happened to an entry."""

    CREATED = "created"
    MODIFIED = "modified"
    DELETED = "deleted"
    MOVED = "moved"
    """Renamed or moved within the watched folder, from :attr:`RawChange.path` to :attr:`RawChange.destination`."""

    OVERFLOW = "overflow"
    """The backend lost events -- its buffer overflowed -- so nothing it did not report can be trusted."""


@dataclass(frozen=True, slots=True)
class RawChange:
    """One observation, as a backend reports it.

    :param kind: what happened.
    :param path: the entry's absolute path; its old path for a move; the watched folder for an overflow.
    :param destination: a move's new absolute path; ``None`` otherwise.
    :param is_directory: whether the entry is a folder, as far as the backend could tell.
    """

    kind: RawChangeKind
    path: Path
    destination: Path | None = None
    is_directory: bool = False
