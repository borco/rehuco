"""Tests for the tool locator: inspecting a path, detecting installs, and resolving the one a feature uses (#521)."""

import os
from pathlib import Path
from typing import override

from rehuco_core import ToolCandidate, ToolLocator, ToolNotRunnableError, ToolStatus, Version, shared_tool_locator

from rehuco_core_tests.external_tools.sample_tool import SAMPLE, SampleTool, make_install


class ScriptedTool(SampleTool):
    """The sample tool, reporting the versions a test scripted for each folder and listing its own search folders.

    :param versions: the version each folder's copy reports; a missing folder's copy does not run.
    :param folders: the folders ``search_folders`` offers, with their sources.
    """

    def __init__(self, versions: dict[Path, Version | None], folders: list[tuple[str, Path]] | None = None) -> None:
        self.versions = versions
        self.folders = folders or []
        self.reads = 0

    @override
    def search_folders(self) -> list[tuple[str, Path]]:
        return self.folders

    @override
    def read_version(self, folder: Path) -> Version | None:
        self.reads += 1
        if folder not in self.versions:
            raise ToolNotRunnableError("It did not run.")
        return self.versions[folder]


def test_inspecting_a_path_with_no_install_is_missing_with_its_path(tmp_path: Path) -> None:
    """The page can say where it looked.

    **Test steps:**

    * inspect a path that holds nothing
    * verify the status and that the reason names the path
    """
    candidate = ToolLocator().inspect(ScriptedTool({}), tmp_path / "nowhere")

    assert candidate.status is ToolStatus.MISSING
    assert str(tmp_path / "nowhere") in candidate.reason
    assert not candidate.is_usable


def test_inspecting_judges_the_version_the_copy_reports(tmp_path: Path) -> None:
    """The candidate carries the folder the pick resolved to, the version, and the status the descriptor judged.

    **Test steps:**

    * inspect an install by its folder's parent, so it resolves to the ``bin``
    * verify the folder, source, version and status
    """
    folder = make_install(tmp_path / "build" / "bin")

    candidate = ToolLocator().inspect(ScriptedTool({folder: (5, 0)}), tmp_path / "build")

    assert (candidate.folder, candidate.source, candidate.version, candidate.status) == (
        folder,
        "Custom",
        (5, 0),
        ToolStatus.USABLE,
    )


def test_a_copy_that_does_not_run_is_not_runnable_with_the_reason(tmp_path: Path) -> None:
    """The reason the descriptor gave reaches the candidate.

    **Test steps:**

    * inspect an install whose version read raises
    * verify the status and reason
    """
    folder = make_install(tmp_path / "bin")

    candidate = ToolLocator().inspect(ScriptedTool({}), folder)

    assert (candidate.status, candidate.reason) == (ToolStatus.NOT_RUNNABLE, "It did not run.")


def test_the_version_is_read_once_until_an_executable_changes(tmp_path: Path) -> None:
    """Running the tool is the cost, so a copy already read is not run again -- until an update changes a file.

    **Test steps:**

    * inspect the same install twice, and verify one read
    * change an executable's modification time and inspect again
    * verify a second read
    """
    folder = make_install(tmp_path / "bin")
    tool = ScriptedTool({folder: (5, 0)})
    locator = ToolLocator()

    locator.inspect(tool, folder)
    locator.inspect(tool, folder, "PATH")
    assert tool.reads == 1

    executable = tool.executable_files(folder)[0]
    os.utime(executable, ns=(1_000_000_000, 1_000_000_000))
    locator.inspect(tool, folder)
    assert tool.reads == 2


def test_the_source_is_the_askers_not_the_cached_readings(tmp_path: Path) -> None:
    """A copy found on ``PATH`` and later browsed to is the same reading, shown under each name.

    **Test steps:**

    * inspect one install under two sources
    * verify each candidate carries the source it was asked under
    """
    folder = make_install(tmp_path / "bin")
    tool = ScriptedTool({folder: (5, 0)})
    locator = ToolLocator()

    assert locator.inspect(tool, folder, "PATH").source == "PATH"
    assert locator.inspect(tool, folder, "Custom").source == "Custom"


