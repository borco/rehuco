"""Tests for the external-tool descriptor: judging a version, and finding the folder a user picked (#521)."""

import os
from pathlib import Path
from typing import override

from pytest import MonkeyPatch, mark, param
from rehuco_core import ToolCandidate, ToolStatus, Version, best_candidate, version_text

from rehuco_core_tests.external_tools.sample_tool import SAMPLE, SampleTool, make_install
from rehuco_core_tests.real_links import directory_link, symlink


@mark.parametrize(
    ("version", "status"),
    [
        param((6, 2), ToolStatus.USABLE, id="the-newest-tested"),
        param((6, 2, 9), ToolStatus.USABLE, id="a-later-patch-of-the-newest-tested"),
        param((6, 3), ToolStatus.UNTESTED, id="the-next-minor"),
        param((4, 0), ToolStatus.USABLE, id="the-minimum"),
        param((7, 0), ToolStatus.UNTESTED, id="newer-than-any-tested"),
        param((3, 9), ToolStatus.TOO_OLD, id="older-than-the-minimum"),
        param((5, 1), ToolStatus.BLOCKLISTED, id="a-blocked-version"),
        param((5, 2), ToolStatus.USABLE, id="next-to-a-blocked-version"),
        param(None, ToolStatus.UNTESTED, id="a-version-nothing-could-read"),
    ],
)
def test_a_version_is_judged_by_the_minimum_the_blocklist_and_the_newest_tested(
    version: Version | None, status: ToolStatus
) -> None:
    """A version is refused only for a reason the descriptor knows; anything it cannot judge is allowed.

    **Test steps:**

    * judge each version
    * verify the status, and that only a usable or untested copy is one a feature may use
    """
    judged, reason = SAMPLE.judge(version)

    assert judged is status
    assert bool(reason) == (status is not ToolStatus.USABLE)
    assert judged.is_usable == (status in (ToolStatus.USABLE, ToolStatus.UNTESTED))


def test_a_blocked_version_says_why() -> None:
    """The reason on screen is the one the descriptor recorded.

    **Test steps:**

    * judge the blocked version
    * verify its reason
    """
    assert SAMPLE.judge((5, 1)) == (ToolStatus.BLOCKLISTED, "5.1 crashes on start.")


def test_a_too_old_version_names_the_minimum() -> None:
    """The user is told which version is enough.

    **Test steps:**

    * judge a version below the minimum
    * verify the reason names the minimum
    """
    assert "4.0" in SAMPLE.judge((3, 0))[1]


@mark.parametrize(
    ("version", "text"),
    [param((7, 1, 5), "7.1.5", id="numbers"), param(None, "unknown version", id="unreadable")],
)
def test_a_version_reads_as_dotted_numbers(version: Version | None, text: str) -> None:
    """The page shows a version in the form a vendor does.

    **Test steps:**

    * spell a version and a missing one
    * verify the text
    """
    assert version_text(version) == text


def test_a_folder_holding_every_executable_resolves_to_itself(tmp_path: Path) -> None:
    """Picking the folder, or any one executable in it, names the install.

    **Test steps:**

    * make an install
    * resolve its folder, and each of its executables
    * verify each answers the folder
    """
    folder = make_install(tmp_path / "bin")

    assert SAMPLE.resolve_folder(folder) == folder
    for file in SAMPLE.executable_files(folder):
        assert SAMPLE.resolve_folder(file) == folder


def test_an_unpacked_archives_root_resolves_to_its_bin(tmp_path: Path) -> None:
    """Builds unpack to a root holding a ``bin``, which is what people browse to.

    **Test steps:**

    * make an install under ``bin``
    * resolve the root
    * verify the answer is the ``bin``
    """
    folder = make_install(tmp_path / "build" / "bin")

    assert SAMPLE.resolve_folder(tmp_path / "build") == folder


