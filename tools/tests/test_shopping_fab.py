"""Tests for the tool that adds a Fab results page's free listings to the library (#687)."""

import ctypes
import sys
from pathlib import Path
from typing import Final

from pytest import CaptureFixture, mark

from tools.shopping_fab import (
    ADDED,
    LISTING_URL,
    NOT_OFFERED,
    OWNED,
    PROFILE_LOCK,
    UNCONFIRMED,
    Tally,
    browsers_on,
    listing_ids,
    profile_in_use,
    remove_profile,
)

# region Fixtures / helpers

FIRST: Final = "6423b41f-d6e3-47e7-a10c-5117f7224af2"
SECOND: Final = "1aef5d5b-8e99-4ad3-bf44-7dc0eb5ce9fc"

GENERIC_READ: Final = 0x80000000
NO_SHARING: Final = 0
OPEN_ALWAYS: Final = 4
FILE_FLAG_DELETE_ON_CLOSE: Final = 0x04000000
INVALID_HANDLE: Final = ctypes.c_void_p(-1).value


def hold_unshared(path: Path) -> int:
    """Open a file as Firefox opens its profile lock on Windows: no sharing, deleted when closed.

    :param path: the file.
    :returns: its handle, to close with ``CloseHandle``.
    """
    create_file = ctypes.windll.kernel32.CreateFileW
    create_file.restype = ctypes.c_void_p
    handle = create_file(str(path), GENERIC_READ, NO_SHARING, None, OPEN_ALWAYS, FILE_FLAG_DELETE_ON_CLOSE, None)
    assert handle not in (None, INVALID_HANDLE)
    return handle


# endregion


# region listing_ids


def test_listing_ids_keeps_each_listing_once_in_page_order() -> None:
    """
    Test steps:
    1. Give a page's links: a listing twice (once with a query), another listing, and two links that name none
    2. Assert each listing's id comes back once, in the order first met
    """
    links = [
        f"https://www.fab.com/listings/{SECOND}",
        "https://www.fab.com/sellers/Somebody",
        f"https://www.fab.com/listings/{FIRST}?tab=reviews",
        f"https://www.fab.com/listings/{SECOND}",
        "https://www.fab.com/listings/not-an-id",
    ]

    assert listing_ids(links) == [SECOND, FIRST]


# endregion


# region Tally


def test_tally_counts_added_and_owned_and_lists_each_failure_by_its_address() -> None:
    """
    Test steps:
    1. Record an added listing, an owned one, and two that failed in different ways
    2. Assert the summary gives the three counts, then each failed listing's address on its own line with its reason
    """
    tally = Tally()

    tally.record(FIRST, ADDED)
    tally.record(FIRST, OWNED)
    tally.record(FIRST, NOT_OFFERED)
    tally.record(SECOND, UNCONFIRMED)

    assert tally.summary().splitlines() == [
        "Added: 1",
        "Already owned: 1",
        "Failed: 2",
        f"{LISTING_URL.format(FIRST)}  ({NOT_OFFERED})",
        f"{LISTING_URL.format(SECOND)}  ({UNCONFIRMED})",
    ]


def test_tally_of_a_run_that_did_nothing_lists_no_address() -> None:
    """
    Test steps:
    1. Summarize a run that recorded nothing
    2. Assert the three counts are zero and no address follows
    """
    assert Tally().summary().splitlines() == ["Added: 0", "Already owned: 0", "Failed: 0"]


# endregion


# region profile_in_use


def test_a_profile_without_a_lock_file_is_free(tmp_path: Path) -> None:
    """
    Test steps:
    1. Ask about a profile folder holding no lock file
    2. Assert it is free
    """
    assert not profile_in_use(tmp_path)


def test_a_lock_file_nobody_holds_leaves_the_profile_free(tmp_path: Path) -> None:
    """
    Test steps:
    1. Leave the lock file a closed Firefox leaves behind
    2. Assert the profile is free
    """
    (tmp_path / PROFILE_LOCK).touch()

    assert not profile_in_use(tmp_path)


@mark.skipif(sys.platform != "win32", reason="the Windows lock is the one this reads")
def test_a_lock_file_held_unshared_marks_the_profile_in_use(tmp_path: Path) -> None:
    """
    Test steps:
    1. Hold the profile's lock file open with no sharing, as a running Firefox holds it on Windows
    2. Assert the profile is in use
    3. Let it go, and assert the profile is free again
    """
    handle = hold_unshared(tmp_path / PROFILE_LOCK)
    try:
        assert profile_in_use(tmp_path)
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)

    assert not profile_in_use(tmp_path)


# endregion


# region remove_profile


def test_remove_profile_deletes_the_folder_and_says_so(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    """
    Test steps:
    1. Make a persona folder holding a file and a subfolder, and a lock file nobody holds
    2. Remove it
    3. Assert the folder is gone, the status is 0, and the message names the folder
    """
    persona = tmp_path / "persona"
    (persona / "storage").mkdir(parents=True)
    (persona / "cookies.sqlite").touch()
    (persona / PROFILE_LOCK).touch()

    assert remove_profile(persona) == 0

    assert not persona.exists()
    assert capsys.readouterr().out == f"Deleted the profile at {persona}.\n"


def test_remove_profile_with_no_folder_deletes_nothing(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    """
    Test steps:
    1. Remove a persona whose folder does not exist
    2. Assert the status is 0 and the message says nothing was deleted
    """
    persona = tmp_path / "persona"

    assert remove_profile(persona) == 0

    assert capsys.readouterr().out == f"There is no profile at {persona}; nothing was deleted.\n"


@mark.skipif(sys.platform != "win32", reason="the Windows lock is the one this reads")
def test_remove_profile_leaves_a_persona_open_in_firefox(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    """
    Test steps:
    1. Make a persona folder and hold its lock file as a running Firefox does
    2. Remove it
    3. Assert the status is 1, the folder and its files are still there, and the message says to close it first
    """
    persona = tmp_path / "persona"
    persona.mkdir()
    (persona / "cookies.sqlite").touch()
    handle = hold_unshared(persona / PROFILE_LOCK)
    try:
        assert remove_profile(persona) == 1
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)

    assert (persona / "cookies.sqlite").exists()
    out = capsys.readouterr().out
    assert out == f"The profile at {persona} is open in a Firefox; close it first. Nothing was deleted.\n"


# endregion


# region browsers_on

PROFILE: Final = Path("C:/Users/someone/persona")


def test_browsers_on_finds_the_process_whose_command_line_names_the_profile() -> None:
    """
    Test steps:
    1. List three Firefox processes: one on the profile (spelled with other slashes and case), one on another
       profile, and a content process with no command line
    2. Assert only the first one's id comes back
    """
    processes = [
        {"ProcessId": 1, "CommandLine": '"firefox.exe" -no-remote -profile c:/users/SOMEONE/persona https://fab.com/'},
        {"ProcessId": 2, "CommandLine": r'"firefox.exe" -profile C:\Users\someone\other'},
        {"ProcessId": 3, "CommandLine": None},
    ]

    assert browsers_on(PROFILE, processes) == [1]


def test_browsers_on_reads_a_single_process_and_none() -> None:
    """
    Test steps:
    1. Give one process as an object, as PowerShell prints a list of one, and then nothing, as when no Firefox runs
    2. Assert the first finds it and the second finds none
    """
    single = {"ProcessId": 7, "CommandLine": f"firefox.exe -profile {PROFILE}"}

    assert browsers_on(PROFILE, single) == [7]
    assert not browsers_on(PROFILE, None)


# endregion
