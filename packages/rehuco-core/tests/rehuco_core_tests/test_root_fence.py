"""Tests for the fence a scan keeps around a catalog's other roots (#498): matched by identity, spelled where identity
is unusable, and stat'ed only where a directory's name could be a root's.

Identities come from real folders under ``tmp_path``; the module's ``os`` is replaced only where a test needs a stat to
fail, report no inode, or be counted.
"""

import logging
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from pytest import LogCaptureFixture, mark, param
from pytest_mock import MockerFixture
from rehuco_core import CatalogRoot, root_path_key
from rehuco_core.root_fence import RootFence

from rehuco_core_tests.real_links import directory_link


def other_root(path: Path, *, reachable: bool | None = True) -> CatalogRoot:
    """Another root of the catalog, as the cache holds it.

    :param path: its folder.
    :param reachable: what the cache last knew of it.
    :returns: the row.
    """
    return CatalogRoot(uuid4(), path.name, path, 0, False, reachable, None)


def identity(path: Path) -> tuple[int, int]:
    """A real folder's ``(st_dev, st_ino)``.

    :param path: the folder.
    :returns: its identity.
    """
    status = os.stat(path)
    return status.st_dev, status.st_ino


def counted_stat(mocker: MockerFixture, **status: int) -> Mock:
    """Replace the fence's ``os.stat``: the real one, or a fixed answer when ``status`` is given.

    :param mocker: pytest-mock fixture.
    :param status: the ``stat`` fields to answer with, instead of the disk's.
    :returns: the stand-in, to count what was stat'ed.
    """
    stat = mocker.Mock(side_effect=os.stat) if not status else mocker.Mock(return_value=SimpleNamespace(**status))
    mocker.patch("rehuco_core.root_fence.os", SimpleNamespace(stat=stat))
    return stat


# region Reading the other roots


def test_reading_a_root_keeps_its_identity_spelling_and_name(tmp_path: Path) -> None:
    """A reachable root is known three ways: its identity, its spelled key, and the name a directory must carry.

    **Test steps:**

    * read the fence of one real root folder
    * verify its identity, spelling and name, and that not every directory needs a stat
    """
    (tmp_path / "Lib").mkdir()
    root = other_root(tmp_path / "Lib")

    fence = RootFence.read([root])

    assert fence.identities == {identity(tmp_path / "Lib"): root.root_id}
    assert fence.spellings == {root_path_key(tmp_path / "Lib"): root.root_id}
    assert fence.names == frozenset({"lib"})
    assert not fence.every_directory


def test_a_root_with_no_name_makes_every_directory_a_candidate(tmp_path: Path) -> None:
    """A drive's top has no last component a directory could carry, so every directory is stat'ed.

    **Test steps:**

    * read the fence of the drive (or filesystem) top and a named root
    * verify every directory is a candidate
    """
    (tmp_path / "lib").mkdir()

    fence = RootFence.read([other_root(Path(Path.cwd().anchor)), other_root(tmp_path / "lib")])

    assert fence.every_directory
    assert "lib" in fence.names


@mark.windows
def test_a_share_root_makes_every_directory_a_candidate_without_being_read(mocker: MockerFixture) -> None:
    """A share's top has no name either; held unreachable, it is spelled only and never stat'ed.

    **Test steps:**

    * read the fence of an unreachable share root
    * verify every directory is a candidate, its spelling kept, and nothing stat'ed
    """
    stat = counted_stat(mocker)
    share = other_root(Path("\\\\nas\\share"), reachable=False)

    fence = RootFence.read([share])

    assert fence.every_directory
    assert (fence.spellings, fence.identities) == ({root_path_key(share.path): share.root_id}, {})
    stat.assert_not_called()


def test_an_unreachable_root_is_spelled_only_and_never_stated(tmp_path: Path, mocker: MockerFixture) -> None:
    """A root the cache holds offline is not read, so a switched-off share's timeout is never waited out.

    **Test steps:**

    * read the fence of a root held unreachable
    * verify it has a spelling and a name, no identity, and nothing was stat'ed
    """
    stat = counted_stat(mocker)
    root = other_root(tmp_path / "away", reachable=False)

    fence = RootFence.read([root])

    assert fence.spellings == {root_path_key(root.path): root.root_id}
    assert (fence.identities, fence.names) == ({}, frozenset({"away"}))
    stat.assert_not_called()


@mark.parametrize("name", [param("missing", id="not-there"), param("bad\x00name", id="unstatable-name")])
def test_a_root_that_will_not_stat_is_spelled_only(tmp_path: Path, caplog: LogCaptureFixture, name: str) -> None:
    """A root that cannot be read is matched by its spelling alone, and the log says so.

    **Test steps:**

    * read the fence of a root that does not exist, and of one whose name no stat accepts
    * verify it is spelled, has no identity, and was logged
    """
    root = other_root(tmp_path / name)

    with caplog.at_level(logging.INFO, logger="rehuco_core.root_fence"):
        fence = RootFence.read([root])

    assert fence.spellings == {root_path_key(root.path): root.root_id}
    assert not fence.identities
    assert "by spelling only" in caplog.text


def test_a_root_reporting_no_inode_is_spelled_only(
    tmp_path: Path, mocker: MockerFixture, caplog: LogCaptureFixture
) -> None:
    """Some SMB servers answer a zero inode, which would match every other such folder: such a root is spelled only.

    **Test steps:**

    * make every stat answer inode 0, and read the fence of a real root
    * verify it is spelled, has no identity, and was logged
    """
    (tmp_path / "lib").mkdir()
    counted_stat(mocker, st_dev=5, st_ino=0)
    root = other_root(tmp_path / "lib")

    with caplog.at_level(logging.INFO, logger="rehuco_core.root_fence"):
        fence = RootFence.read([root])

    assert fence.spellings == {root_path_key(root.path): root.root_id}
    assert not fence.identities
    assert "no file identity" in caplog.text


