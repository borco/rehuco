"""Tests for RootPlanner: what picked ``.rehuroot`` files and folders would add to a catalog as roots (#578).

Every test works on real files in ``tmp_path``: a catalog saved there, folders made there, and root files whose
locations name this machine's folders, so they resolve as they would on the owner's machine.
"""

from pathlib import Path

from pytest import fixture
from pytest_mock import MockerFixture
from rehuco_core import (
    CandidateKind,
    MappedRoot,
    RehucoFile,
    RehurootFile,
    RootPick,
    RootPlanner,
    location_of,
    location_stem,
    path_key,
)
from rehuco_core.root_candidates import ALREADY_A_ROOT, SAME_LOCATION_ABOVE, SAME_ROOT_ABOVE

UNREACHABLE: str = "//nohost-578/share/far"
"""A location no machine here resolves."""


@fixture(name="home")
def fixture_home(tmp_path: Path) -> RehucoFile:
    """A catalog saved in ``tmp_path/catalog``, with one root, ``tmp_path/lib``, mapped here.

    :param tmp_path: pytest's temporary directory.
    :returns: the catalog.
    """
    (tmp_path / "catalog").mkdir()
    (tmp_path / "lib").mkdir()
    file = RehucoFile.new()
    file.save(tmp_path / "catalog" / "home.rehuco")
    file.add_root(location_of(tmp_path / "lib"), "lib")
    file.save()
    return file


def mapped(home: RehucoFile, tmp_path: Path) -> tuple[MappedRoot, ...]:
    """The catalog's one root, mapped to its folder.

    :param home: the catalog.
    :param tmp_path: pytest's temporary directory.
    :returns: the root.
    """
    root = home.roots[0]
    return (MappedRoot(root.root_id, root.label, root.location, tmp_path / "lib", file=root.file),)


def folder(tmp_path: Path, name: str) -> Path:
    """A folder made under ``tmp_path``.

    :param tmp_path: pytest's temporary directory.
    :param name: its name, ``/`` making levels.
    :returns: the folder.
    """
    path = tmp_path / name
    path.mkdir(parents=True)
    return path


def root_file(path: Path, location: str, label: str = "shared") -> Path:
    """A ``.rehuroot`` saved at ``path``.

    :param path: where.
    :param location: its location.
    :param label: its label.
    :returns: the path.
    """
    RehurootFile.new(path, location, label, layouts={"tutorial": "{title}"}, fallbacks={"title": "?"}).save()
    return path


def test_folders_become_new_roots_with_root_files_named_after_their_locations(tmp_path: Path, home: RehucoFile) -> None:
    """Sibling folders each become a root, labelled by its folder, its root file beside the ``.rehuco`` named after its
    location -- a label typed changes the label only, a taken name is suffixed.

    **Test steps:**

    * make the root file the first folder's location names, and pick three sibling folders, one with a label typed
    * verify the kinds, labels, locations, folders, root files, and that all can be added
    """
    picks = (
        RootPick(folder(tmp_path, "t/Blender")),
        RootPick(folder(tmp_path, "u/blender")),
        RootPick(folder(tmp_path, "t/Krita"), label="Painting"),
    )
    stems = [location_stem(location_of(pick.path)) for pick in picks]
    (tmp_path / "catalog" / f"{stems[0]}.rehuroot").write_text("someone else's", encoding="utf-8")

    lines = RootPlanner.plan(home, picks, mapped(home, tmp_path))

    catalog = tmp_path / "catalog"
    assert [line.kind for line in lines] == [CandidateKind.FOLDER] * 3
    assert [line.label for line in lines] == ["Blender", "blender", "Painting"]
    assert stems[0] is not None and stems[0].endswith("--t--Blender")
    assert [line.location for line in lines] == [location_of(pick.path) for pick in picks]
    assert [line.folder for line in lines] == [pick.path for pick in picks]
    assert {path_key(line.root_file.parent) for line in lines} == {path_key(catalog)}
    assert [line.root_file.name for line in lines] == [
        f"{stems[0]} (2).rehuroot",
        f"{stems[1]}.rehuroot",
        f"{stems[2]}.rehuroot",
    ]
    assert all(line.addable for line in lines)


