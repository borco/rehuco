"""Tests for the natural sort keys ([[reference-images#image-identity]])."""

from pytest import mark
from rehuco_core import natural_path_sort_key, natural_sort_key


def test_digit_runs_compare_as_numbers() -> None:
    """``file-2`` sorts before ``file-10``, which lexical order would reverse.

    **Test steps:**

    * sort ``file-10``, ``file-2``, ``file-1`` by the key
    * verify the numeric order
    """
    assert sorted(["file-10", "file-2", "file-1"], key=natural_sort_key) == ["file-1", "file-2", "file-10"]


def test_a_numeric_tie_puts_fewer_leading_zeros_first() -> None:
    """The issue's own example: ``image8 < image9 < image009 < image10`` -- a raw-string fallback would
    put ``009`` before ``9``.

    **Test steps:**

    * sort the four names given shuffled
    * verify that exact order
    """
    names = ["image009", "image10", "image8", "image9"]

    assert sorted(names, key=natural_sort_key) == ["image8", "image9", "image009", "image10"]


def test_non_digit_runs_compare_case_insensitively() -> None:
    """``Beta`` sorts between ``alpha`` and ``gamma`` rather than before both as ASCII would.

    **Test steps:**

    * sort ``gamma``, ``Beta``, ``alpha``
    * verify the case-blind order
    """
    assert sorted(["gamma", "Beta", "alpha"], key=natural_sort_key) == ["alpha", "Beta", "gamma"]


@mark.parametrize(
    ("first", "second"),
    [
        ("a/x.jpg", "a.jpg"),
        ("a/b/c.jpg", "a/b.jpg"),
        ("vol2/page1.jpg", "vol10/page1.jpg"),
        ("vol1/page9.jpg", "vol1/page10.jpg"),
    ],
)
def test_paths_compare_component_by_component(first: str, second: str) -> None:
    """A path key compares its ``/`` components in turn, so a folder sorts before a same-prefix name and
    each component is itself natural.

    **Test steps:**

    * compare the two paths' keys
    * verify ``first`` sorts before ``second``
    """
    assert natural_path_sort_key(first) < natural_path_sort_key(second)
