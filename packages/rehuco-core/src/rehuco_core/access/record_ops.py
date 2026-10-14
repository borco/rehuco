"""What the records operation group answers: a record as read, as saved, and a save refused as a conflict (#416).

The group itself, :class:`~rehuco_core.access.RecordOps`, is declared beside the other groups in
:mod:`~rehuco_core.access.resource_access`; these are the values it hands back.
"""

from dataclasses import dataclass
from typing import Final

from ..lock_reasons import LockReason
from ..record_versions import RecordVersion
from ..rehu_document import RehuDocument

type FileSignature = tuple[int, int]
"""A file's modification time in nanoseconds and its size: what a later stat is compared with to see a change."""


@dataclass(frozen=True, slots=True)
class LoadedRecord:
    """A record as read.

    :param document: the document, or an empty locked stub standing in for a file that could not be read.
    :param version: what a save of it is checked against; ``None`` for a stub and a legacy ``.tc``, which are never
        saved over.
    :param lock_reasons: why it opens read-only, if it does.
    :param signature: the file's signature, taken before the read, so a change landing during it is seen as one;
        ``None`` when the file could not be stat'ed.
    """

    document: RehuDocument
    version: RecordVersion | None
    lock_reasons: tuple[LockReason, ...]
    signature: FileSignature | None


@dataclass(frozen=True, slots=True)
class SavedRecord:
    """A record as a save left it.

    :param version: what the next save is checked against.
    :param signature: the written file's signature, or ``None`` when it could not be stat'ed.
    :param users_merged: whether per-user fields the file held were merged into the saved document, so what shows
        them must be read again.
    """

    version: RecordVersion
    signature: FileSignature | None
    users_merged: bool


class RecordConflict(Exception):
    """A save refused because the record's metadata changed on disk since the saved document was read
    ([[nodes#access-seam]]); over the network, a ``409``.

    :param theirs: the record as it is on disk now.
    :param version: its version, which a save that has taken it into account is made against.
    """

    def __init__(self, theirs: RehuDocument, version: RecordVersion) -> None:
        super().__init__(f"{theirs.path} was changed by someone else since it was read")
        self.theirs: Final = theirs
        self.version: Final = version
