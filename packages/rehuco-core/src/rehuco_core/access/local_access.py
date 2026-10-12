"""Resources this machine reaches itself, through its own filesystem (#413)."""

from typing import Final, override

from .change_feed import ChangeFeed
from .keys import LocalKey, ResourceKey
from .resource_access import Capability, ResourceAccess

LOCAL_CAPABILITIES: Final = frozenset(Capability)
"""Everything a file on this machine allows; refined per volume when legacy conversion, reveal and the Recycle Bin
move behind capabilities (#430)."""


class LocalAccess(ResourceAccess):
    """The :class:`~rehuco_core.access.ResourceAccess` over :class:`~rehuco_core.access.LocalKey` objects.

    :param changes: where every change it makes is announced; a new feed when not given.
    """

    def __init__(self, changes: ChangeFeed | None = None) -> None:
        self.__changes: Final = changes if changes is not None else ChangeFeed()

    @property
    @override
    def changes(self) -> ChangeFeed:
        """Where this implementation announces every change it makes."""
        return self.__changes

    @override
    def capabilities(self, key: ResourceKey) -> frozenset[Capability]:
        """What can be done for a local ``key``: everything.

        :param key: the resource.
        :returns: its capabilities.
        :raises TypeError: for a :class:`~rehuco_core.access.NodeKey`, which only its node's access answers.
        """
        if not isinstance(key, LocalKey):
            raise TypeError(f"Local access cannot answer for {key}")
        return LOCAL_CAPABILITIES
