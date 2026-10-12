"""What a resource is reached by: a location on this machine, or one under another node's root (#413).

A key is a **location**, not an identity ([[nodes#access-seam]]): recognizing one resource reached by two routes stays
a UUID question ([[mounts-and-storage#uuid-not-paths]]). Both kinds share the path arithmetic a holder needs to follow
a rename or name a sibling, so code written against :data:`ResourceKey` works for either; only :class:`LocalKey` has a
:attr:`~LocalKey.path`, so code that would treat a remote resource as a file does not type-check.

**Equality differs by kind, on purpose.** A :class:`LocalKey` compares as its :class:`~pathlib.Path` does, which is
:func:`os.path.normcase`'s rule -- case and separators folded on Windows, nothing folded on POSIX -- the rule
:class:`~rehuco_core.Relocation` and the rename itself use. A :class:`NodeKey` compares its path **as spelled**: the
owning node hands out its own canonical spelling, and folding it by *this* machine's rule would merge two files a
case-sensitive node keeps apart. The worst an unfolded spelling does is show one file twice.
"""

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from uuid import UUID

from ..relocation import Relocation


@dataclass(frozen=True, slots=True)
class LocalKey:
    """A resource this machine reaches itself, by its absolute path.

    The path is taken as given, never resolved: resolving touches the disk, which on an offline share waits out the
    network timeout. A ``..`` is refused instead, since two spellings of one place would be two keys; a ``.`` the path
    itself drops.

    :param path: the absolute path, spelled as the caller spells it.
    :raises ValueError: when ``path`` is relative or has a ``..`` component.
    """

    path: Path

    def __post_init__(self) -> None:
        if not self.path.is_absolute() or ".." in self.path.parts:
            raise ValueError(f"A local key needs an absolute path with no '..', not {self.path}")

    @property
    def name(self) -> str:
        """The final component, as spelled."""
        return self.path.name

    @property
    def stem(self) -> str:
        """The final component without its last suffix."""
        return self.path.stem

    @property
    def parent(self) -> LocalKey:
        """The folder holding it; the anchor's parent is the anchor."""
        return LocalKey(self.path.parent)

    @property
    def parts(self) -> tuple[str, ...]:
        """Its components, anchor first, as spelled."""
        return self.path.parts

    def with_name(self, name: str) -> LocalKey:
        """The sibling called ``name``.

        :param name: the new final component.
        :returns: its key.
        """
        return LocalKey(self.path.with_name(name))

    def joinpath(self, *parts: str) -> LocalKey:
        """The location ``parts`` beneath this one.

        :param parts: the components to append.
        :returns: its key.
        """
        return LocalKey(self.path.joinpath(*parts))

    def is_at_or_beneath(self, other: ResourceKey) -> bool:
        """Whether this is ``other`` or lies inside it, comparing whole components folded as the filesystem folds them.

        :param other: the would-be ancestor; a :class:`NodeKey` never contains a local key.
        :returns: whether ``other``'s components start this key's.
        """
        if not isinstance(other, LocalKey):
            return False
        ancestor = Relocation.path_parts(other.path)
        return Relocation.path_parts(self.path)[: len(ancestor)] == ancestor


@dataclass(frozen=True, slots=True)
class NodeKey:
    """A resource under a root another node owns; that node resolves it to its own :class:`LocalKey`.

    The ``.rehudb`` cache stores a resource as root plus root-relative path ([[data-model#cache-schema]]), so a
    catalog row maps straight onto one.

    :param node_id: the owning node's device ID ([[discovery-trust-access#node-identity-pairing]]).
    :param root_id: the root's ``.rehuco`` id.
    :param relative: the path under the root, ``/``-separated, as the node spells it; ``""`` is the root itself.
    :raises ValueError: when ``relative`` is absolute, climbs out of the root with ``..``, or is not in its plain form
        (a doubled or trailing ``/``, a ``.`` component) -- spellings that would compare unequal to the same place.
    """

    node_id: str
    root_id: UUID
    relative: str

    def __post_init__(self) -> None:
        if self.relative == "":
            return
        posix = PurePosixPath(self.relative)
        if posix.is_absolute() or ".." in posix.parts or str(posix) != self.relative or self.relative == ".":
            raise ValueError(f"A node key needs a plain path under its root, not {self.relative!r}")

    @property
    def name(self) -> str:
        """The final component, as spelled; ``""`` for the root."""
        return self.__posix().name

    @property
    def stem(self) -> str:
        """The final component without its last suffix."""
        return self.__posix().stem

    @property
    def parent(self) -> NodeKey:
        """The folder holding it; the root's parent is the root."""
        if not self.relative:
            return self
        return self.__at(self.__posix().parent)

    @property
    def parts(self) -> tuple[str, ...]:
        """Its components under the root, as spelled; empty for the root."""
        return self.__posix().parts if self.relative else ()

    def with_name(self, name: str) -> NodeKey:
        """The sibling called ``name``.

        :param name: the new final component.
        :returns: its key.
        :raises ValueError: for the root, which has no name to replace.
        """
        return self.__at(self.__posix().with_name(name))

    def joinpath(self, *parts: str) -> NodeKey:
        """The location ``parts`` beneath this one.

        :param parts: the components to append.
        :returns: its key.
        :raises ValueError: when the result would leave the root.
        """
        return self.__at(PurePosixPath(self.relative, *parts))

    def is_at_or_beneath(self, other: ResourceKey) -> bool:
        """Whether this is ``other`` or lies inside it: the same node and root, and ``other``'s components, as
        spelled, starting this key's.

        :param other: the would-be ancestor; a :class:`LocalKey` never contains a node key.
        :returns: whether this key is at or beneath ``other``.
        """
        if not isinstance(other, NodeKey) or (other.node_id, other.root_id) != (self.node_id, self.root_id):
            return False
        ancestor = other.parts
        return self.parts[: len(ancestor)] == ancestor

    def __posix(self) -> PurePosixPath:
        """:returns: the relative path as a pure path, for the arithmetic."""
        return PurePosixPath(self.relative)

    def __at(self, relative: PurePosixPath) -> NodeKey:
        """The key on this key's node and root at ``relative``.

        :param relative: the new path under the root; ``.`` is the root.
        :returns: its key.
        """
        spelled = str(relative)
        return NodeKey(self.node_id, self.root_id, "" if spelled == "." else spelled)


type ResourceKey = LocalKey | NodeKey
"""A resource's location: on this machine, or under another node's root ([[nodes#access-seam]])."""