# endregion

# region Matching a directory


def test_a_directory_is_matched_by_identity_whatever_its_path(tmp_path: Path) -> None:
    """Another root reached under a different path -- a mapped letter, a ``subst`` drive -- is still that root.

    **Test steps:**

    * make a folder ``a/lib``, a link ``m`` to ``a`` standing in for a mapped letter, and a folder ``b/lib``
    * read the fence of a root spelled ``m/lib``
    * verify ``a/lib`` matches it though its spelled key is not the root's, and ``b/lib`` does not
    """
    (tmp_path / "a" / "lib").mkdir(parents=True)
    (tmp_path / "b" / "lib").mkdir(parents=True)
    root = other_root(directory_link(tmp_path / "m", tmp_path / "a") / "lib")
    fence = RootFence.read([root])

    assert root_path_key(tmp_path / "a" / "lib") not in fence.spellings
    assert fence.match(tmp_path / "a" / "lib") == root.root_id
    assert fence.match(tmp_path / "b" / "lib") is None


@mark.windows
def test_a_case_variant_of_a_root_is_that_root(tmp_path: Path) -> None:
    """Spelled in another case, a root folder is the same folder.

    **Test steps:**

    * read the fence of a real root, and match its path in upper case
    * verify the match
    """
    (tmp_path / "lib").mkdir()
    root = other_root(tmp_path / "lib")

    assert RootFence.read([root]).match(tmp_path / "LIB") == root.root_id


def test_a_directory_whose_name_no_root_carries_is_never_stated(tmp_path: Path, mocker: MockerFixture) -> None:
    """The name prefilter: a stat per directory costs a third more walk time on the NAS, so only a candidate name
    pays it.

    **Test steps:**

    * read the fence of a real root ``lib``, then count stats
    * match a directory named otherwise, then one named ``LIB``
    * verify only the second was stat'ed, and neither matched
    """
    (tmp_path / "lib").mkdir()
    (tmp_path / "x" / "LIB").mkdir(parents=True)
    fence = RootFence.read([other_root(tmp_path / "lib")])
    stat = counted_stat(mocker)

    assert fence.match(tmp_path / "x") is None
    stat.assert_not_called()
    assert fence.match(tmp_path / "x" / "LIB") is None
    stat.assert_called_once_with(tmp_path / "x" / "LIB", follow_symlinks=False)


def test_every_directory_is_stated_where_a_root_has_no_name(tmp_path: Path, mocker: MockerFixture) -> None:
    """With a nameless root among the others, no name can rule a directory out.

    **Test steps:**

    * build a fence that knows one identity and stats every directory
    * match a directory of any name; verify it was stat'ed
    """
    (tmp_path / "anything").mkdir()
    fence = RootFence({(0, 1): uuid4()}, {}, frozenset(), True)
    stat = counted_stat(mocker)

    assert fence.match(tmp_path / "anything") is None
    stat.assert_called_once()


def test_a_root_known_by_spelling_alone_needs_no_stat(mocker: MockerFixture) -> None:
    """A root spelled only still matches its own spelling; with no identity known, nothing else is stat'ed.

    **Test steps:**

    * build a fence that knows one root by spelling only
    * verify its spelling matches, another folder of its name does not, and nothing was stat'ed
    """
    stat = counted_stat(mocker)
    root_id = uuid4()
    spelled = Path(Path.cwd().anchor) / "away" / "lib"
    fence = RootFence({}, {root_path_key(spelled): root_id}, frozenset({"lib"}), False)

    assert fence.match(spelled) == root_id
    assert fence.match(spelled.parent / "x" / "lib") is None
    stat.assert_not_called()


def test_a_directory_that_will_not_stat_is_left_to_the_walk(tmp_path: Path) -> None:
    """A candidate that vanished between the listing and the stat is no root; the walk's own listing reports it.

    **Test steps:**

    * build a fence with a known identity, and match a candidate name that does not exist
    * verify no match and no error
    """
    fence = RootFence({(0, 1): uuid4()}, {}, frozenset({"gone"}), False)

    assert fence.match(tmp_path / "gone") is None


def test_a_root_spelled_through_a_link_is_matched_at_its_real_folder(tmp_path: Path) -> None:
    """A root whose spelling is a link carries its target's name too, so a walk meeting the real folder stats it.

    **Test steps:**

    * make a folder ``a/real`` and a root spelled as a link ``alias`` to it
    * read the fence; verify it knows both names, and the real folder matches the root
    """
    (tmp_path / "a" / "real").mkdir(parents=True)
    root = other_root(directory_link(tmp_path / "alias", tmp_path / "a" / "real"))

    fence = RootFence.read([root])

    assert fence.names == frozenset({"alias", "real"})
    assert fence.match(tmp_path / "a" / "real") == root.root_id


def test_the_scans_own_root_is_matched_through_its_link_only_when_asked(tmp_path: Path) -> None:
    """A walk never queues a link, so a candidate is stat'ed without following one; the root a scan starts from may
    be spelled through one, and is matched as what it points at.

    **Test steps:**

    * make a root ``lib`` and a link named ``lib`` elsewhere pointing at it
    * verify the link matches the root with ``by_name=False`` and not with the default
    """
    (tmp_path / "lib").mkdir()
    (tmp_path / "x").mkdir()
    link = directory_link(tmp_path / "x" / "lib", tmp_path / "lib")
    root = other_root(tmp_path / "lib")
    fence = RootFence.read([root])

    assert fence.match(link, by_name=False) == root.root_id
    assert fence.match(link) is None


# endregion
