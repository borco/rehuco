"""Tests for resource keys: their identity rule and their path arithmetic (#413).

Pure arithmetic: nothing here touches a filesystem, so nothing is mocked either.
"""

from pathlib import Path
from typing import Final

from pytest import mark, raises
from rehuco_core import ResourceKey

LIBRARY: Final = Path("/fake/library").absolute()


# region ResourceKey identity
def test_a_local_key_refuses_a_relative_path() -> None:
    """A key is a location on this machine, which a relative path is not.

    **Test steps:**

    * build a key from a relative path
    """
    with raises(ValueError, match="absolute"):
        ResourceKey(Path("pack") / "info.rehu")


def test_a_local_key_refuses_a_dot_dot_and_drops_a_dot() -> None:
    """``pack/../pack`` would be a second key for one place, and resolving it would touch the disk; ``.`` costs nothing
    because the path itself drops it.

    **Test steps:**

    * build a key from a path with ``..``
    * build one from a path with ``.`` and compare it with the plain spelling
    """
    with raises(ValueError, match=r"\.\."):
        ResourceKey(LIBRARY / "pack" / ".." / "kit")

    assert ResourceKey(LIBRARY / "." / "pack") == ResourceKey(LIBRARY / "pack")


@mark.windows
def test_local_keys_fold_case_on_windows() -> None:
    """Two spellings of one file on a case-insensitive filesystem are one key, and hash alike.

    **Test steps:**

    * compare and hash two keys differing only in case
    * check the key keeps the spelling it was given
    """
    upper = ResourceKey(LIBRARY / "Pack" / "INFO.rehu")
    lower = ResourceKey(LIBRARY / "pack" / "info.rehu")

    assert upper == lower
    assert hash(upper) == hash(lower)
    assert upper.name == "INFO.rehu"


@mark.linux
def test_local_keys_keep_case_on_linux() -> None:
    """A case-sensitive filesystem keeps ``Pack`` and ``pack`` apart.

    **Test steps:**

    * compare two keys differing only in case
    """
    assert ResourceKey(LIBRARY / "Pack") != ResourceKey(LIBRARY / "pack")


# endregion


# region arithmetic
def test_local_key_arithmetic_follows_its_path() -> None:
    """Every operation answers what the same operation on the path answers.

    **Test steps:**

    * read name, stem, parent and parts
    * derive a sibling and a child
    """
    key = ResourceKey(LIBRARY / "pack" / "info.rehu")

    assert key.name == "info.rehu"
    assert key.stem == "info"
    assert key.parent == ResourceKey(LIBRARY / "pack")
    assert key.parts == (LIBRARY / "pack" / "info.rehu").parts
    assert key.with_name("other.rehu") == ResourceKey(LIBRARY / "pack" / "other.rehu")
    assert ResourceKey(LIBRARY).joinpath("pack", "info.rehu") == key


# endregion


# region is_at_or_beneath
@mark.parametrize(
    ("candidate", "ancestor", "beneath"),
    [
        (ResourceKey(LIBRARY / "pack"), ResourceKey(LIBRARY / "pack"), True),
        (ResourceKey(LIBRARY / "pack" / "member" / "info.rehu"), ResourceKey(LIBRARY / "pack"), True),
        (ResourceKey(LIBRARY / "pack2" / "info.rehu"), ResourceKey(LIBRARY / "pack"), False),
        (ResourceKey(LIBRARY), ResourceKey(LIBRARY / "pack"), False),
    ],
)
def test_is_at_or_beneath_compares_whole_components(
    candidate: ResourceKey, ancestor: ResourceKey, beneath: bool
) -> None:
    """A key itself and anything inside it count; a sibling whose name merely starts alike, or a parent, never do.

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
    assert ResourceKey(LIBRARY / "pack" / "info.rehu").is_at_or_beneath(ResourceKey(LIBRARY / "PACK"))


# endregion


# region text


def test_a_local_key_reads_as_its_path() -> None:
    """A key's text is its path as spelled -- what a dock was named by before keys, so saved layouts still match.

    **Test steps:**

    * read a key as text
    """
    path = LIBRARY / "Pack" / "info.rehu"

    assert str(ResourceKey(path)) == str(path)


# endregion
