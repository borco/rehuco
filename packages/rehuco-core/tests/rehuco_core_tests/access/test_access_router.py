"""Tests for routing a key to the implementation that reaches it, and the local implementation's answers (#413)."""

from pathlib import Path
from typing import Final
from uuid import UUID

from pytest import raises
from rehuco_core import (
    LOCAL_CAPABILITIES,
    AccessRouter,
    Capability,
    ChangeFeed,
    LocalAccess,
    LocalKey,
    NodeKey,
    NodeUnreachable,
)

LOCAL_KEY: Final = LocalKey(Path("/fake/library/pack").absolute())
NODE_KEY: Final = NodeKey("node-device-id", UUID("00000000-0000-0000-0000-000000000001"), "pack")


def test_a_local_key_goes_to_the_local_implementation() -> None:
    """A resource this machine reaches itself is reached through local access.

    **Test steps:**

    * route a local key
    """
    local = LocalAccess()
    router = AccessRouter(local)

    assert router.for_key(LOCAL_KEY) is local
    assert router.local is local


def test_a_node_key_has_no_route_yet() -> None:
    """Until the remote implementation exists, another node's resource is unreachable, and the error says which.

    **Test steps:**

    * route a node key
    * check the error carries it
    """
    router = AccessRouter(LocalAccess())

    with raises(NodeUnreachable) as caught:
        router.for_key(NODE_KEY)

    assert caught.value.key == NODE_KEY
    assert isinstance(caught.value, LookupError)


def test_local_access_announces_on_the_feed_it_was_given() -> None:
    """The agent hands in the feed it adapts to Qt signals; without one, local access makes its own.

    **Test steps:**

    * build local access with and without a feed
    """
    feed = ChangeFeed()

    assert LocalAccess(feed).changes is feed
    assert isinstance(LocalAccess().changes, ChangeFeed)


def test_a_local_resource_has_every_capability() -> None:
    """A file on this machine has a path, can be revealed, recycled and converted.

    **Test steps:**

    * ask local access for a local key's capabilities
    """
    assert LocalAccess().capabilities(LOCAL_KEY) == LOCAL_CAPABILITIES == frozenset(Capability)


def test_local_access_refuses_to_answer_for_a_node_key() -> None:
    """Only the owning node's access answers for its keys; the router never sends one here.

    **Test steps:**

    * ask local access for a node key's capabilities
    """
    with raises(TypeError):
        LocalAccess().capabilities(NODE_KEY)


def test_a_path_entering_the_app_becomes_a_local_key() -> None:
    """Until a root's claim is read (#453), every path is reached by this machine itself, spelled as it was given.

    **Test steps:**

    * turn an absolute path into a key
    * check a relative one is refused, as a local key refuses it
    """
    router = AccessRouter(LocalAccess())
    path = Path("/fake/library/Pack/info.rehu").absolute()

    key = router.key_for_path(path)

    assert key == LocalKey(path)
    assert isinstance(key, LocalKey) and str(key.path) == str(path)
    with raises(ValueError):
        router.key_for_path(Path("relative/info.rehu"))
