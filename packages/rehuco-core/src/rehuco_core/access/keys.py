"""What a resource is reached by: its location on this machine (#413).

A key is a **location**, not an identity ([[nodes#access-seam]]): recognizing one resource reached by two routes stays
a UUID question ([[mounts-and-storage#uuid-not-paths]]). It carries the path arithmetic a holder needs to follow a
rename or name a sibling. A :class:`ResourceKey` compares as its :class:`~pathlib.Path` does, which is
:func:`os.path.normcase`'s rule -- case and separators folded on Windows, nothing folded on POSIX -- the rule
:class:`~rehuco_core.Relocation` and the rename itself use.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import override

from ..relocation import Relocation


@dataclass(frozen=True, slots=True)
class ResourceKey:
    """A resource, by its absolute path on this machine -- a local disk or a mounted share alike.

    The path is taken as given, never resolved: resolving touches the disk, which on an offline share waits out the
    network timeout. A ``..`` is refused instead, since two spellings of one place would be two keys; a ``.`` the path
    itself drops.

    :param path: the absolute path, spelled as the caller spells it.
    :raises ValueError: when ``path`` is relative or has a ``..`` component.
    """

    path: Path

    def __post_init__(self) -> None:
        if not self.path.is_absolute() or ".." in self.path.parts:
            raise ValueError(f"A resource key needs an absolute path with no '..', not {self.path}")

    @override
    def __str__(self) -> str:
        """:returns: the path, as spelled -- what a tooltip shows and a saved layout names a dock by."""
        return str(self.path)

    @property
    def name(self) -> str:
        """The final component, as spelled."""
        return self.path.name

    @property
    def stem(self) -> str:
        """The final component without its last suffix."""
        return self.path.stem

    @property
    def parent(self) -> ResourceKey:
        """The folder holding it; the anchor's parent is the anchor."""
        return ResourceKey(self.path.parent)

    @property
    def parts(self) -> tuple[str, ...]:
        """Its components, anchor first, as spelled."""
        return self.path.parts

    def with_name(self, name: str) -> ResourceKey:
        """The sibling called ``name``.

        :param name: the new final component.
        :returns: its key.
        """
        return ResourceKey(self.path.with_name(name))

    def joinpath(self, *parts: str) -> ResourceKey:
        """The location ``parts`` beneath this one.

        :param parts: the components to append.
        :returns: its key.
        """
        return ResourceKey(self.path.joinpath(*parts))

    def is_at_or_beneath(self, other: ResourceKey) -> bool:
        """Whether this is ``other`` or lies inside it, comparing whole components folded as the filesystem folds them.

        :param other: the would-be ancestor.
        :returns: whether ``other``'s components start this key's.
        """
        ancestor = Relocation.path_parts(other.path)
        return Relocation.path_parts(self.path)[: len(ancestor)] == ancestor
