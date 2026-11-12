"""Tests for adding a root to a ``.rehuco``: a new ``.rehuroot`` beside it or where chosen, its label, layouts and
fallbacks, and the root file names it takes (#371, #514, #577, #578).

Split from ``test_rehuco_file.py``, whose helpers it uses.
"""

from pathlib import Path
from uuid import UUID

import pytest
from pytest import fixture, mark, param
from rehuco_core import RehucoFile, RehurootFile

from rehuco_core_tests.test_rehuco_file import ROOT_IDS, labels, read_json, write_home


@fixture
def home(tmp_path: Path) -> RehucoFile:
    """A loaded copy of ``HOME``: three roots, one in a subfolder.

    :param tmp_path: pytest's temporary directory.
    :returns: the loaded file.
    """
    return RehucoFile.load(write_home(tmp_path))


# region Adding a root


def test_add_root_makes_a_root_file_beside_the_rehuco(tmp_path: Path, home: RehucoFile) -> None:
    """A root added from a folder is a new ``.rehuroot`` beside the ``.rehuco``, under a fresh id and the default
    layouts, written by the next save.

    **Test steps:**

    * add a root by location
    * verify its row, label, fresh id and file, and that nothing is written yet
    * save, and verify the root file's content and the reference to it
    """
    row = home.add_root("//nas/data/courses")
    added = home.roots[row]

    assert (row, added.label, added.location) == (3, "courses", "//nas/data/courses")
    assert added.root_id.version == 4
    assert added.root_id not in {UUID(root_id) for root_id in ROOT_IDS}
    file = tmp_path / "nas--data--courses.rehuroot"
    assert added.file == file
    assert not file.exists()

    home.save()

    assert read_json(file) == {
        "format_version": 1,
        "id": str(added.root_id),
        "label": "courses",
        "location": "//nas/data/courses",
        "layouts": {"*": ["*"]},
        "fallbacks": {},
    }
    assert read_json(tmp_path / "home.rehuco")["roots"][3] == {"file": "nas--data--courses.rehuroot"}


def test_add_root_names_its_file_after_the_location_whatever_the_label(tmp_path: Path, home: RehucoFile) -> None:
    """A label given is the root's, and changes nothing about its file's name.

    **Test steps:**

    * add a root labelled with characters no file name keeps
    * verify the label as given and the file named after the location
    """
    row = home.add_root("//nas/data_14t/DATA1/Courses", "Courses: 2026")

    assert home.roots[row].label == "Courses: 2026"
    assert home.roots[row].file == tmp_path / "nas--data_14t--DATA1--Courses.rehuroot"


def test_a_location_that_sanitizes_to_nothing_names_its_file_root(tmp_path: Path, home: RehucoFile) -> None:
    """A location with nothing a file name keeps still gets a file.

    **Test steps:**

    * add a root whose location holds only characters no file name keeps
    * verify its file is ``root.rehuroot``
    """
    row = home.add_root("//???/???", "courses")

    assert home.roots[row].file == tmp_path / "root.rehuroot"


def test_a_root_file_name_already_taken_gets_a_suffix(tmp_path: Path, home: RehucoFile) -> None:
    """A file already on disk, or a name another reference holds, is never written over.

    **Test steps:**

    * put a file named for ``//nas/data/courses`` beside the ``.rehuco``, then add that root and, after an unreadable
      root's file is deleted, a root whose location names that file
    * verify the files are suffixed ``(2)``
    """
    (tmp_path / "nas--data--courses.rehuroot").write_text("someone else's", encoding="utf-8")
    first = home.add_root("//nas/data/courses")
    (tmp_path / "discs.rehuroot").unlink()
    reloaded = RehucoFile.load(tmp_path / "home.rehuco")
    second = reloaded.add_root("//discs", "more")

    assert home.roots[first].file == tmp_path / "nas--data--courses (2).rehuroot"
    assert reloaded.roots[second].file == tmp_path / "discs (2).rehuroot"


def test_adding_a_root_needs_the_rehuco_saved_first() -> None:
    """A root file goes beside the ``.rehuco``, so a never-saved one has nowhere to put it.

    **Test steps:**

    * add a root to a new file and verify ``ValueError``
    """
    with pytest.raises(ValueError, match="saved first"):
        RehucoFile.new().add_root("//nas/data/courses")


@mark.parametrize(
    "location, label",
    [
        param("//nas/data/foo", "foo", id="folder"),
        param("//nas/data/foo/", "foo", id="trailing-separator"),
        param("//nas", "nas", id="server"),
        param("//", "//", id="nothing-else"),
    ],
)
def test_default_label_is_the_locations_last_segment(location: str, label: str) -> None:
    """With no label given, a root is labelled by its location's last segment.

    **Test steps:**

    * take the default label of each location
    * verify the segment, or the whole text when there is none
    """
    assert RehucoFile.default_label(location) == label


