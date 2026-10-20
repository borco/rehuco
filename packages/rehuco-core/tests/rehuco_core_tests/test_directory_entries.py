"""Tests for what a walk may enter and take as a record (#498), on real entries of ``tmp_path``.

A declared listing answers whatever the test declares, so only a real directory read proves how the operating system
reports a junction or a symlink.
"""

import os
from pathlib import Path

from pytest import mark
from rehuco_core.directory_entries import is_plain_file, is_walkable_directory

from rehuco_core_tests.real_links import junction, symlink


def entries(folder: Path) -> dict[str, os.DirEntry[str]]:
    """Every entry of a real listing of ``folder``, by name.

    :param folder: the folder to list.
    :returns: the entries.
    """
    with os.scandir(folder) as listing:
        return {entry.name: entry for entry in listing}


def test_a_real_directory_is_walked_and_a_real_file_is_a_plain_file(tmp_path: Path) -> None:
    """The ordinary case: a folder is entered, a file is a record candidate, and neither is the other.

    **Test steps:**

    * make a folder and a file
    * verify the folder is walkable and not a plain file, the file the reverse
    """
    (tmp_path / "folder").mkdir()
    (tmp_path / "info.rehu").write_text("{}", encoding="utf-8")

    listed = entries(tmp_path)

    assert is_walkable_directory(listed["folder"]) and not is_plain_file(listed["folder"])
    assert is_plain_file(listed["info.rehu"]) and not is_walkable_directory(listed["info.rehu"])


@mark.windows
def test_a_junction_is_never_walked(tmp_path: Path) -> None:
    """A junction answers ``is_dir`` even without following links, which is why it is asked about on its own.

    **Test steps:**

    * make a junction to a folder
    * verify the listing calls it a directory not followed, and it is not walkable
    """
    (tmp_path / "target").mkdir()
    junction(tmp_path / "link", tmp_path / "target")

    entry = entries(tmp_path)["link"]

    assert entry.is_dir(follow_symlinks=False)
    assert not is_walkable_directory(entry)


def test_a_symlinked_directory_is_never_walked(tmp_path: Path) -> None:
    """A symlink to a folder is a link, whatever it points at.

    **Test steps:**

    * make a symlink to a folder
    * verify it is not walkable
    """
    (tmp_path / "target").mkdir()
    symlink(tmp_path / "link", tmp_path / "target")

    assert not is_walkable_directory(entries(tmp_path)["link"])


def test_a_symlinked_file_is_not_a_plain_file(tmp_path: Path) -> None:
    """A symlink to a ``.rehu`` would catalog its target a second time, so it is no record.

    **Test steps:**

    * make a symlink to a file
    * verify the listing calls it a file when followed, and it is not a plain file
    """
    (tmp_path / "info.rehu").write_text("{}", encoding="utf-8")
    symlink(tmp_path / "link.rehu", tmp_path / "info.rehu")

    entry = entries(tmp_path)["link.rehu"]

    assert entry.is_file()
    assert not is_plain_file(entry)
