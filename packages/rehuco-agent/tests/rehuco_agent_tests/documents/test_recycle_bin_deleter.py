"""Tests for RecycleBinDeleter: the agent's own `~rehuco_core.Deleter`, and its refusal (#291)."""

import re
from pathlib import Path
from typing import Final

import pytest
from pytest_mock import MockerFixture
from rehuco_agent.documents.recycle_bin_deleter import RecycleBinDeleter
from rehuco_core import NoTrashBinError

PATH: Final = Path("/fake/tutorial/info00.jpg")


def test_delete_moves_the_file_through_send2trash(mocker: MockerFixture) -> None:
    """The whole point of this `Deleter`: the file goes to the Recycle Bin / Trash, not straight gone.

    **Test steps:**

    * delete a path
    * verify ``send2trash`` was asked to move exactly that path
    """
    send2trash = mocker.patch("rehuco_agent.documents.recycle_bin_deleter.send2trash")

    RecycleBinDeleter().delete(PATH)

    send2trash.assert_called_once_with(str(PATH))


def test_delete_refuses_with_the_location_when_no_bin_is_reachable(mocker: MockerFixture) -> None:
    """A network share with no Recycle Bin ([[mounts-and-storage#offline-mounts]]) is refused by name,
    never silently unlinked instead.

    **Test steps:**

    * make ``send2trash`` raise as it does for an unreachable bin
    * delete a path through the deleter
    * verify a `NoTrashBinError` naming the path's directory was raised, and nothing else was tried
    """
    mocker.patch("rehuco_agent.documents.recycle_bin_deleter.send2trash", side_effect=OSError("no bin"))

    with pytest.raises(NoTrashBinError, match=re.escape(str(PATH.parent))):
        RecycleBinDeleter().delete(PATH)