def test_clashing_labels_get_a_suffix(home: RehucoFile) -> None:
    """A label already in use, in any case, gets the first free numbered suffix.

    **Test steps:**

    * add three roots whose default label is ``Tutorials``, ``tutorials`` and ``tutorials``
    * verify the suffixes count on from 2
    """
    home.add_root("//other/a/Tutorials")
    home.add_root("//other/b/tutorials")
    home.add_root("//other/c/tutorials")

    assert labels(home)[3:] == ["Tutorials (2)", "tutorials (3)", "tutorials (4)"]


def test_a_location_already_a_root_is_refused(home: RehucoFile) -> None:
    """The same location twice is one root, whatever its case.

    **Test steps:**

    * add a root at ``HOME``'s first location, upper-cased
    * verify ``ValueError`` and three roots still
    """
    with pytest.raises(ValueError, match="Already a root"):
        home.add_root("//NAS/data/tutorials")
    assert home.count == 3


# endregion


# region A root's layouts, fallbacks and file (#578)


def test_add_root_takes_layouts_fallbacks_and_a_chosen_file(tmp_path: Path, home: RehucoFile) -> None:
    """A root can start with layouts and fallbacks of its own, in a file put where the user chose -- here a folder two
    catalogs both reach, named from the ``.rehuco`` by a relative path.

    **Test steps:**

    * add a root with layouts, fallbacks and a file in a sibling folder, and save
    * verify the root, the root file's maps, and the reference spelled relative to the ``.rehuco``
    """
    shared = tmp_path.parent / f"{tmp_path.name}-shared"
    shared.mkdir()
    chosen = shared / "courses.rehuroot"
    row = home.add_root(
        "//nas/data/courses", layouts={"tutorial": ("{title}",)}, fallbacks={"title": "Untitled"}, file=chosen
    )
    home.save()

    assert home.roots[row].file == chosen
    assert dict(home.roots[row].layouts) == {"tutorial": ("{title}",)}
    saved = read_json(chosen)
    assert (saved["layouts"], saved["fallbacks"]) == ({"tutorial": ["{title}"]}, {"title": "Untitled"})
    assert read_json(tmp_path / "home.rehuco")["roots"][3] == {"file": f"../{shared.name}/courses.rehuroot"}


def test_a_chosen_root_file_given_relative_goes_beside_the_rehuco(tmp_path: Path, home: RehucoFile) -> None:
    """A relative root file is meant beside the ``.rehuco``, never wherever the process runs.

    **Test steps:**

    * add a root choosing ``mine.rehuroot``, and save
    * verify the root file beside the ``.rehuco`` and the reference naming it there
    """
    row = home.add_root("//nas/data/courses", file=Path("mine.rehuroot"))
    home.save()

    assert home.roots[row].file == tmp_path / "mine.rehuroot"
    assert (tmp_path / "mine.rehuroot").exists()
    assert read_json(tmp_path / "home.rehuco")["roots"][3] == {"file": "mine.rehuroot"}


@mark.parametrize(
    "name",
    [param("courses.rehuroot", id="a-file-there"), param("discs.rehuroot", id="a-file-listed")],
)
def test_add_root_refuses_a_chosen_file_already_taken(tmp_path: Path, home: RehucoFile, name: str) -> None:
    """A chosen root file is never written over, nor named twice.

    **Test steps:**

    * put a file named ``courses.rehuroot`` beside the ``.rehuco``
    * add a root choosing that file, or one ``HOME`` already lists
    * verify ``ValueError`` and three roots still
    """
    (tmp_path / "courses.rehuroot").write_text("someone else's", encoding="utf-8")

    with pytest.raises(ValueError, match="already there"):
        home.add_root("//nas/data/courses", file=tmp_path / name)
    assert home.count == 3


def test_free_root_file_avoids_the_paths_it_is_given(tmp_path: Path, home: RehucoFile) -> None:
    """The root file a new root would get skips names about to be taken by other new roots as well.

    **Test steps:**

    * ask for ``courses`` with ``courses.rehuroot`` and ``courses (2).rehuroot`` taken, in another case
    * verify ``courses (3).rehuroot``; then ask for a name a reference holds and verify its suffix
    """
    taken = (tmp_path / "Courses.rehuroot", tmp_path / "courses (2).rehuroot")

    assert home.free_root_file("courses", taken) == tmp_path / "courses (3).rehuroot"
    assert home.free_root_file("tutorials") == tmp_path / "tutorials (2).rehuroot"


def test_free_root_file_needs_the_rehuco_saved_first() -> None:
    """A never-saved ``.rehuco`` has no folder to name a root file in.

    **Test steps:**

    * ask a new file for a root file name and verify ``ValueError``
    """
    with pytest.raises(ValueError, match="saved first"):
        RehucoFile.new().free_root_file("courses")


