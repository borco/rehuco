"""Tests for `~borco_pyside.recycle_bin.RecycleBin` (#300).

Both platform branches are exercised by forcing ``sys.platform`` rather than relying on the runner's
real OS, the same dispatch-testing shape as ``borco_core``'s own ``test_shared_read.py``: which branch
runs is this module's own logic, and a forced value proves it without needing two runners.
"""

import re
from pathlib import Path
from typing import Final

from borco_pyside import recycle_bin
from borco_pyside.recycle_bin import NoRecycleBinError, RecycleBin
from pytest import mark, raises
from pytest_mock import MockerFixture
from send2trash.exceptions import TrashPermissionError

PATH: Final = Path("/fake/tutorial/backup.orig")

CAPABILITY: Final = "borco_pyside.platforms.windows.recycle_bin_capability.has_recycle_bin"
"""Where the Windows drive-capability check lands -- imported lazily inside
:meth:`~borco_pyside.recycle_bin.RecycleBin.add`, so it is patched at its source module."""


# region off Windows


def test_add_moves_the_file_through_send2trash(mocker: MockerFixture) -> None:
    """The whole point of this class: the file goes to the Recycle Bin / Trash, not straight gone.

    **Test steps:**

    * force a non-Windows platform, so the drive-capability check never runs
    * add a path
    * verify ``send2trash`` was asked to move exactly that path
    """
    mocker.patch("borco_pyside.recycle_bin.sys.platform", "linux")
    send2trash = mocker.patch("borco_pyside.recycle_bin.send2trash")

    RecycleBin().add(PATH)

    send2trash.assert_called_once_with(str(PATH))


def test_trash_permission_error_becomes_no_recycle_bin_error(mocker: MockerFixture) -> None:
    """``send2trash``'s own documented no-bin signal (mac/gio/other backends) is translated, not
    swallowed.

    **Test steps:**

    * force a non-Windows platform
    * make ``send2trash`` raise ``TrashPermissionError``
    * add a path
    * verify `NoRecycleBinError` naming the path's directory was raised
    """
    mocker.patch("borco_pyside.recycle_bin.sys.platform", "linux")
    mocker.patch("borco_pyside.recycle_bin.send2trash", side_effect=TrashPermissionError(str(PATH)))

    with raises(NoRecycleBinError, match=re.escape(str(PATH.parent))):
        RecycleBin().add(PATH)


def test_a_file_already_gone_is_not_mistaken_for_a_missing_bin(mocker: MockerFixture) -> None:
    """``send2trash`` raising ``FileNotFoundError`` for a vanished path is not a bin problem.

    **Test steps:**

    * force a non-Windows platform
    * make ``send2trash`` raise ``FileNotFoundError``
    * add a path
    * verify ``FileNotFoundError`` itself was raised, not `NoRecycleBinError`
    """
    mocker.patch("borco_pyside.recycle_bin.sys.platform", "linux")
    mocker.patch("borco_pyside.recycle_bin.send2trash", side_effect=FileNotFoundError(PATH))

    with raises(FileNotFoundError):
        RecycleBin().add(PATH)


def test_a_real_failure_is_not_mistaken_for_a_missing_bin(mocker: MockerFixture) -> None:
    """A locked file or an access-denied one is a real failure, not a bin problem (#300) -- the bug
    this class replaces the old ``RecycleBinDeleter`` to fix.

    **Test steps:**

    * force a non-Windows platform
    * make ``send2trash`` raise a plain ``PermissionError``
    * add a path
    * verify the same ``PermissionError`` was raised, not `NoRecycleBinError`
    """
    mocker.patch("borco_pyside.recycle_bin.sys.platform", "linux")
    mocker.patch("borco_pyside.recycle_bin.send2trash", side_effect=PermissionError("locked"))

    with raises(PermissionError):
        RecycleBin().add(PATH)


# endregion

# region on Windows


@mark.windows
def test_a_binless_drive_is_refused_without_calling_send2trash(mocker: MockerFixture) -> None:
    """On Windows, a drive known to have no Recycle Bin is refused up front (#300) -- ``send2trash``'s
    own error for that case is not reliably distinguishable from a locked file, so it is never reached.

    **Test steps:**

    * force the Windows platform and the capability check to say no, for a path that exists
    * add the path
    * verify `NoRecycleBinError` was raised and ``send2trash`` was never called
    """
    mocker.patch("borco_pyside.recycle_bin.sys.platform", "win32")
    mocker.patch(CAPABILITY, return_value=False)
    mocker.patch.object(Path, "exists", return_value=True)
    send2trash = mocker.patch("borco_pyside.recycle_bin.send2trash")

    with raises(NoRecycleBinError):
        RecycleBin().add(PATH)

    send2trash.assert_not_called()


@mark.windows
def test_a_file_already_gone_on_a_binless_drive_is_still_not_a_bin_problem(mocker: MockerFixture) -> None:
    """The drive check runs before ``send2trash`` and so before its own ``FileNotFoundError`` -- a
    vanished file must still come back as that, not as `NoRecycleBinError`, so the callers that tolerate
    a vanished file keep tolerating it whatever drive it was on.

    **Test steps:**

    * force the Windows platform and the capability check to say no, for a path that does not exist
    * add the path
    * verify ``FileNotFoundError`` was raised, not `NoRecycleBinError`
    """
    mocker.patch("borco_pyside.recycle_bin.sys.platform", "win32")
    mocker.patch(CAPABILITY, return_value=False)
    mocker.patch.object(Path, "exists", return_value=False)

    with raises(FileNotFoundError):
        RecycleBin().add(PATH)


@mark.windows
def test_a_bin_capable_drive_proceeds_to_send2trash(mocker: MockerFixture) -> None:
    """On Windows, a drive known to have a Recycle Bin goes straight to ``send2trash``.

    **Test steps:**

    * force the Windows platform and the capability check to say yes
    * add a path
    * verify ``send2trash`` was asked to move it
    """
    mocker.patch("borco_pyside.recycle_bin.sys.platform", "win32")
    mocker.patch(CAPABILITY, return_value=True)
    send2trash = mocker.patch("borco_pyside.recycle_bin.send2trash")

    RecycleBin().add(PATH)

    send2trash.assert_called_once_with(str(PATH))


# endregion


def test_recycle_bin_is_a_process_wide_singleton() -> None:
    """`~borco_pyside.recycle_bin.recycle_bin` hands back the same instance every time.

    **Test steps:**

    * call the accessor twice
    * verify both calls returned the same object
    """
    assert recycle_bin.recycle_bin() is recycle_bin.recycle_bin()
