"""Tests for resource keys: their identity rules and the path arithmetic both kinds share (#413).

Pure arithmetic: nothing here touches a filesystem, so nothing is mocked either.
"""

from pathlib import Path
from typing import Final
from uuid import UUID

from pytest import mark, raises
from rehuco_core import LocalKey, NodeKey

LIBRARY: Final = Path("/fake/library").absolute()
NODE: Final = "node-device-id"
ROOT: Final = UUID("00000000-0000-0000-0000-000000000001")
OTHER_ROOT: Final = UUID("00000000-0000-0000-0000-000000000002")


# region LocalKey identity
def test_a_local_key_refuses_a_relative_path() -> None:
    """A key is a location on this machine, which a relative path is not.

    **Test steps:**

    * build a key from a relative path
    """
    with raises(ValueError, match="absolute"):
        LocalKey(Path("pack") / "info.rehu")


def test_a_local_key_refuses_a_dot_dot_and_drops_a_dot() -> None:
    """``pack/../pack`` would be a second key for one place, and resolving it would touch the disk; ``.`` costs nothing
    because the path itself drops it.

    **Test steps:**

    * build a key from a path with ``..``
    * build one from a path with ``.`` and compare it with the plain spelling
    """
    with raises(ValueError, match=r"\.\."):
        LocalKey(LIBRARY / "pack" / ".." / "kit")

    assert LocalKey(LIBRARY / "." / "pack") == LocalKey(LIBRARY / "pack")


@mark.windows
def test_local_keys_fold_case_on_windows() -> None:
    """Two spellings of one file on a case-insensitive filesystem are one key, and hash alike.

    **Test steps:**

    * compare and hash two keys differing only in case
    * check the key keeps the spelling it was given
    """
    upper = LocalKey(LIBRARY / "Pack" / "INFO.rehu")
    lower = LocalKey(LIBRARY / "pack" / "info.rehu")

    assert upper == lower
    assert hash(upper) == hash(lower)
    assert upper.name == "INFO.rehu"


@mark.linux
def test_local_keys_keep_case_on_linux() -> None:
    """A case-sensitive filesystem keeps ``Pack`` and ``pack`` apart.

    **Test steps:**

    * compare two keys differing only in case
    """
    assert LocalKey(LIBRARY / "Pack") != LocalKey(LIBRARY / "pack")


def test_a_local_key_never_equals_a_node_key() -> None:
    """The two kinds are never the same location, whatever they spell.

    **Test steps:**

    * compare a local key with a node key
    """
    assert LocalKey(LIBRARY / "pack") != NodeKey(NODE, ROOT, "pack")


# endregion


# region NodeKey identity
def test_node_keys_compare_as_spelled() -> None:
    """The owning node hands out canonical spellings; folding by this machine's rule could merge two of its files.

    **Test steps:**

    * compare two node keys differing only in case
    * compare two spelled alike
    """
    assert NodeKey(NODE, ROOT, "Pack") != NodeKey(NODE, ROOT, "pack")
    assert NodeKey(NODE, ROOT, "pack") == NodeKey(NODE, ROOT, "pack")
    assert hash(NodeKey(NODE, ROOT, "pack")) == hash(NodeKey(NODE, ROOT, "pack"))


def test_node_keys_differ_by_node_and_by_root() -> None:
    """The same relative path under another root, or another node, is somewhere else.

    **Test steps:**

    * compare keys differing only in root, then only in node
    """
    assert NodeKey(NODE, ROOT, "pack") != NodeKey(NODE, OTHER_ROOT, "pack")
    assert NodeKey(NODE, ROOT, "pack") != NodeKey("another-node", ROOT, "pack")


@mark.parametrize("relative", ["/pack", "../pack", "pack/../other", "pack/", "pack//info.rehu", "./pack", "."])
def test_a_node_key_refuses_a_path_that_is_not_plain_and_under_its_root(relative: str) -> None:
    """Each of these either leaves the root or spells a place two ways, which exact comparison cannot afford.

    **Test steps:**

    * build a node key from the spelling
    """
    with raises(ValueError, match="plain path"):
        NodeKey(NODE, ROOT, relative)


# endregion


# region arithmetic
def test_local_key_arithmetic_follows_its_path() -> None:
    """Every operation answers what the same operation on the path answers.

    **Test steps:**

    * read name, stem, parent and parts
    * derive a sibling and a child
    """
    key = LocalKey(LIBRARY / "pack" / "info.rehu")

    assert key.name == "info.rehu"
    assert key.stem == "info"
    assert key.parent == LocalKey(LIBRARY / "pack")
    assert key.parts == (LIBRARY / "pack" / "info.rehu").parts
    assert key.with_name("other.rehu") == LocalKey(LIBRARY / "pack" / "other.rehu")
    assert LocalKey(LIBRARY).joinpath("pack", "info.rehu") == key


