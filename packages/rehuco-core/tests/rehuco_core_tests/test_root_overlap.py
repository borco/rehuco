"""Tests for whether two roots of one ``.rehuco`` overlap (#498): spelled, and resolved through links.

The spelled comparison is pure string work, so most tests compare Windows spellings through ``ntpath`` on every
platform; the resolved one follows links with :func:`os.path.realpath`, replaced here by a table, since CI has no share
to map a drive letter to -- and checked against a real link where the platform allows one.
"""

import ntpath
import posixpath
from pathlib import Path
from types import SimpleNamespace
from typing import Final
from unittest.mock import Mock
from uuid import uuid4

from pytest import fixture, mark, param
from pytest_mock import MockerFixture
from rehuco_core import MappedRoot, RootOverlap, root_path_key

from rehuco_core_tests.mapped_roots import location_at
from rehuco_core_tests.real_links import directory_link

RESOLVED: Final = {
    "T:\\lib": "\\\\Nas\\share\\lib",
    "T:\\lib\\sub": "\\\\Nas\\share\\lib\\sub",
    "U:\\other": "\\\\Nas\\share\\other",
}
"""What each mapped spelling resolves to; a spelling not here resolves to itself."""

BROKEN: Final = "X:\\broken"
"""A spelling whose resolution raises -- a path ``realpath`` refuses."""


def root(path: str, label: str = "") -> MappedRoot:
    """A root at ``path``, kept exactly as spelled.

    :param path: the folder.
    :param label: its label; the folder's name when omitted.
    :returns: the root.
    """
    return MappedRoot(uuid4(), label or ntpath.basename(path.rstrip("\\")), location_at(Path(path)), Path(path))


def resolve(path: str) -> str:
    """:data:`RESOLVED`'s answer for ``path``.

    :param path: the spelling.
    :returns: what it resolves to.
    :raises OSError: for :data:`BROKEN`.
    """
    if path == BROKEN:
        raise OSError(f"cannot resolve {path}")
    return RESOLVED.get(path, path)


@fixture(name="windows_paths")
def fixture_windows_paths(mocker: MockerFixture) -> Mock:
    """Compare paths the way ``ntpath`` does, resolving through :func:`resolve`.

    :param mocker: pytest-mock fixture.
    :returns: the ``realpath`` stand-in, to check what was resolved.
    """
    realpath = mocker.Mock(side_effect=resolve)
    mocker.patch(
        "rehuco_core.root_overlap.os_path",
        SimpleNamespace(normcase=ntpath.normcase, normpath=ntpath.normpath, sep=ntpath.sep, realpath=realpath),
    )
    return realpath


# region As spelled


@mark.usefixtures("windows_paths")
@mark.parametrize(
    ("existing", "candidate", "encloses"),
    [
        param("D:\\tutorials", "D:\\tutorials\\blender", True, id="inside"),
        param("D:\\tutorials\\blender", "D:\\tutorials", False, id="containing"),
        param("D:\\Tutorials", "d:/TUTORIALS/blender/", True, id="case-and-separators"),
        param("D:\\", "D:\\x", True, id="drive-root"),
        param("\\\\nas\\share", "\\\\nas\\share\\lib", True, id="unc"),
    ],
)
def test_a_folder_inside_a_root_or_containing_one_overlaps_it(existing: str, candidate: str, encloses: bool) -> None:
    """Either direction is an overlap, compared normalized and case-folded, and the root's top counts as containing.

    **Test steps:**

    * compare a candidate with a root, Windows-style
    * verify the overlap names the root as stored, the candidate as spelled, and which contains which
    """
    stored = root(existing)

    overlap = RootOverlap.find(candidate, [root("Z:\\elsewhere"), stored])

    assert overlap == RootOverlap(stored, Path(candidate), encloses)


@mark.usefixtures("windows_paths")
@mark.parametrize(
    "candidate",
    [
        param("D:\\lib2", id="sibling-sharing-a-prefix"),
        param("D:\\li", id="prefix-of-the-root"),
        param("D:\\LIB", id="the-same-folder"),
        param("E:\\lib\\sub", id="another-drive"),
    ],
)
def test_a_sibling_or_the_same_folder_is_no_overlap(candidate: str) -> None:
    """Whole components are compared, so ``lib`` holds not ``lib2``; the same folder is a duplicate, not an overlap.

    **Test steps:**

    * compare each candidate with a root ``D:\\lib``
    * verify none overlaps
    """
    assert RootOverlap.find(candidate, [root("D:\\lib")]) is None


