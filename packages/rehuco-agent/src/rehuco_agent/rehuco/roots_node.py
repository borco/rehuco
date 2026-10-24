"""One row of the Roots view's model, and what kinds of row there are (#378, #514).

A node stores a name only; where it is derives from its ancestors, which is the model's business
(:class:`~rehuco_agent.rehuco.roots_folder_model.RootsFolderModel`).
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from rehuco_core import FileType, MappedRoot, RehucoRoot

from .roots_checksum import RowChecksum

type ShownRoot = MappedRoot | RehucoRoot
"""A root the model shows: a :class:`~rehuco_core.MappedRoot` when this machine reaches it, and so lists it; the
file's own :class:`~rehuco_core.RehucoRoot` when it does not (#514), which has a name and a location and no folder."""


def root_where(root: ShownRoot) -> str:
    """Where a root is, as it is shown: this machine's folder, or the location of a root not mapped here.

    :param root: the root.
    :returns: the text.
    """
    return str(root.path) if isinstance(root, MappedRoot) else root.location


def root_title(root: ShownRoot) -> str:
    """What a root is called in a question about it: its label, or where it is while the label is empty.

    :param root: the root.
    :returns: the text.
    """
    return root.label or root_where(root)


class RootsNodeKind(StrEnum):
    """What a node is. The last two are placeholder rows: a column shows one while it loads, or when it could not
    be listed, and neither can be selected."""

    ROOT = "root"
    FOLDER = "folder"
    FILE = "file"
    LOADING = "loading"
    UNREACHABLE = "unreachable"


class NodeListing(StrEnum):
    """Where a root's or folder's listing stands."""

    UNLISTED = "unlisted"
    """Never asked for."""

    PENDING = "pending"
    """A listing is out. Rows already shown stay until it lands."""

    LISTED = "listed"
    """Listed, and it was reachable."""

    UNREACHABLE = "unreachable"
    """Listed, and the folder could not be read."""


PLACEHOLDER_KINDS: Final = (RootsNodeKind.LOADING, RootsNodeKind.UNREACHABLE)

LISTABLE_KINDS: Final = (RootsNodeKind.ROOT, RootsNodeKind.FOLDER)


@dataclass(eq=False)
class RootsNode:  # pylint: disable=too-many-instance-attributes
    """One row. It stores its name only; where it is derives from its ancestors, and what it shows (:attr:`label`)
    from its name.

    :param name: the row's name -- a root's label, a folder's or file's name, or a placeholder's text. A root's name
        is the text of the field it is edited in while it is being edited, and may be empty.
    :param kind: what the row is.
    :param parent: the row above, or ``None`` for the invisible top.
    :param file_type: what a folder or file is by shape.
    :param root: the root, for a root row.
    :param size: a file's size in bytes, when the listing had it.
    :param modified: a modification time as a POSIX timestamp, when the listing had it.
    :param checksum: what the record that covers a file says about it, when one does (#457).
    :param bookkeeping: whether a file is a record, a checksum file or a screenshot.
    :param listed_at: :func:`time.monotonic` when its listing last landed, reachable or not; ``None`` until one
        has.
    """

    name: str
    kind: RootsNodeKind
    parent: RootsNode | None
    file_type: FileType = FileType.GENERIC
    root: ShownRoot | None = None
    size: int | None = None
    modified: float | None = None
    checksum: RowChecksum | None = None
    bookkeeping: bool = False
    children: list[RootsNode] = field(default_factory=list)
    row: int = 0
    listing: NodeListing = NodeListing.UNLISTED
    request: int = 0
    listed_at: float | None = None

    @property
    def label(self) -> str:
        """What the row shows: its name -- and, for a root whose name is empty, where the root is: this machine's
        folder, or the location of a root not mapped here. Derived, never stored."""
        if self.name or self.root is None:
            return self.name
        return root_where(self.root)
