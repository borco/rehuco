"""What a document asks of the open catalog: the roots this machine reaches, and when they change (#579)."""

from typing import Protocol
from uuid import UUID

from PySide6.QtCore import SignalInstance
from rehuco_core import MappedRoot


class CatalogRoots(Protocol):
    """The open catalog's roots, as a document's path row reads them to offer the place its root's layout gives it.

    Implemented by `~rehuco_agent.rehuco.RootCatalog`, which owns the open ``.rehuco``; a protocol, so the documents
    package does not import the catalog's, which imports it.
    """

    def mapped_roots(self) -> tuple[MappedRoot, ...]:  # pyright: ignore[reportReturnType]
        """The roots of the open catalog this machine reaches, in the file's order; none while none is open."""

    def unreachable_roots(self) -> frozenset[UUID]:  # pyright: ignore[reportReturnType]
        """The roots whose folder could not be reached when last looked at, or whose ``.rehuroot`` cannot be read."""

    @property
    def roots_changed(self) -> SignalInstance:  # pyright: ignore[reportReturnType]
        """Fires when a root is added, removed, mapped or edited, or another catalog is opened."""

    @property
    def root_reachable(self) -> SignalInstance:  # pyright: ignore[reportReturnType]
        """Fires with a root's id and whether its folder can be reached now."""