def test_a_case_variant_is_another_folder_where_paths_do_not_fold_case(mocker: MockerFixture) -> None:
    """On POSIX paths, ``/data/Tutorials/x`` is not inside ``/data/tutorials``.

    **Test steps:**

    * compare paths the way ``posixpath`` does
    * verify the case variant does not overlap, and the true child does
    """
    mocker.patch("rehuco_core.root_overlap.os_path", posixpath)
    stored = MappedRoot(uuid4(), "tutorials", location_at(Path("/data/tutorials")), Path("/data/tutorials"))
    spelled = str(stored.path)  # built from the stored path, which a Windows host spells with backslashes

    assert RootOverlap.find(spelled.replace("tutorials", "Tutorials") + "/x", [stored]) is None
    assert RootOverlap.find(spelled + "/x", [stored]) is not None


@mark.usefixtures("windows_paths")
def test_a_root_path_key_folds_what_the_platform_folds() -> None:
    """Two spellings of one folder share a key; another folder does not.

    **Test steps:**

    * key two spellings of one folder and a sibling, Windows-style
    * verify the first two match and the sibling differs
    """
    assert root_path_key("D:/Lib/") == root_path_key("d:\\lib") != root_path_key("D:\\lib2")


@mark.parametrize(
    ("encloses", "message"),
    [
        param(True, "{other} is inside the root lib ({root})", id="inside"),
        param(False, "{other} contains the root lib ({root})", id="containing"),
    ],
)
def test_the_message_names_both_folders_as_spelled(encloses: bool, message: str) -> None:
    """The root by its label and stored path, the other folder as given -- never a resolved form.

    **Test steps:**

    * build an overlap each way
    * verify its message
    """
    stored = MappedRoot(uuid4(), "lib", location_at(Path("T:/lib")), Path("T:/lib"))
    other = Path("T:/lib/sub") if encloses else Path("T:/")

    assert RootOverlap(stored, other, encloses).message == message.format(other=other, root=stored.path)


@mark.parametrize(
    ("encloses", "message"),
    [
        param(True, "{other} is inside the root {root}", id="inside"),
        param(False, "{other} contains the root {root}", id="containing"),
    ],
)
def test_the_message_names_a_root_with_an_empty_label_by_its_folder_alone(encloses: bool, message: str) -> None:
    """A root whose label is empty is named by its stored path alone, with no empty name before it.

    **Test steps:**

    * build an overlap each way with a root labelled empty
    * verify its message
    """
    stored = MappedRoot(uuid4(), "", location_at(Path("T:/lib")), Path("T:/lib"))
    other = Path("T:/lib/sub") if encloses else Path("T:/")

    assert RootOverlap(stored, other, encloses).message == message.format(other=other, root=stored.path)


@mark.usefixtures("windows_paths")
def test_every_overlapping_pair_is_found_once_its_earlier_root_first() -> None:
    """A file opened nesting: each root against every earlier one, one overlap per pair, an unrelated root in none.

    **Test steps:**

    * hold an inner root, an unrelated one, and the root containing the first, in that order
    * verify one overlap: the inner root's, contained by the later outer one
    """
    inner, unrelated, outer = root("D:\\lib\\sub"), root("E:\\packs"), root("D:\\lib")

    assert RootOverlap.among([inner, unrelated, outer]) == (RootOverlap(inner, outer.path, False),)
    assert not RootOverlap.among([inner, unrelated])


# endregion

# region Through links


@mark.parametrize(
    ("existing", "candidate", "encloses"),
    [
        param("T:\\lib", "\\\\Nas\\share\\lib\\sub", True, id="share-inside-a-mapped-root"),
        param("\\\\Nas\\share\\lib\\sub", "T:\\lib", False, id="mapped-letter-containing-a-share-root"),
    ],
)
def test_a_mapped_drive_and_its_share_overlap_through_resolution(
    windows_paths: Mock, existing: str, candidate: str, encloses: bool
) -> None:
    """``T:\\lib`` is ``\\\\Nas\\share\\lib``: spelled they share nothing, resolved one contains the other -- and the
    overlap keeps both spellings, the letter included.

    **Test steps:**

    * compare a share path with a root on the drive mapped to it, both ways
    * verify the spelled comparison finds nothing and the resolved one finds the overlap, as spelled
    """
    del windows_paths
    stored = root(existing)

    assert RootOverlap.find(candidate, [stored]) is None
    overlap = RootOverlap.find_resolved(candidate, [stored])

    assert overlap == RootOverlap(stored, Path(candidate), encloses)
    assert overlap is not None and str(Path("T:\\lib")) in overlap.message