def test_set_root_layouts_writes_only_that_root_file(tmp_path: Path, home: RehucoFile) -> None:
    """A root's layouts and fallbacks are its ``.rehuroot``'s; the ``.rehuco`` and the other roots stay as they are.

    **Test steps:**

    * set the first root's layouts and fallbacks and save
    * verify the root shows them, its file holds them, and the ``.rehuco`` and another root file are untouched
    """
    rehuco_text = (tmp_path / "home.rehuco").read_text(encoding="utf-8")
    other = (tmp_path / "discs.rehuroot").read_text(encoding="utf-8")

    home.set_root_layouts(0, {"tutorial": ("{authors}/{title}",)}, {"authors": "Unknown"})
    home.save()

    assert dict(home.roots[0].layouts) == {"tutorial": ("{authors}/{title}",)}
    assert dict(home.roots[0].fallbacks) == {"authors": "Unknown"}
    saved = read_json(tmp_path / "tutorials.rehuroot")
    assert (saved["layouts"], saved["fallbacks"]) == ({"tutorial": ["{authors}/{title}"]}, {"authors": "Unknown"})
    assert (tmp_path / "home.rehuco").read_text(encoding="utf-8") == rehuco_text
    assert (tmp_path / "discs.rehuroot").read_text(encoding="utf-8") == other


def test_set_root_layouts_refuses_an_unreadable_root(tmp_path: Path) -> None:
    """There is no file to write an unreadable root's layouts into.

    **Test steps:**

    * load ``HOME`` with its ``discs`` file missing
    * verify setting that root's layouts raises ``ValueError``, and a row outside the file ``IndexError``
    """
    path = write_home(tmp_path)
    (tmp_path / "discs.rehuroot").unlink()
    rehuco = RehucoFile.load(path)

    with pytest.raises(ValueError, match="could not be read"):
        rehuco.set_root_layouts(1, {"*": ("*",)}, {})
    with pytest.raises(IndexError):
        rehuco.set_root_layouts(3, {"*": ("*",)}, {})


# endregion


# region Adding an existing root file (#578)


def test_an_existing_root_file_joins_as_it_is_named_from_the_rehuco(tmp_path: Path, home: RehucoFile) -> None:
    """A root file another catalog made joins with its own id, label, location and layouts; the save names it from
    the ``.rehuco`` and leaves the file as it was.

    **Test steps:**

    * save a root file in a sibling folder, add it, and save
    * verify the root, the reference, and the root file's bytes unchanged
    """
    shared = tmp_path.parent / f"{tmp_path.name}-nas"
    shared.mkdir()
    made = RehurootFile.new(shared / "music.rehuroot", "//nas/data/Music", "Music", layouts={"*": ("{title}",)})
    made.save()
    before = made.path.read_bytes()

    row = home.add_root_file(made)
    home.save()

    root = home.roots[row]
    assert (row, root.root_id, root.label, root.location) == (3, made.root_id, "Music", "//nas/data/Music")
    assert dict(root.layouts) == {"*": ("{title}",)}
    assert read_json(tmp_path / "home.rehuco")["roots"][3] == {"file": f"../{shared.name}/music.rehuroot"}
    assert made.path.read_bytes() == before


def test_adding_an_existing_root_file_refuses_what_the_catalog_has(tmp_path: Path, home: RehucoFile) -> None:
    """A file already listed, and a file of a root already listed -- by id or by location -- are each refused, and
    nothing is added.

    **Test steps:**

    * add the catalog's own first root file, a copy of it, and a new file at its location
    * verify each ``ValueError`` and three roots still
    """
    copy = tmp_path / "copy.rehuroot"
    copy.write_bytes((tmp_path / "tutorials.rehuroot").read_bytes())
    same_place = RehurootFile.new(tmp_path / "same.rehuroot", "//NAS/data/tutorials", "same")
    same_place.save()

    with pytest.raises(ValueError, match="Already a root file"):
        home.add_root_file(RehurootFile.load(tmp_path / "tutorials.rehuroot"))
    for path in (copy, same_place.path):
        with pytest.raises(ValueError, match="Already a root of this catalog"):
            home.add_root_file(RehurootFile.load(path))
    assert home.count == 3


def test_adding_an_existing_root_file_needs_the_rehuco_saved_first(tmp_path: Path) -> None:
    """A reference is named from the ``.rehuco``'s folder, which a never-saved one has not.

    **Test steps:**

    * add a root file to a new catalog and verify ``ValueError``
    """
    with pytest.raises(ValueError, match="saved first"):
        RehucoFile.new().add_root_file(RehurootFile.new(tmp_path / "x.rehuroot", "//nas/x", "x"))


# endregion
