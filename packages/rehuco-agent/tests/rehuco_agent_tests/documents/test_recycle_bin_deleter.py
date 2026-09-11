"""Tests for RecycleBinDeleter: the agent's own `~rehuco_core.Deleter`, and its refusal (#291).

`configured_deleter` -- the shared accessor every in-window delete/discard resolves through absent an
explicit override (#298) -- is tested alongside it: same module, same setting.
"""

import re
from pathlib import Path
from typing import Final

import pytest
from pytest_mock import MockerFixture
from rehuco_agent.documents.recycle_bin_deleter import RecycleBinDeleter, configured_deleter
from rehuco_agent.settings.screenshot_deletion_settings import shared_screenshot_deletion_settings
from rehuco_core import DEFAULT_DELETER, NoTrashBinError

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


def test_a_file_already_gone_is_not_mistaken_for_a_missing_bin(mocker: MockerFixture) -> None:
    """``send2trash`` raises ``FileNotFoundError`` for a path that vanished; that is not a bin problem,
    so it passes through unwrapped -- the discard paths tolerate it the way they tolerate a plain
    unlink's (#298).

    **Test steps:**

    * make ``send2trash`` raise ``FileNotFoundError``
    * delete a path through the deleter
    * verify ``FileNotFoundError`` itself was raised, not `NoTrashBinError`
    """
    mocker.patch("rehuco_agent.documents.recycle_bin_deleter.send2trash", side_effect=FileNotFoundError(PATH))

    with pytest.raises(FileNotFoundError):
        RecycleBinDeleter().delete(PATH)


def test_configured_deleter_is_the_recycle_bin_when_the_setting_is_on() -> None:
    """The setting is on by default (#291), so the shared accessor resolves to a `RecycleBinDeleter`.

    **Test steps:**

    * read the configured deleter with the setting at its default
    * verify it is a `RecycleBinDeleter`
    """
    assert isinstance(configured_deleter(), RecycleBinDeleter)


def test_configured_deleter_is_the_default_deleter_when_the_setting_is_off() -> None:
    """Turning the setting off makes the shared accessor resolve to a plain unlink (#298).

    **Test steps:**

    * turn **Move deleted images to the Recycle Bin** off
    * verify the configured deleter is `~rehuco_core.DEFAULT_DELETER`
    """
    shared_screenshot_deletion_settings().use_recycle_bin = False

    assert configured_deleter() is DEFAULT_DELETER
