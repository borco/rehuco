"""Tests for the crash-safe atomic-write helpers."""

from pathlib import Path
from typing import Final

import pytest
from borco_core import atomic_write_bytes, atomic_write_text
from pytest_mock import MockerFixture

TARGET: Final = Path("/fake/out.bin")
TEMP: Final = "/fake/.out.bin.XXXXXX.tmp"
FD: Final = 7


def patch_fs(
    mocker: MockerFixture,
    *,
    replace_error: Exception | None = None,
    dest_exists: bool = False,
) -> tuple:
    """Patch all filesystem calls inside ``atomic_write`` and return the three mocks tests assert on.

    :param mocker: pytest-mock fixture.
    :param replace_error: if given, ``os.replace`` raises this instead of succeeding.
    :param dest_exists: if ``True``, ``Path.stat`` succeeds (existing destination);
        otherwise it raises ``FileNotFoundError`` (new destination).
    :returns: a 3-tuple of
        ``(write_handle, replace, unlink)`` where ``write_handle`` is the mock object
        bound to ``handle`` inside the ``with os.fdopen(...) as handle:`` block,
        ``replace`` is the mock for ``os.replace``, and ``unlink`` is the mock for
        ``Path.unlink``.
    """
    mocker.patch("borco_core.atomic_write.tempfile.mkstemp", return_value=(FD, TEMP))
    handle = mocker.MagicMock()
    mocker.patch("borco_core.atomic_write.os.fdopen", return_value=handle)
    mocker.patch("borco_core.atomic_write.os.fsync")
    mocker.patch("borco_core.atomic_write.os.chmod")
    mocker.patch("borco_core.atomic_write.os.open", return_value=FD)
    mocker.patch("borco_core.atomic_write.os.close")
    if dest_exists:
        mocker.patch.object(Path, "stat", return_value=mocker.MagicMock(st_mode=0o100644))
    else:
        mocker.patch.object(Path, "stat", side_effect=FileNotFoundError)
    replace = mocker.patch("borco_core.atomic_write.os.replace", side_effect=replace_error)
    unlink = mocker.patch.object(Path, "unlink")
    return handle.__enter__.return_value, replace, unlink


def test_atomic_write_bytes_writes_data(mocker: MockerFixture) -> None:
    """The payload bytes are written to the temp handle, then the atomic swap runs.

    **Test steps:**

    * patch filesystem calls
    * call ``atomic_write_bytes`` with known bytes
    * verify ``write`` received exactly those bytes
    * verify ``os.replace`` was called with the temp and destination paths
    """
    handle, replace, _ = patch_fs(mocker)
    atomic_write_bytes(TARGET, b"hello")
    handle.write.assert_called_once_with(b"hello")
    replace.assert_called_once_with(Path(TEMP), TARGET)


def test_atomic_write_text_encodes_to_utf8(mocker: MockerFixture) -> None:
    """``atomic_write_text`` encodes text to UTF-8 before handing off to the byte writer.

    **Test steps:**

    * patch filesystem calls
    * call ``atomic_write_text`` with a unicode string
    * verify the handle received the UTF-8-encoded bytes
    """
    handle, _, _ = patch_fs(mocker)
    atomic_write_text(TARGET, "café ☕")
    handle.write.assert_called_once_with("café ☕".encode())


def test_atomic_write_fsync_precedes_replace(mocker: MockerFixture) -> None:
    """``os.fsync`` is called before ``os.replace`` so data hits storage before the swap.

    **Test steps:**

    * patch filesystem calls, tracking call order via ``side_effect``
    * call ``atomic_write_bytes``
    * verify fsync precedes replace in the recorded sequence
    """
    mocker.patch("borco_core.atomic_write.tempfile.mkstemp", return_value=(FD, TEMP))
    mocker.patch("borco_core.atomic_write.os.fdopen", return_value=mocker.MagicMock())
    mocker.patch.object(Path, "unlink")
    mocker.patch.object(Path, "stat", side_effect=FileNotFoundError)
    mocker.patch("borco_core.atomic_write.os.chmod")
    mocker.patch("borco_core.atomic_write.os.open", return_value=FD)
    mocker.patch("borco_core.atomic_write.os.close")

    order: list[str] = []
    mocker.patch("borco_core.atomic_write.os.fsync", side_effect=lambda _: order.append("fsync"))
    mocker.patch("borco_core.atomic_write.os.replace", side_effect=lambda *_: order.append("replace"))

    atomic_write_bytes(TARGET, b"data")
    assert order == ["fsync", "replace"]


