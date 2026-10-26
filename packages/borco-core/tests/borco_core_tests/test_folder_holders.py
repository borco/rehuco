"""Tests for asking which processes hold a folder or anything under it (#505).

Two kinds, as with naming a file's holders: the **dispatch** is mocked, and the **answer** is not -- who stands in a
folder is a fact about the running operating system, so those tests start a child of their own and carry ``disk``
and ``windows``.
"""

import subprocess  # nosec B404 -- the tests start their own interpreter, with fixed arguments
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Final

from borco_core import FileHolder, folder_holders
from pytest import mark
from pytest_mock import MockerFixture

WINDOWS_QUERY: Final = "borco_core.platforms.windows.folder_holders.folder_holders"
"""Where the Windows branch lands, patched at its source module -- the import happens inside the call."""

FOLDER: Final = Path("/fake/pack")


@contextmanager
def standing_in(folder: Path) -> Iterator[int]:
    """A child interpreter whose working directory is ``folder``, alive for the block.

    :param folder: where it stands.
    :yields: the interpreter's own pid, once it is running -- not the child's: a virtual environment's ``python.exe``
        is a launcher that starts the real interpreter, and only that one stands in the folder.
    """
    with subprocess.Popen(  # nosec B603 -- our own interpreter, fixed arguments
        (sys.executable, "-c", "import os, sys; print(os.getpid(), flush=True); sys.stdin.read()"),
        cwd=folder,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    ) as child:
        try:
            assert child.stdout is not None
            yield int(child.stdout.readline())
        finally:
            child.kill()


def test_off_windows_there_is_nobody_to_ask(mocker: MockerFixture) -> None:
    """POSIX renames under open handles anyway, and has no handle table to walk.

    **Test steps:**

    * force ``sys.platform`` to Linux
    * ask about a folder, and verify the answer is empty
    """
    mocker.patch("borco_core.folder_holders.sys.platform", "linux")

    assert not folder_holders(FOLDER)


@mark.windows
def test_windows_walks_the_handles(mocker: MockerFixture) -> None:
    """On Windows the question goes to the handle walk.

    **Test steps:**

    * patch the Windows walk
    * ask about a folder, and verify it was handed the folder and its answer returned
    """
    walk = mocker.patch(WINDOWS_QUERY, return_value=(FileHolder(7, "bash.exe"),))

    assert folder_holders(FOLDER) == (FileHolder(7, "bash.exe"),)
    walk.assert_called_once_with(FOLDER)


@mark.disk
@mark.windows
def test_a_process_standing_in_the_folder_is_found(tmp_path: Path) -> None:
    """A process whose working directory is the folder holds it -- the case the Restart Manager cannot see -- and is
    named by its executable; one standing in a sibling whose name only starts the same is not.

    **Test steps:**

    * start one child standing in ``pack`` and one standing in ``pack-old``
    * ask who holds ``pack``
    * verify the first child is named by its executable, and the second is not listed
    """
    pack = tmp_path / "pack"
    sibling = tmp_path / "pack-old"
    pack.mkdir()
    sibling.mkdir()

    with standing_in(pack) as inside, standing_in(sibling) as beside:
        holders = {holder.pid: holder.name for holder in folder_holders(pack)}

    assert holders[inside].lower().endswith(".exe")
    assert beside not in holders


@mark.disk
@mark.windows
def test_a_process_standing_beneath_the_folder_is_found(tmp_path: Path) -> None:
    """A handle anywhere under the folder blocks renaming it, so a process standing in a subfolder is found too.

    **Test steps:**

    * start a child standing in ``pack/images``
    * ask who holds ``pack``, and verify the child is listed
    """
    images = tmp_path / "pack" / "images"
    images.mkdir(parents=True)

    with standing_in(images) as child:
        pids = {holder.pid for holder in folder_holders(tmp_path / "pack")}

    assert child in pids
