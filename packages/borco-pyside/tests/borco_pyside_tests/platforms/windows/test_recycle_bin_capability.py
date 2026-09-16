"""Tests for the ``SHQueryRecycleBinW`` capability check (#300).

Windows-only, like the module: ``ctypes.WinDLL("shell32", ...)`` fails to even import off Windows, so
the whole file skips off Windows the same way the registry tests beside it do. What the operating
system's answer actually looks like was measured manually (see the module's own docstring); this covers
the call itself and the per-drive cache.

Each test builds its own `RecycleBinCapability` rather than going through the shared
`~borco_pyside.platforms.windows.recycle_bin_capability.recycle_bin_capability` singleton, so no test
needs to reset any shared cache between runs.
"""

from pathlib import Path
from typing import Final

import pytest
from pytest import mark

pytest.importorskip("msvcrt")  # module doesn't exist off Windows -- skip the whole file there,
# same sentinel `test_shared_read.py` uses (the module under test would otherwise fail to import off
# Windows anyway, via `ctypes.WinDLL`, but that raises `AttributeError`, not the `ImportError` this needs)

# these must follow the guard above, or collection fails off Windows -- hence the suppressions
from borco_pyside.platforms.windows import recycle_bin_capability  # noqa: E402  # pylint: disable=wrong-import-position
from pytest_mock import MockerFixture  # noqa: E402  # pylint: disable=wrong-import-position

MODULE: Final = "borco_pyside.platforms.windows.recycle_bin_capability"

LOCAL_DRIVE: Final = Path("C:/fake/content.zip")
NETWORK_PATH: Final = Path("//fake-nas/share/content.zip")


@mark.windows
def test_a_successful_query_means_the_drive_has_a_bin(mocker: MockerFixture) -> None:
    """``SHQueryRecycleBinW`` returning ``S_OK`` (0) means the drive has a queryable Recycle Bin.

    **Test steps:**

    * patch the Win32 call to succeed
    * check a local path's drive
    * verify the call was asked about ``C:\\`` and the answer was ``True``
    """
    query = mocker.patch(f"{MODULE}.SH_QUERY_RECYCLE_BIN", return_value=0)
    assert recycle_bin_capability.RecycleBinCapability().has_recycle_bin(LOCAL_DRIVE) is True
    assert query.call_args.args[0] == "C:\\"


@mark.windows
def test_a_failed_query_means_the_drive_has_no_bin(mocker: MockerFixture) -> None:
    """A non-zero ``HRESULT`` -- measured as ``0x80070003`` for a UNC/network root -- means no bin.

    **Test steps:**

    * patch the Win32 call to fail
    * check a UNC path's drive
    * verify the call was asked about the UNC share root and the answer was ``False``
    """
    query = mocker.patch(f"{MODULE}.SH_QUERY_RECYCLE_BIN", return_value=0x80070003)
    assert recycle_bin_capability.RecycleBinCapability().has_recycle_bin(NETWORK_PATH) is False
    assert query.call_args.args[0] == "\\\\fake-nas\\share\\"


@mark.windows
def test_a_second_check_within_the_ttl_reuses_the_cached_answer(mocker: MockerFixture) -> None:
    """A drive already checked recently is not asked again -- the whole point of the cache (#300):
    a bulk delete over hundreds of files on one drive must not pay the Win32 round trip per file.

    **Test steps:**

    * patch the Win32 call to succeed
    * check the same path's drive twice, through the same `RecycleBinCapability`
    * verify the real call only happened once
    """
    query = mocker.patch(f"{MODULE}.SH_QUERY_RECYCLE_BIN", return_value=0)
    capability = recycle_bin_capability.RecycleBinCapability()
    capability.has_recycle_bin(LOCAL_DRIVE)
    capability.has_recycle_bin(LOCAL_DRIVE)
    query.assert_called_once()


@mark.windows
def test_a_stale_answer_is_checked_again(mocker: MockerFixture) -> None:
    """Past the TTL, the drive is asked again -- so an unmounted/remounted share or a changed policy
    is eventually noticed rather than trusted forever.

    **Test steps:**

    * patch the Win32 call to succeed and the clock to advance past the TTL between two checks
    * check the same path's drive twice, through the same `RecycleBinCapability`
    * verify the real call happened both times
    """
    query = mocker.patch(f"{MODULE}.SH_QUERY_RECYCLE_BIN", return_value=0)
    clock = mocker.patch(f"{MODULE}.time.monotonic")
    clock.side_effect = [0.0, recycle_bin_capability.CACHE_TTL_SECONDS + 1.0]
    capability = recycle_bin_capability.RecycleBinCapability()
    capability.has_recycle_bin(LOCAL_DRIVE)
    capability.has_recycle_bin(LOCAL_DRIVE)
    assert query.call_count == 2


@mark.windows
def test_the_module_function_asks_the_shared_capability(mocker: MockerFixture) -> None:
    """`has_recycle_bin` -- what `~borco_pyside.recycle_bin.RecycleBin` imports -- goes through the
    process-wide instance, so its cache is the one that accumulates across deletes.

    **Test steps:**

    * patch the Win32 call to succeed and the shared accessor to hand out a fresh instance
    * ask through the module function
    * verify the answer came from the shared instance's own check
    """
    mocker.patch(f"{MODULE}.SH_QUERY_RECYCLE_BIN", return_value=0)
    shared = recycle_bin_capability.RecycleBinCapability()
    mocker.patch(f"{MODULE}.recycle_bin_capability", return_value=shared)
    check = mocker.spy(shared, "has_recycle_bin")
    assert recycle_bin_capability.has_recycle_bin(LOCAL_DRIVE) is True
    check.assert_called_once_with(LOCAL_DRIVE)


@mark.windows
def test_recycle_bin_capability_is_a_process_wide_singleton() -> None:
    """`~borco_pyside.platforms.windows.recycle_bin_capability.recycle_bin_capability` hands back the
    same instance every time, so its cache actually accumulates across calls.

    **Test steps:**

    * call the accessor twice
    * verify both calls returned the same object
    """
    assert recycle_bin_capability.recycle_bin_capability() is recycle_bin_capability.recycle_bin_capability()