def test_a_root_that_will_not_resolve_takes_no_part(windows_paths: Mock) -> None:
    """A root whose resolution fails is neither raised nor compared, and the roots after it still are.

    **Test steps:**

    * compare a candidate with a root that refuses to resolve, then a share root it resolves into
    * verify the overlap is the share root's
    """
    del windows_paths
    broken, share = root(BROKEN), root("\\\\Nas\\share")

    assert RootOverlap.find_resolved("T:\\lib\\sub", [broken, share]) == RootOverlap(share, Path("T:\\lib\\sub"), True)


def test_a_candidate_that_will_not_resolve_meets_nothing(windows_paths: Mock) -> None:
    """A candidate whose resolution fails has nothing to compare, so no root is even resolved.

    **Test steps:**

    * compare a candidate that refuses to resolve with a root
    * verify no overlap, and only the candidate was resolved
    """
    assert RootOverlap.find_resolved(BROKEN, [root("\\\\Nas\\share")]) is None
    windows_paths.assert_called_once_with(BROKEN)


def test_a_root_in_skip_is_never_resolved(windows_paths: Mock) -> None:
    """A root known unreachable is not asked about, so its timeout is never waited out.

    **Test steps:**

    * compare a candidate with two roots, skipping the one that would overlap
    * verify no overlap, and ``realpath`` was never called with the skipped root's path
    """
    skipped, other = root("T:\\lib"), root("U:\\other")

    assert RootOverlap.find_resolved("\\\\Nas\\share\\lib\\sub", [skipped, other], skip={skipped.root_id}) is None
    assert all(call.args != ("T:\\lib",) for call in windows_paths.call_args_list)
    assert windows_paths.call_count == 2


def test_spelled_is_never_compared_with_resolved(windows_paths: Mock) -> None:
    """A root that will not resolve is not compared by its spelling against a resolved candidate.

    **Test steps:**

    * hold a root spelled as the share, which refuses to resolve
    * compare the mapped letter's child, which resolves into that share
    * verify no overlap
    """
    windows_paths.side_effect = lambda path: (
        RESOLVED.get(path, path) if path != "\\\\Nas\\share\\lib" else resolve(BROKEN)
    )

    assert RootOverlap.find_resolved("T:\\lib\\sub", [root("\\\\Nas\\share\\lib")]) is None


def test_every_pair_overlapping_through_links_is_found_reachable_roots_only(windows_paths: Mock) -> None:
    """``among_resolved`` pairs the roots as :meth:`~rehuco_core.RootOverlap.among` does, through resolution, and
    leaves a skipped root out of every pair.

    **Test steps:**

    * hold a mapped root, a share root inside it, and a skipped share root inside it too
    * verify one overlap, the share root's against the mapped one, and the skipped root never resolved
    """
    mapped, share, skipped = root("T:\\lib"), root("\\\\Nas\\share\\lib\\sub"), root("\\\\Nas\\share\\lib\\x")

    overlaps = RootOverlap.among_resolved([mapped, share, skipped], skip={skipped.root_id})

    assert overlaps == (RootOverlap(mapped, share.path, True),)
    assert all(call.args != (str(skipped.path),) for call in windows_paths.call_args_list)


def test_a_root_linked_into_another_overlaps_it_once_resolved(tmp_path: Path) -> None:
    """A real directory link into a root: its spelling is elsewhere, its resolution inside.

    **Test steps:**

    * make a root folder with a subfolder, and a link to the subfolder outside it
    * verify spelled finds nothing, resolved finds the link inside the root
    """
    (tmp_path / "lib" / "sub").mkdir(parents=True)
    link = directory_link(tmp_path / "alias", tmp_path / "lib" / "sub")
    stored = MappedRoot(uuid4(), "lib", location_at(tmp_path / "lib"), tmp_path / "lib")

    assert RootOverlap.find(link, [stored]) is None
    assert RootOverlap.find_resolved(link, [stored]) == RootOverlap(stored, link, True)


# endregion
