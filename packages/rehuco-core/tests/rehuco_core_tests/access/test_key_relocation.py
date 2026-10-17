"""Tests for a rename's executed plan over keys (#413): the :class:`~rehuco_core.Relocation` rule.

Pure arithmetic: nothing here touches a filesystem, so nothing is mocked either.
"""

from pathlib import Path
from typing import Final

from pytest import mark
from rehuco_core import KeyRelocation, Relocation, ResourceKey

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


# region relocate
def test_from_local_wraps_each_pair_in_local_keys() -> None:
    """The key form of a local rename holds the same pairs.

    **Test steps:**

    * read the pairs of a converted file rename
    """
    assert FILE_RENAME.pairs == (
        (ResourceKey(LIBRARY / "foo.rehu"), ResourceKey(LIBRARY / "bar.rehu")),
        (ResourceKey(LIBRARY / "foo.zip"), ResourceKey(LIBRARY / "bar.zip")),
    )


def test_a_renamed_source_lands_on_its_destination() -> None:
    """The renamed entry itself answers its destination.

    **Test steps:**

    * relocate a renamed file
    """
    assert FILE_RENAME.relocate(ResourceKey(LIBRARY / "foo.zip")) == ResourceKey(LIBRARY / "bar.zip")


def test_a_key_beneath_a_renamed_folder_keeps_its_offset() -> None:
    """A record nested anywhere under a renamed folder rebases with it.

    **Test steps:**

    * relocate a nested record
    """
    nested = ResourceKey(LIBRARY / "pack" / "member" / "info.rehu")

    assert FOLDER_RENAME.relocate(nested) == ResourceKey(LIBRARY / "kit" / "member" / "info.rehu")


@mark.parametrize("candidate", [ResourceKey(LIBRARY / "pack2" / "info.rehu"), ResourceKey(LIBRARY)])
def test_what_the_rename_did_not_move_stays(candidate: ResourceKey) -> None:
    """A sibling whose name merely starts alike, and the renamed folder's parent, stay.

    **Test steps:**

    * relocate the candidate
    """
    assert FOLDER_RENAME.relocate(candidate) == candidate


def test_an_empty_relocation_moves_nothing() -> None:
    """What a rename that did not happen answers with.

    **Test steps:**

    * relocate through an empty relocation
    """
    key = ResourceKey(LIBRARY / "pack")

    assert KeyRelocation().relocate(key) == key


@mark.windows
def test_case_folds_on_windows_and_the_tail_keeps_its_own_spelling() -> None:
    """A differently-cased local ancestor still relocates, without respelling the rest of the name.

    **Test steps:**

    * relocate a key under the folder spelled in another case
    * check the tail's spelling
    """
    relocated = FOLDER_RENAME.relocate(ResourceKey(LIBRARY / "PACK" / "Member.rehu"))

    assert relocated.path == LIBRARY / "kit" / "Member.rehu"


# endregion


# region touches
@mark.parametrize(
    ("folder", "touched"),
    [
        (ResourceKey(LIBRARY), True),
        (ResourceKey(LIBRARY / "pack"), True),
        (ResourceKey(LIBRARY / "pack" / "member"), True),
        (ResourceKey(LIBRARY / "kit" / "member"), True),
        (ResourceKey(LIBRARY / "other"), False),
        (ResourceKey(LIBRARY / "pack2"), False),
    ],
)
def test_a_folder_rename_touches_its_parent_itself_its_subtree_and_its_destination(
    folder: ResourceKey, touched: bool
) -> None:
    """A listing of any of these would show something different after the rename.

    **Test steps:**

    * ask each folder whether the folder rename touches it
    """
    assert FOLDER_RENAME.touches(folder) is touched


def test_an_empty_relocation_touches_nothing() -> None:
    """Nothing moved, so no listing needs reading again.

    **Test steps:**

    * ask an empty relocation about a folder
    """
    assert not KeyRelocation().touches(ResourceKey(LIBRARY))


# endregion


# region to_local


def test_to_local_keeps_the_pairs_as_paths() -> None:
    """A holder of paths -- the cache, the Roots tree -- gets the rename back as a path relocation.

    **Test steps:**

    * turn a relocation back
    """
    assert FOLDER_RENAME.to_local() == Relocation(((LIBRARY / "pack", LIBRARY / "kit"),))


# endregion