def test_a_root_file_joins_with_what_it_holds_resolved_here_or_unmapped(tmp_path: Path, home: RehucoFile) -> None:
    """A picked ``.rehuroot`` keeps its label, location, layouts and fallbacks; where this machine finds it is its
    location resolved -- or nowhere, when it cannot be, and it joins unmapped.

    **Test steps:**

    * pick a root file whose location is a folder here, and one whose location resolves nowhere
    * verify both lines
    """
    near = root_file(tmp_path / "near.rehuroot", location_of(folder(tmp_path, "near")), "Near")
    far = root_file(tmp_path / "far.rehuroot", UNREACHABLE, "Far")

    lines = RootPlanner.plan(home, (RootPick(near), RootPick(far)), mapped(home, tmp_path))
    first, second = lines[0], lines[1]

    assert (first.kind, first.label, first.root_file, first.folder) == (
        CandidateKind.FILE,
        "Near",
        near,
        tmp_path / "near",
    )
    assert (first.layouts, first.fallbacks) == ({"tutorial": "{title}"}, {"title": "?"})
    assert (second.label, second.location, second.folder, second.addable) == ("Far", UNREACHABLE, None, True)


def test_a_folder_a_picked_root_file_resolves_to_is_left_out_whichever_came_first(
    tmp_path: Path, home: RehucoFile
) -> None:
    """The folder and the root file naming it are one root: only the file stays.

    **Test steps:**

    * pick a folder and the root file whose location it is, in both orders
    * verify only the file's line, each time
    """
    picked = folder(tmp_path, "shared")
    file = root_file(tmp_path / "shared.rehuroot", location_of(picked))

    for picks in ((RootPick(picked), RootPick(file)), (RootPick(file), RootPick(picked))):
        lines = RootPlanner.plan(home, picks, mapped(home, tmp_path))
        assert [(line.kind, line.root_file) for line in lines] == [(CandidateKind.FILE, file)]


def test_what_cannot_be_added_is_kept_and_says_why(tmp_path: Path, home: RehucoFile) -> None:
    """Each problem is a line of its own, not a refusal of the list.

    **Test steps:**

    * pick a root file that is not JSON, the catalog's own root file, a copy of it under another name, a file whose
      location is the catalog's root, the catalog's root folder -- which that file stands for, so it is left out -- a
      folder inside it, and a path that is no folder
    * verify each line's problem
    """
    broken = tmp_path / "broken.rehuroot"
    broken.write_text("not json", encoding="utf-8")
    listed = home.roots[0].file
    assert listed is not None
    copy = tmp_path / "copy.rehuroot"
    copy.write_bytes(listed.read_bytes())
    same_place = root_file(tmp_path / "same.rehuroot", location_of(tmp_path / "lib"))
    inside = folder(tmp_path, "lib/inner")
    loose = tmp_path / "loose.txt"
    loose.write_text("", encoding="utf-8")
    picks = [RootPick(path) for path in (broken, listed, copy, same_place, tmp_path / "lib", inside, loose)]

    lines = RootPlanner.plan(home, picks, mapped(home, tmp_path))

    problems = [line.problem for line in lines]
    assert problems[0].startswith("The root file cannot be read: Not JSON")
    assert (lines[0].label, lines[0].folder) == ("broken", None)
    assert problems[1] == "This catalog already lists this root file."
    assert problems[2] == "This catalog already lists this root, through another root file."
    assert problems[3] == ALREADY_A_ROOT
    assert problems[4] == f"{inside} is inside the root lib ({tmp_path / 'lib'})"
    assert problems[5] == f"Not a folder: {loose}"
    assert len(lines) == 6
    assert not any(line.addable for line in lines)


def test_a_folder_overlapping_one_picked_before_it_is_refused(tmp_path: Path, home: RehucoFile) -> None:
    """Two picks are compared as roots are: a folder inside one picked earlier cannot be added; the earlier one can.

    **Test steps:**

    * pick a folder, then a folder inside it
    * verify the first can be added and the second says it is inside the first
    """
    outer = folder(tmp_path, "outer")
    inner = folder(tmp_path, "outer/inner")

    lines = RootPlanner.plan(home, (RootPick(outer), RootPick(inner)), mapped(home, tmp_path))
    first, second = lines[0], lines[1]

    assert first.addable
    assert second.problem == f"{inner} is inside the root outer ({outer})"