def test_detecting_lists_every_install_usable_first_and_newest_first(tmp_path: Path) -> None:
    """Every install is listed, the unusable after the usable, so a user sees why one was not chosen.

    **Test steps:**

    * make installs of 5.0, 6.0, 3.0 (too old) and 5.1 (blocklisted), plus a folder with no install
    * detect
    * verify the order, and that the folder with no install is not listed
    """
    folders = {version: make_install(tmp_path / str(version) / "bin") for version in ((5, 0), (6, 0), (3, 0), (5, 1))}
    tool = ScriptedTool(
        {folder: version for version, folder in folders.items()},
        [
            ("PATH", folders[(5, 0)]),
            ("winget", folders[(6, 0)]),
            ("scoop", folders[(3, 0)]),
            ("PATH", folders[(5, 1)]),
            ("PATH", tmp_path / "empty"),
        ],
    )

    found = ToolLocator().detect(tool)

    assert [candidate.version for candidate in found] == [(6, 0), (5, 0), (5, 1), (3, 0)]
    assert [candidate.status for candidate in found] == [
        ToolStatus.USABLE,
        ToolStatus.USABLE,
        ToolStatus.BLOCKLISTED,
        ToolStatus.TOO_OLD,
    ]
    assert found[0].source == "winget"


def test_detecting_lists_one_install_found_twice_once(tmp_path: Path) -> None:
    """``PATH`` and a package manager's folder may be the same install.

    **Test steps:**

    * offer one folder under two sources, once spelled through ``..``
    * verify one candidate, under the first source
    """
    folder = make_install(tmp_path / "bin")
    tool = ScriptedTool({folder: (5, 0)}, [("PATH", folder), ("winget", tmp_path / "bin" / ".." / "bin")])

    found = ToolLocator().detect(tool)

    assert [candidate.source for candidate in found] == ["PATH"]


def test_resolving_takes_the_chosen_path_even_when_unusable(tmp_path: Path) -> None:
    """A chosen path is the user's word and is judged as it is, so its reason can be shown.

    **Test steps:**

    * make a 3.0 install that is chosen, and a 6.0 one found earlier
    * resolve with the chosen path
    * verify the chosen one is what came back, with its status
    """
    newest = make_install(tmp_path / "newest")
    old = make_install(tmp_path / "chosen")
    tool = ScriptedTool({newest: (6, 0), old: (3, 0)})
    found = ToolLocator().detect(ScriptedTool({newest: (6, 0)}, [("PATH", newest)]))

    candidate = ToolLocator().resolve(tool, str(old), found)

    assert candidate is not None
    assert (candidate.version, candidate.status) == ((3, 0), ToolStatus.TOO_OLD)


def test_resolving_automatic_takes_the_best_found_earlier_and_searches_for_nothing(tmp_path: Path) -> None:
    """An empty path is the newest usable copy among those already found; no folder is looked at.

    **Test steps:**

    * resolve with no chosen path over a list holding a usable and an unusable copy
    * verify the usable one came back and no version was read
    """
    usable = ToolCandidate(make_install(tmp_path / "a"), "PATH", ToolStatus.USABLE, (5, 0))
    old = ToolCandidate(tmp_path / "b", "PATH", ToolStatus.TOO_OLD, (3, 0))
    tool = ScriptedTool({})

    assert ToolLocator().resolve(tool, "", [old, usable]) == usable
    assert tool.reads == 0


