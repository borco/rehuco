"""Tests for RecycleBinDeleter: the agent's own `~rehuco_core.Deleter`, and its refusal (#291, #300).

`configured_deleter` -- the shared accessor every in-window delete/discard resolves through absent an
explicit override (#298) -- is tested alongside it: same module, same setting.

`RecycleBinDeleter` itself is now a thin adapter over `~borco_pyside.recycle_bin.recycle_bin`, which
carries the actual `send2trash` mechanics (#300); these tests mock that seam rather than `send2trash`
directly.
"""

import re
from pathlib import Path
from typing import Final

import pytest
from borco_pyside.recycle_bin import NoRecycleBinError
from pytest_mock import MockerFixture
from rehuco_agent.recycle_bin_deleter import RecycleBinDeleter, configured_deleter
from rehuco_agent.settings.screenshot_deletion_settings import shared_screenshot_deletion_settings
from rehuco_core import DEFAULT_DELETER, NoTrashBinError

PATH: Final = Path("/fake/tutorial/info00.jpg")

RECYCLE_BIN: Final = "rehuco_agent.recycle_bin_deleter.recycle_bin"
"""Where the shared `~borco_pyside.recycle_bin.RecycleBin` accessor is patched -- imported by name into
this module, the same seam every other caller of it would mock."""


def test_delete_moves_the_file_through_the_shared_recycle_bin(mocker: MockerFixture) -> None:
    """The whole point of this `Deleter`: the file goes through `~borco_pyside.recycle_bin.RecycleBin`,
    not straight gone.

    **Test steps:**

    * delete a path
    * verify the shared `RecycleBin` was asked to add exactly that path
    """
    bin_ = mocker.patch(RECYCLE_BIN).return_value

    RecycleBinDeleter().delete(PATH)

    bin_.add.assert_called_once_with(PATH)


def test_delete_refuses_with_the_location_when_no_bin_is_reachable(mocker: MockerFixture) -> None:
    """A network share with no Recycle Bin ([[mounts-and-storage#offline-mounts]]) is refused by name,
    never silently unlinked instead.

    **Test steps:**

    * make the shared `RecycleBin` refuse as it does for an unreachable bin
    * delete a path through the deleter
    * verify a `NoTrashBinError` naming the path's directory was raised
    """
    bin_ = mocker.patch(RECYCLE_BIN).return_value
    bin_.add.side_effect = NoRecycleBinError(f"No Recycle Bin is available for {PATH.parent}")

    with pytest.raises(NoTrashBinError, match=re.escape(str(PATH.parent))):
        RecycleBinDeleter().delete(PATH)


def test_a_file_already_gone_is_not_mistaken_for_a_missing_bin(mocker: MockerFixture) -> None:
    """`~borco_pyside.recycle_bin.RecycleBin.add` raising ``FileNotFoundError`` for a path that vanished
    is not a bin problem, so it passes through unwrapped -- the discard paths tolerate it the way they
    tolerate a plain unlink's (#298).

    **Test steps:**

    * make the shared `RecycleBin` raise ``FileNotFoundError``
    * delete a path through the deleter
    * verify ``FileNotFoundError`` itself was raised, not `NoTrashBinError`
    """
    bin_ = mocker.patch(RECYCLE_BIN).return_value
    bin_.add.side_effect = FileNotFoundError(PATH)

    with pytest.raises(FileNotFoundError):
        RecycleBinDeleter().delete(PATH)


def test_a_real_failure_is_not_mistaken_for_a_missing_bin(mocker: MockerFixture) -> None:
    """A locked file or an access-denied one is a real failure, not a bin problem (#300): it must reach
    the caller as itself, not be relabelled `NoTrashBinError`.

    **Test steps:**

    * make the shared `RecycleBin` raise a plain ``PermissionError``
    * delete a path through the deleter
    * verify the same ``PermissionError`` was raised, not `NoTrashBinError`
    """
    bin_ = mocker.patch(RECYCLE_BIN).return_value
    bin_.add.side_effect = PermissionError("locked")

    with pytest.raises(PermissionError):
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
