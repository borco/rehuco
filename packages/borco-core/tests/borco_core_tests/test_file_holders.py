"""Tests for asking which processes have files open (#355).

Two kinds, as with the non-locking reader: the **dispatch** is mocked, and the **answer** is not -- who
holds a file is a fact about the running operating system, so that test carries ``disk`` and
``windows``.
"""

import os
from pathlib import Path
from typing import Final

from borco_core import FileHolder, file_holders
from pytest import mark
from pytest_mock import MockerFixture

WINDOWS_QUERY: Final = "borco_core.platforms.windows.file_holders.file_holders"
"""Where the Windows branch lands, patched at its source module -- the import happens inside the call."""

PATHS: Final = (Path("/fake/pack/pack.zip"),)


def test_off_windows_there_is_nobody_to_ask(mocker: MockerFixture) -> None:
    """POSIX renames under open handles anyway, and has no Restart Manager to ask.

    **Test steps:**

    * force ``sys.platform`` to Linux
    * ask about a file, and verify the answer is empty
    """
    mocker.patch("borco_core.file_holders.sys.platform", "linux")

    assert not file_holders(PATHS)


@mark.windows
def test_windows_asks_the_restart_manager(mocker: MockerFixture) -> None:
    """On Windows the question goes to the Restart Manager binding.

    **Test steps:**

    * patch the Windows query
    * ask about a file, and verify it was handed the paths and its answer returned
    """
    query = mocker.patch(WINDOWS_QUERY, return_value=(FileHolder(7, "Windows Explorer"),))

    assert file_holders(PATHS) == (FileHolder(7, "Windows Explorer"),)
    query.assert_called_once_with(PATHS)


@mark.disk
@mark.windows
def test_a_file_this_process_holds_names_this_process(tmp_path: Path) -> None:
    """The Restart Manager names whoever has the file open -- here, this process -- and nobody once it
    is closed.

    **Test steps:**

    * write a file, and ask about it while it is open and again once it is closed
    * verify the first answer names this process and the second is empty
    """
    path = tmp_path / "content.zip"
    path.write_bytes(b"held")

    with path.open("rb"):
        holders = file_holders((path,))

    assert [holder.pid for holder in holders] == [os.getpid()]
    assert not file_holders((path,))