def test_resolving_automatic_refuses_a_copy_found_earlier_that_is_gone(tmp_path: Path) -> None:
    """A copy uninstalled since, or on a share that is down, must not read as usable: a scan under it would total
    ``0`` over files it never read.

    **Test steps:**

    * make an install, record it as found, then remove its executables
    * resolve with no chosen path
    * verify the copy comes back missing, with a reason naming its folder, and is not usable
    """
    folder = make_install(tmp_path / "gone")
    tool = ScriptedTool({})
    found = ToolCandidate(folder, "PATH", ToolStatus.USABLE, (6, 0))
    for file in tool.executable_files(folder):
        file.unlink()

    candidate = ToolLocator().resolve(tool, "", [found])

    assert candidate is not None
    assert candidate.status is ToolStatus.MISSING
    assert not candidate.is_usable
    assert str(folder) in candidate.reason


def test_resolving_automatic_with_nothing_usable_finds_nothing(tmp_path: Path) -> None:
    """An unusable copy is kept in the list but is never what an empty path resolves to.

    **Test steps:**

    * resolve with no chosen path over a list holding only a copy that is too old, and over an empty one
    * verify nothing is chosen
    """
    old = ToolCandidate(tmp_path / "old", "PATH", ToolStatus.TOO_OLD, (3, 0))

    assert ToolLocator().resolve(ScriptedTool({}), "", [old]) is None
    assert ToolLocator().resolve(ScriptedTool({})) is None


def test_verifying_keeps_the_installs_still_there_and_reads_no_version(tmp_path: Path) -> None:
    """A start checks that what was found is still installed, nothing more.

    **Test steps:**

    * store two installs, then remove one's executables
    * verify them
    * verify only the other is kept, and no version was read
    """
    kept = make_install(tmp_path / "kept")
    gone = make_install(tmp_path / "gone")
    tool = ScriptedTool({})
    stored = [
        ToolCandidate(gone, "PATH", ToolStatus.USABLE, (5, 0)),
        ToolCandidate(kept, "winget", ToolStatus.USABLE, (6, 0)),
    ]
    for file in tool.executable_files(gone):
        file.unlink()

    assert ToolLocator().verify(tool, stored) == [stored[1]]
    assert tool.reads == 0


def test_an_install_that_vanishes_between_resolving_and_reading_is_missing(tmp_path: Path) -> None:
    """A share that drops, or an uninstall, can take the executables after the folder was resolved.

    **Test steps:**

    * resolve a folder whose executables are not there to be read
    * inspect it
    * verify it is missing, naming the path, and was never run
    """

    class Vanishing(ScriptedTool):
        """The sample tool, whose folder resolves but holds nothing."""

        @override
        def resolve_folder(self, path: Path) -> Path | None:
            return path

    tool = Vanishing({})

    candidate = ToolLocator().inspect(tool, tmp_path)

    assert candidate.status is ToolStatus.MISSING
    assert str(tmp_path) in candidate.reason
    assert tool.reads == 0


def test_the_shared_locator_is_one_object() -> None:
    """Every feature shares one cache of versions already read.

    **Test steps:**

    * ask for the shared locator twice, from a cleared cache
    * verify one real locator came back both times
    """
    shared_tool_locator.cache_clear()
    try:
        assert shared_tool_locator() is shared_tool_locator()
        assert isinstance(shared_tool_locator(), ToolLocator)
    finally:
        shared_tool_locator.cache_clear()


def test_verifying_keeps_a_candidate_as_stored_when_its_folder_still_holds_the_tool(tmp_path: Path) -> None:
    """The default re-check reads nothing: a copy still there is kept exactly as it was, one gone is dropped (#580).

    **Test steps:**

    * verify a stored copy whose folder holds the tool and one whose folder is empty
    * verify the first is returned unchanged and the second is not
    """
    there = ToolCandidate(make_install(tmp_path / "there", SAMPLE.EXECUTABLES), "PATH", ToolStatus.USABLE, (5, 0))
    (tmp_path / "gone").mkdir()
    gone = ToolCandidate(tmp_path / "gone", "PATH", ToolStatus.USABLE, (5, 0))

    assert ToolLocator().verify(SAMPLE, [there, gone]) == [there]
