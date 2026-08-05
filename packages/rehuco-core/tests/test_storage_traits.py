"""Tests for the storage trait a reader consults before it decides whether to let go (#241).

Both answers are exercised on every platform by forcing ``sys.platform``, because the trait is what
every job's behaviour hangs off: a wrong answer on the platform the suite does not happen to be
running on would be invisible until someone ran the app there.
"""

from pathlib import Path
from typing import Final

from pytest import mark, param
from pytest_mock import MockerFixture
from rehuco_core import readers_must_yield_for_directory_rename

PATH: Final = Path("/fake/resource/content.zip")


@mark.parametrize(
    ("platform", "expected"),
    [
        param("win32", True, id="windows-locks"),
        param("linux", False, id="linux-does-not"),
        param("darwin", False, id="macos-does-not"),
    ],
)
def test_only_windows_makes_a_reader_let_go(mocker: MockerFixture, platform: str, expected: bool) -> None:
    """Windows readers must yield before a directory above them is renamed; nobody else's must.

    NTFS refuses to rename a directory while any handle is open beneath it, whatever share mode that
    handle asked for -- so :func:`~borco_core.shared_read_open`'s ``FILE_SHARE_DELETE``, which does
    settle the file-scoped case, cannot settle this one. POSIX renames a directory entry and an open
    descriptor never notices.

    **Test steps:**

    * force ``sys.platform``;
    * ask the trait about a path;
    * check the answer.
    """
    mocker.patch("rehuco_core.storage_traits.sys.platform", platform)
    assert readers_must_yield_for_directory_rename(PATH) is expected