def test_atomic_write_success_does_not_unlink_temp(mocker: MockerFixture) -> None:
    """A successful write never manually removes the temp -- ``os.replace`` already moved it.

    **Test steps:**

    * patch filesystem calls including ``Path.unlink``
    * call ``atomic_write_bytes`` without triggering an error
    * verify ``unlink`` was never called
    """
    _, _, unlink = patch_fs(mocker)
    atomic_write_bytes(TARGET, b"data")
    unlink.assert_not_called()


def test_atomic_write_failure_unlinks_temp_and_propagates(mocker: MockerFixture) -> None:
    """A failed replace removes the temp file and propagates the error.

    **Test steps:**

    * patch ``os.replace`` to raise ``OSError``
    * call ``atomic_write_bytes``
    * verify the error propagates to the caller
    * verify ``unlink`` was called on the temp path with ``missing_ok=True``
    """
    _, _, unlink = patch_fs(mocker, replace_error=OSError("replace failed"))
    with pytest.raises(OSError, match="replace failed"):
        atomic_write_bytes(TARGET, b"replacement")
    unlink.assert_called_once_with(missing_ok=True)


def test_atomic_write_preserves_existing_destination_mode(mocker: MockerFixture) -> None:
    """The temp file's mode is set to the existing destination's mode before the replace.

    **Test steps:**

    * patch filesystem calls with an existing destination mode of 0o644
    * call ``atomic_write_bytes``
    * verify ``os.chmod`` was called with the temp path and 0o644 before ``os.replace``
    """
    mocker.patch("borco_core.atomic_write.tempfile.mkstemp", return_value=(FD, TEMP))
    mocker.patch("borco_core.atomic_write.os.fdopen", return_value=mocker.MagicMock())
    mocker.patch("borco_core.atomic_write.os.fsync")
    mocker.patch("borco_core.atomic_write.os.open", return_value=FD)
    mocker.patch("borco_core.atomic_write.os.close")
    mocker.patch.object(Path, "unlink")
    mocker.patch.object(Path, "stat", return_value=mocker.MagicMock(st_mode=0o100644))
    chmod = mocker.patch("borco_core.atomic_write.os.chmod")

    order: list[str] = []
    chmod.side_effect = lambda *_: order.append("chmod")
    replace = mocker.patch("borco_core.atomic_write.os.replace", side_effect=lambda *_: order.append("replace"))

    atomic_write_bytes(TARGET, b"data")
    chmod.assert_called_once_with(Path(TEMP), 0o644)
    replace.assert_called_once_with(Path(TEMP), TARGET)
    assert order == ["chmod", "replace"]


def test_atomic_write_applies_umask_mode_for_new_destination(mocker: MockerFixture) -> None:
    """A new destination (no existing file) gets umask-respecting default permissions.

    **Test steps:**

    * patch filesystem calls with a missing destination and a known umask
    * call ``atomic_write_bytes``
    * verify ``os.chmod`` was called with ``0o666`` minus the umask
    """
    _, _, _ = patch_fs(mocker, dest_exists=False)
    chmod = mocker.patch("borco_core.atomic_write.os.chmod")
    mocker.patch("borco_core.atomic_write.os.umask", side_effect=[0o022, 0o022])

    atomic_write_bytes(TARGET, b"data")
    chmod.assert_called_once_with(Path(TEMP), 0o644)
