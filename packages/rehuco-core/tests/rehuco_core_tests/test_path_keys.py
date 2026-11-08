"""Tests for the path key a chosen name or a matched root or catalog file is compared by (#629).

Pure string work: nothing here touches a filesystem, so nothing is mocked either.
"""

from pathlib import Path

from rehuco_core import path_key


def test_a_path_key_folds_case_on_every_platform() -> None:
    """``Blender`` and ``blender`` are one name wherever the file may land, not only on Windows.

    **Test steps:**

    * key one path in two cases
    * verify the keys match
    """
    assert path_key(Path("lib") / "Blender.rehuroot") == path_key(Path("LIB") / "blender.rehuroot")


def test_a_path_key_normalizes_the_spelling() -> None:
    """A trailing separator and a ``.`` part are spellings of the same path; another name is another key.

    **Test steps:**

    * key a path, the same path with ``.`` and a trailing separator, and a sibling
    * verify the first two match and the sibling differs
    """
    assert path_key("lib/./Krita/") == path_key("lib/Krita") != path_key("lib/Krita2")


def test_a_path_key_keeps_sharp_s_apart_from_ss() -> None:
    """The fold is case only, as the filesystems fold it: ``Straße`` and ``Strasse`` are two names.

    **Test steps:**

    * key both spellings
    * verify they differ
    """
    assert path_key("Straße") != path_key("Strasse")