def test_node_key_arithmetic_stays_on_its_node_and_root() -> None:
    """Every derived key keeps the node and root, and spells its path ``/``-separated.

    **Test steps:**

    * read name, stem, parent and parts
    * derive a sibling and a child
    """
    key = NodeKey(NODE, ROOT, "pack/info.rehu")

    assert key.name == "info.rehu"
    assert key.stem == "info"
    assert key.parent == NodeKey(NODE, ROOT, "pack")
    assert key.parts == ("pack", "info.rehu")
    assert key.with_name("other.rehu") == NodeKey(NODE, ROOT, "pack/other.rehu")
    assert NodeKey(NODE, ROOT, "").joinpath("pack", "info.rehu") == key


def test_a_node_keys_root_is_the_empty_path() -> None:
    """A root-level entry's parent is the root, the root's parent is itself, and the root has no name or parts.

    **Test steps:**

    * walk up from a root-level entry twice
    * read the root's name and parts
    * try to rename the root
    """
    root = NodeKey(NODE, ROOT, "")

    assert NodeKey(NODE, ROOT, "pack").parent == root
    assert root.parent == root
    assert root.name == ""
    assert root.parts == ()
    with raises(ValueError):
        root.with_name("pack")


def test_a_node_key_cannot_join_its_way_out_of_its_root() -> None:
    """``..`` would name a place the root's node never handed out.

    **Test steps:**

    * join ``..`` onto a key
    """
    with raises(ValueError, match="plain path"):
        NodeKey(NODE, ROOT, "pack").joinpath("..", "..", "elsewhere")


# endregion


# region is_at_or_beneath
@mark.parametrize(
    ("candidate", "ancestor", "beneath"),
    [
        (LocalKey(LIBRARY / "pack"), LocalKey(LIBRARY / "pack"), True),
        (LocalKey(LIBRARY / "pack" / "member" / "info.rehu"), LocalKey(LIBRARY / "pack"), True),
        (LocalKey(LIBRARY / "pack2" / "info.rehu"), LocalKey(LIBRARY / "pack"), False),
        (LocalKey(LIBRARY), LocalKey(LIBRARY / "pack"), False),
        (NodeKey(NODE, ROOT, "pack/info.rehu"), NodeKey(NODE, ROOT, "pack"), True),
        (NodeKey(NODE, ROOT, "pack"), NodeKey(NODE, ROOT, ""), True),
        (NodeKey(NODE, ROOT, "pack2/info.rehu"), NodeKey(NODE, ROOT, "pack"), False),
        (NodeKey(NODE, ROOT, "Pack/info.rehu"), NodeKey(NODE, ROOT, "pack"), False),
        (NodeKey(NODE, ROOT, "pack/info.rehu"), NodeKey(NODE, OTHER_ROOT, "pack"), False),
        (NodeKey(NODE, ROOT, "pack/info.rehu"), NodeKey("another-node", ROOT, "pack"), False),
        (NodeKey(NODE, ROOT, "pack"), LocalKey(LIBRARY), False),
        (LocalKey(LIBRARY / "pack"), NodeKey(NODE, ROOT, ""), False),
    ],
)
def test_is_at_or_beneath_compares_whole_components_on_one_root(
    candidate: LocalKey | NodeKey, ancestor: LocalKey | NodeKey, beneath: bool
) -> None:
    """A key itself and anything inside it count; a sibling whose name merely starts alike, another root, another
    node or another kind never do.

    **Test steps:**

    * ask whether the candidate is at or beneath the ancestor
    """
    assert candidate.is_at_or_beneath(ancestor) is beneath


@mark.windows
def test_a_local_ancestor_spelled_in_another_case_still_contains_on_windows() -> None:
    """Containment folds case where the filesystem does, as equality does.

    **Test steps:**

    * ask about a path under a differently-cased ancestor
    """
    assert LocalKey(LIBRARY / "pack" / "info.rehu").is_at_or_beneath(LocalKey(LIBRARY / "PACK"))


# endregion


# region text


def test_a_local_key_reads_as_its_path() -> None:
    """A local key's text is its path as spelled -- what a dock was named by before keys, so saved layouts still match.

    **Test steps:**

    * read a local key as text
    """
    path = LIBRARY / "Pack" / "info.rehu"

    assert str(LocalKey(path)) == str(path)


def test_a_node_key_reads_as_node_root_and_relative() -> None:
    """A node key's text names its node, its root and its path, so two roots' same-named files differ.

    **Test steps:**

    * read node keys on two roots as text
    """
    assert str(NodeKey(NODE, ROOT, "pack/info.rehu")) == f"{NODE}/{ROOT}/pack/info.rehu"
    assert str(NodeKey(NODE, ROOT, "pack")) != str(NodeKey(NODE, OTHER_ROOT, "pack"))


# endregion