def test_a_root_file_typed_is_used_unless_it_is_taken_or_no_root_file(tmp_path: Path, home: RehucoFile) -> None:
    """A folder's root file may be put anywhere -- a share both catalogs reach -- but never over a file, onto another
    pick's or root's, or under another extension.

    **Test steps:**

    * pick folders whose root files are typed: one free, one an existing file, one the free one again, one the
      catalog's root's, one not a ``.rehuroot``, and one for a folder already a root
    * verify the free one is used, the others refused, and the last keeps its own reason
    """
    shared = folder(tmp_path, "nas")
    existing = tmp_path / "nas" / "taken.rehuroot"
    existing.write_text("someone else's", encoding="utf-8")
    listed = home.roots[0].file
    picks = (
        RootPick(folder(tmp_path, "a"), root_file=shared / "a.rehuroot"),
        RootPick(folder(tmp_path, "b"), root_file=existing),
        RootPick(folder(tmp_path, "c"), root_file=shared / "a.rehuroot"),
        RootPick(folder(tmp_path, "d"), root_file=listed),
        RootPick(folder(tmp_path, "e"), root_file=shared / "e.json"),
        RootPick(tmp_path / "lib", root_file=shared / "lib.rehuroot"),
    )

    lines = RootPlanner.plan(home, picks, mapped(home, tmp_path))

    assert lines[0].root_file == shared / "a.rehuroot" and lines[0].addable
    assert [line.problem for line in lines[1:4]] == [
        f"A root file is already there: {existing}",
        f"A root file is already there: {shared / 'a.rehuroot'}",
        f"A root file is already there: {listed}",
    ]
    assert lines[4].problem == f"A root file ends in .rehuroot: {shared / 'e.json'}"
    assert (lines[5].problem, lines[5].root_file) == (ALREADY_A_ROOT, shared / "lib.rehuroot")


def test_a_root_picked_twice_under_two_files_or_two_picks_at_one_location_are_refused_after_the_first(
    tmp_path: Path, home: RehucoFile
) -> None:
    """Two root files carrying one id, or two picks at one location, would list one root twice: the later one is
    refused, and only the first is added.

    **Test steps:**

    * pick a root file, a copy of it under another name, and a third root file of its own at the same location
      spelled in another case, none resolving here
    * verify the first can be added and the other two each say why not
    """
    shared = root_file(tmp_path / "shared.rehuroot", "//nohost-578/share/far", "Shared")
    copy = tmp_path / "copy.rehuroot"
    copy.write_bytes(shared.read_bytes())
    twin = root_file(tmp_path / "twin.rehuroot", "//NOHOST-578/share/FAR", "Twin")

    lines = RootPlanner.plan(home, [RootPick(path) for path in (shared, copy, twin)], mapped(home, tmp_path))

    assert [line.addable for line in lines] == [True, False, False]
    assert lines[1].problem == SAME_ROOT_ABOVE
    assert lines[2].problem == SAME_LOCATION_ABOVE
    assert lines[0].root is not None and lines[0].root.root_id == RehurootFile.load(shared).root_id


def test_a_root_file_typed_as_a_bare_name_goes_beside_the_catalog(tmp_path: Path, home: RehucoFile) -> None:
    """A relative root file is meant beside the ``.rehuco``, never wherever the process runs.

    **Test steps:**

    * pick a folder with ``mine.rehuroot`` typed as its root file
    * verify the root file planned is beside the catalog
    """
    line = RootPlanner.plan(
        home, (RootPick(folder(tmp_path, "x"), root_file=Path("mine.rehuroot")),), mapped(home, tmp_path)
    )[0]

    assert path_key(line.root_file) == path_key(tmp_path / "catalog" / "mine.rehuroot")
    assert line.addable


def test_a_label_changes_nothing_about_the_root_file_name(tmp_path: Path, home: RehucoFile) -> None:
    """A label with nothing a file name keeps still gets a root file, named after the location.

    **Test steps:**

    * pick a folder labelled only with characters no file name keeps
    * verify its root file is the one its location names, beside the catalog
    """
    picked = folder(tmp_path, "x")

    line = RootPlanner.plan(home, (RootPick(picked, label="???"),), mapped(home, tmp_path))[0]

    assert path_key(line.root_file) == path_key(tmp_path / "catalog" / f"{location_stem(location_of(picked))}.rehuroot")


def test_an_unreachable_root_is_compared_as_spelled_only(
    mocker: MockerFixture, tmp_path: Path, home: RehucoFile
) -> None:
    """A root known unreachable is not resolved through links, which would only wait out its share's timeout.

    **Test steps:**

    * pick a folder, the catalog's root said to be unreachable
    * verify the comparison through links was told to skip it
    """
    find = mocker.patch("rehuco_core.root_candidates.RootOverlap.find_resolved", return_value=None)
    roots = mapped(home, tmp_path)

    RootPlanner.plan(home, (RootPick(folder(tmp_path, "x")),), roots, {roots[0].root_id})

    assert find.call_args.args[2] == {roots[0].root_id}