@mark.parametrize(
    "present",
    [param(("alpha",), id="only-one-of-two-executables"), param((), id="an-empty-folder")],
)
def test_a_folder_missing_an_executable_resolves_to_nothing(tmp_path: Path, present: tuple[str, ...]) -> None:
    """An install holding only some of the tool is not the tool.

    **Test steps:**

    * make a folder holding some of the executables
    * resolve it, and a path that does not exist
    * verify both answer nothing
    """
    folder = make_install(tmp_path / "bin", present)

    assert SAMPLE.resolve_folder(folder) is None
    assert SAMPLE.resolve_folder(tmp_path / "nowhere") is None


def test_the_search_starts_with_path_and_expands_the_descriptors_patterns(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """``PATH`` is searched on every OS, then wherever the descriptor says this one keeps the tool.

    **Test steps:**

    * name two ``PATH`` entries and a pattern matching two folders
    * verify the folders come back in that order, the pattern's sorted, each with its source
    """
    (tmp_path / "apps" / "b").mkdir(parents=True)
    (tmp_path / "apps" / "a").mkdir()

    class Searching(SampleTool):
        """The sample, with a place to look."""

        @override
        def search_patterns(self) -> tuple[tuple[str, str], ...]:
            return (("apps", str(tmp_path / "apps" / "*")),)

    monkeypatch.setenv("PATH", f"{tmp_path / 'one'}{os.pathsep}{tmp_path / 'two'}")

    assert Searching().search_folders() == [
        ("PATH", tmp_path / "one"),
        ("PATH", tmp_path / "two"),
        ("apps", tmp_path / "apps" / "a"),
        ("apps", tmp_path / "apps" / "b"),
    ]


def test_a_candidate_round_trips_through_its_stored_form() -> None:
    """What is stored for a found install is what comes back, version included.

    **Test steps:**

    * store a candidate with and without a version
    * read each back
    * verify they are equal
    """
    for candidate in (
        ToolCandidate(Path("/opt/ffmpeg/bin"), "winget", ToolStatus.USABLE, (7, 1, 1)),
        ToolCandidate(Path("/x"), "PATH", ToolStatus.UNTESTED, None, "The version could not be read."),
    ):
        assert ToolCandidate.from_stored(candidate.to_stored()) == candidate


@mark.parametrize(
    "raw",
    [
        param(None, id="not-an-object"),
        param({}, id="empty"),
        param({"folder": "", "source": "x", "status": "usable", "version": [], "reason": ""}, id="no-folder"),
        param({"folder": "/x", "source": "x", "status": "weird", "version": [], "reason": ""}, id="unknown-status"),
        param({"folder": "/x", "source": "x", "status": "usable", "version": "7", "reason": ""}, id="version-text"),
        param({"folder": "/x", "source": "x", "status": "usable", "version": ["7"], "reason": ""}, id="version-words"),
        param({"folder": "/x", "source": 3, "status": "usable", "version": [], "reason": ""}, id="source-not-text"),
    ],
)
def test_a_malformed_stored_entry_reads_as_nothing(raw: object) -> None:
    """The settings file may come from another build or a hand edit; a bad entry costs only itself.

    **Test steps:**

    * read each malformed entry
    * verify none yields a candidate
    """
    assert ToolCandidate.from_stored(raw) is None


def test_the_best_candidate_is_the_newest_usable_one() -> None:
    """Unusable copies never win, however new, and among equals the first listed does.

    **Test steps:**

    * pick from a list holding an old usable, a newer usable, a newest that is blocklisted and a tie
    * verify the newer usable copy, then nothing for a list with none usable and for an empty one
    """
    old = ToolCandidate(Path("/old"), "PATH", ToolStatus.USABLE, (5, 0))
    newer = ToolCandidate(Path("/newer"), "PATH", ToolStatus.USABLE, (6, 0))
    tie = ToolCandidate(Path("/tie"), "winget", ToolStatus.USABLE, (6, 0))
    blocked = ToolCandidate(Path("/blocked"), "PATH", ToolStatus.BLOCKLISTED, (9, 0))

    assert best_candidate([old, newer, blocked, tie]) is newer
    assert best_candidate([blocked]) is None
    assert best_candidate([]) is None


def test_a_folder_of_links_resolves_to_the_install_they_point_at(tmp_path: Path) -> None:
    """winget puts links to an install's executables in a ``Links`` folder on ``PATH``; that is the same install, so it
    is listed once, under its real folder.

    **Test steps:**

    * make an install and a folder of links to each of its executables
    * resolve the links folder
    * verify the answer is the install's own folder
    """
    install = make_install(tmp_path / "package" / "bin")
    links = tmp_path / "Links"
    links.mkdir()
    for file in SAMPLE.executable_files(install):
        symlink(links / file.name, file)

    assert SAMPLE.resolve_folder(links) == install


def test_a_linked_folder_keeps_its_own_path(tmp_path: Path) -> None:
    """scoop's ``current`` is a link to the versioned folder; its path is kept, so a choice of it survives an update.

    **Test steps:**

    * make an install under a versioned folder and a ``current`` link to that folder
    * resolve ``current``
    * verify the answer is ``current``'s own ``bin``
    """
    make_install(tmp_path / "9.0.2" / "bin")
    current = directory_link(tmp_path / "current", tmp_path / "9.0.2")

    assert SAMPLE.resolve_folder(current) == current / "bin"


def test_a_link_to_a_folder_that_is_no_whole_install_keeps_the_links_folder(tmp_path: Path) -> None:
    """A link whose target sits apart from the other executables names no install there, so the folder holding all of
    them is the install.

    **Test steps:**

    * make a folder holding the second executable and a link to a first executable kept alone elsewhere
    * resolve the folder
    * verify the answer is that folder
    """
    lone = make_install(tmp_path / "lone", SampleTool.EXECUTABLES[:1])
    folder = make_install(tmp_path / "mixed", SampleTool.EXECUTABLES[1:])
    first = SAMPLE.executable_files(lone)[0]
    symlink(folder / first.name, first)

    assert SAMPLE.resolve_folder(folder) == folder


def test_a_folder_of_scoop_shims_resolves_to_the_install_they_launch(tmp_path: Path) -> None:
    """scoop puts a launcher for each executable on ``PATH``, beside a ``.shim`` file naming the real one; that is the
    same install, so it is listed once, under its real folder.

    **Test steps:**

    * make an install and a shims folder holding a launcher and a ``.shim`` file per executable
    * resolve the shims folder
    * verify the answer is the install's own folder
    """
    install = make_install(tmp_path / "apps" / "tool" / "current" / "bin")
    shims = make_install(tmp_path / "shims")
    for file in SAMPLE.executable_files(install):
        (shims / file.name).with_suffix(".shim").write_text(f'path = "{file}"\n', encoding="utf-8")

    assert SAMPLE.resolve_folder(shims) == install


@mark.parametrize(
    "shim_text",
    [
        param("args = -x\n", id="no-path-line"),
        param(None, id="no-shim-file"),
    ],
)
def test_a_launcher_naming_no_install_is_the_install_itself(tmp_path: Path, shim_text: str | None) -> None:
    """An executable with no ``.shim`` beside it, or one that names nothing, is taken as it is.

    **Test steps:**

    * make an install, with a ``.shim`` file naming no path or with none
    * resolve the folder
    * verify the answer is that folder
    """
    folder = make_install(tmp_path / "bin")
    if shim_text is not None:
        SAMPLE.executable_files(folder)[0].with_suffix(".shim").write_text(shim_text, encoding="utf-8")

    assert SAMPLE.resolve_folder(folder) == folder


def test_an_unreadable_shim_file_is_ignored(tmp_path: Path) -> None:
    """A ``.shim`` that is not text costs nothing: the launcher is taken as it is.

    **Test steps:**

    * make an install whose first executable has a ``.shim`` file of bytes that are not UTF-8
    * resolve the folder
    * verify the answer is that folder
    """
    folder = make_install(tmp_path / "bin")
    SAMPLE.executable_files(folder)[0].with_suffix(".shim").write_bytes(b"\xff\xfe\x00bad")

    assert SAMPLE.resolve_folder(folder) == folder
