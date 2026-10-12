"""Which implementation a key is reached through (#413).

Local only for now: a :class:`~rehuco_core.access.NodeKey` has nowhere to go until the remote implementation arrives
(#420, #421), and a local root a node owns is not yet sent to that node (#453).
"""

from typing import Final

from .keys import NodeKey, ResourceKey
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

    def __init__(self, local: ResourceAccess) -> None:
        self.__local: Final = local

    @property
    def local(self) -> ResourceAccess:
        """The implementation for resources this machine reaches itself -- whose change feed the agent adapts."""
        return self.__local

    def for_key(self, key: ResourceKey) -> ResourceAccess:
        """The implementation ``key`` is reached through.

        :param key: the resource.
        :returns: its implementation.
        :raises NodeUnreachable: for a :class:`~rehuco_core.access.NodeKey`, which no implementation reaches yet.
        """
        if isinstance(key, NodeKey):
            raise NodeUnreachable(key)
        return self.__local
