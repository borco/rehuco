"""Which implementation a key is reached through (#413).

Local only for now: a :class:`~rehuco_core.access.NodeKey` has nowhere to go until the remote implementation arrives
(#420, #421), and a local root a node owns is not yet sent to that node (#453).
"""

from pathlib import Path
from typing import Final

from .keys import LocalKey, NodeKey, ResourceKey
from .local_access import LocalAccess
from .resource_access import ResourceAccess


class NodeUnreachable(LookupError):
    """No implementation can reach the node owning a key -- what a read shows as *unreachable*.

    :param key: the key that could not be routed.
    """

    def __init__(self, key: NodeKey) -> None:
        super().__init__(f"No route to node {key.node_id} for {key.relative!r} under root {key.root_id}")
        self.key: Final = key


class AccessRouter:
    """Picks the :class:`~rehuco_core.access.ResourceAccess` a key is reached through.

    :param local: the implementation for resources this machine reaches itself.
    """

    def __init__(self, local: LocalAccess) -> None:
        self.__local: Final = local

    @property
    def local(self) -> LocalAccess:
        """The implementation for resources this machine reaches itself -- whose change feed the agent adapts, and
        whose catalog it attaches the open ``.rehuco``'s cache to."""
        return self.__local

    def key_for_path(self, path: Path) -> ResourceKey:
        """The key a path entering the app is reached by -- a dialog's pick, a double-clicked file, a recent.

        A path says where the bytes are, not who owns them: a root a node owns is reached through that node even on
        this machine ([[nodes#two-roles]]), so this is the one place a path becomes a key. Every path is a
        :class:`~rehuco_core.access.LocalKey` until the folder's ownership claim is read here (#453).

        :param path: an absolute path, spelled as the caller spells it.
        :returns: its key.
        :raises ValueError: when ``path`` is relative or has a ``..`` component.
        """
        return LocalKey(path)

    def for_key(self, key: ResourceKey) -> ResourceAccess:
        """The implementation ``key`` is reached through.

        :param key: the resource.
        :returns: its implementation.
        :raises NodeUnreachable: for a :class:`~rehuco_core.access.NodeKey`, which no implementation reaches yet.
        """
        if isinstance(key, NodeKey):
            raise NodeUnreachable(key)
        return self.__local
