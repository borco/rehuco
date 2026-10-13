"""Tests for a rename's executed plan over keys (#413): the :class:`~rehuco_core.Relocation` rule, for both kinds.

Pure arithmetic: nothing here touches a filesystem, so nothing is mocked either.
"""

from pathlib import Path
from typing import Final
from uuid import UUID

from pytest import mark
from rehuco_core import KeyRelocation, LocalKey, NodeKey, Relocation

LIBRARY: Final = Path("/fake/library").absolute()
FOLDER_RENAME: Final = KeyRelocation.from_local(Relocation(((LIBRARY / "pack", LIBRARY / "kit"),)))
FILE_RENAME: Final = KeyRelocation.from_local(
    Relocation(
        (
            (LIBRARY / "foo.rehu", LIBRARY / "bar.rehu"),
            (LIBRARY / "foo.zip", LIBRARY / "bar.zip"),
        )
    )
)
NODE: Final = "node-device-id"
ROOT: Final = UUID("00000000-0000-0000-0000-000000000001")
NODE_RENAME: Final = KeyRelocation(((NodeKey(NODE, ROOT, "pack"), NodeKey(NODE, ROOT, "kit")),))


# region relocate
def test_from_local_wraps_each_pair_in_local_keys() -> None:
    """The key form of a local rename holds the same pairs.

    **Test steps:**

    * read the pairs of a converted file rename
    """
    assert FILE_RENAME.pairs == (
        (LocalKey(LIBRARY / "foo.rehu"), LocalKey(LIBRARY / "bar.rehu")),
        (LocalKey(LIBRARY / "foo.zip"), LocalKey(LIBRARY / "bar.zip")),
    )


def test_a_renamed_source_lands_on_its_destination() -> None:
    """The renamed entry itself answers its destination, for either kind.

    **Test steps:**

    * relocate a renamed local file and a renamed node folder
    """
    assert FILE_RENAME.relocate(LocalKey(LIBRARY / "foo.zip")) == LocalKey(LIBRARY / "bar.zip")
    assert NODE_RENAME.relocate(NodeKey(NODE, ROOT, "pack")) == NodeKey(NODE, ROOT, "kit")


def test_a_key_beneath_a_renamed_folder_keeps_its_offset() -> None:
    """A record nested anywhere under a renamed folder rebases with it, for either kind.

    **Test steps:**

    * relocate a nested local record and a nested node record
    """
    nested = LocalKey(LIBRARY / "pack" / "member" / "info.rehu")

    assert FOLDER_RENAME.relocate(nested) == LocalKey(LIBRARY / "kit" / "member" / "info.rehu")
    assert NODE_RENAME.relocate(NodeKey(NODE, ROOT, "pack/member/info.rehu")) == NodeKey(
        NODE, ROOT, "kit/member/info.rehu"
    )


@mark.parametrize(
    ("relocation", "candidate"),
    [
        (FOLDER_RENAME, LocalKey(LIBRARY / "pack2" / "info.rehu")),
        (FOLDER_RENAME, NodeKey(NODE, ROOT, "pack/info.rehu")),
        (NODE_RENAME, LocalKey(LIBRARY / "pack")),
        (NODE_RENAME, NodeKey(NODE, UUID("00000000-0000-0000-0000-000000000002"), "pack")),
    ],
)
def test_what_the_rename_did_not_move_stays(relocation: KeyRelocation, candidate: LocalKey | NodeKey) -> None:
    """A sibling whose name merely starts alike, a key of another kind, and the same path under another root stay.

    **Test steps:**

    * relocate the candidate
    """
    assert relocation.relocate(candidate) == candidate


def test_an_empty_relocation_moves_nothing() -> None:
    """What a rename that did not happen answers with.

    **Test steps:**

    * relocate through an empty relocation
    """
    key = LocalKey(LIBRARY / "pack")

    assert KeyRelocation().relocate(key) == key


@mark.windows
def test_case_folds_on_windows_and_the_tail_keeps_its_own_spelling() -> None:
    """A differently-cased local ancestor still relocates, without respelling the rest of the name.

    **Test steps:**

    * relocate a key under the folder spelled in another case
    * check the tail's spelling
    """
    relocated = FOLDER_RENAME.relocate(LocalKey(LIBRARY / "PACK" / "Member.rehu"))

    assert isinstance(relocated, LocalKey)
    assert relocated.path == LIBRARY / "kit" / "Member.rehu"


def test_a_node_key_spelled_in_another_case_does_not_move() -> None:
    """Node keys compare as spelled, so a differently-cased path is another file on the node.

    **Test steps:**

    * relocate a node key under the folder spelled in another case
    """
    candidate = NodeKey(NODE, ROOT, "PACK/info.rehu")

    assert NODE_RENAME.relocate(candidate) == candidate


# endregion


# region touches
@mark.parametrize(
    ("folder", "touched"),
    [
        (LocalKey(LIBRARY), True),
        (LocalKey(LIBRARY / "pack"), True),
        (LocalKey(LIBRARY / "pack" / "member"), True),
        (LocalKey(LIBRARY / "kit" / "member"), True),
        (LocalKey(LIBRARY / "other"), False),
        (LocalKey(LIBRARY / "pack2"), False),
        (NodeKey(NODE, ROOT, ""), False),
    ],
)
def test_a_folder_rename_touches_its_parent_itself_its_subtree_and_its_destination(
    folder: LocalKey | NodeKey, touched: bool
) -> None:
    """A listing of any of these would show something different after the rename; another kind never would.

    **Test steps:**

    * ask each folder whether the local folder rename touches it
    """
    assert FOLDER_RENAME.touches(folder) is touched


def test_a_node_rename_touches_its_root() -> None:
    """The root's listing shows the renamed folder.

    **Test steps:**

    * ask the root and a sibling folder
    """
    assert NODE_RENAME.touches(NodeKey(NODE, ROOT, ""))
    assert not NODE_RENAME.touches(NodeKey(NODE, ROOT, "other"))


def test_an_empty_relocation_touches_nothing() -> None:
    """Nothing moved, so no listing needs reading again.

    **Test steps:**

    * ask an empty relocation about a folder
    """
    assert not KeyRelocation().touches(LocalKey(LIBRARY))


# endregion


# region to_local


def test_to_local_keeps_the_local_pairs_as_paths() -> None:
    """A holder of local paths -- the cache, the Roots tree -- gets this machine's renames back as a path relocation.

    **Test steps:**

    * turn a local relocation back
    """
    assert FOLDER_RENAME.to_local() == Relocation(((LIBRARY / "pack", LIBRARY / "kit"),))


def test_to_local_leaves_out_a_node_s_pairs() -> None:
    """A rename on another node's root concerns no local holder.

    **Test steps:**

    * turn a node relocation, and a mixed one, back
    """
    mixed = KeyRelocation((*NODE_RENAME.pairs, *FOLDER_RENAME.pairs))

    assert NODE_RENAME.to_local() == Relocation()
    assert mixed.to_local() == FOLDER_RENAME.to_local()


# endregion
