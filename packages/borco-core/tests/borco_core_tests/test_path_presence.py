"""Tests for asking whether a remembered path is still there (#464).

Two kinds here. The **classification** (:func:`device_of`) is fed a mount table or a patched drive classifier, so no
real table or drive is read -- except for the Windows facts that are about the running OS, which carry ``windows``.
The **verdicts** (:func:`presence_of`, ``_judge``) have the stat, the volume check and the server probe replaced.
``socket.create_connection`` is always replaced -- no test touches the network. The scan is in
``test_path_presence_scan.py``.
"""

from pathlib import Path
from typing import Final

import pytest
from borco_core import path_presence
from borco_core.path_presence import REACH_TIMEOUT, Device, Presence, StorageKind, device_of, presence_of
from borco_core.platforms.linux.mount_table import Mount
from pytest import mark
from pytest_mock import MockerFixture

from .path_presence_support import MODULE, Probe, local, network

FILE: Final = Path("/fake/pack/file.rehu")
"""A stand-in for a remembered path; nothing here is ever really read."""

NAS_MOUNT: Final = Mount("//nas/share", Path("/mnt/nas"), "cifs")


# --- device_of: POSIX -------------------------------------------------------------------------------------------


def test_posix_reads_the_mount_table_when_given_none(mocker: MockerFixture) -> None:
    """A caller classifying one path lets :func:`device_of` read the table.

    **Test steps:**

    * force Linux and replace the table reader with one returning a CIFS mount
    * classify a path under that mount without passing a table
    * verify the reader was used and the path is on the network
    """
    mocker.patch(f"{MODULE}.sys.platform", "linux")
    read = mocker.patch(f"{MODULE}.read_mounts", return_value=[NAS_MOUNT])

    assert device_of(Path("/mnt/nas/a.rehu")).kind is StorageKind.NETWORK
    read.assert_called_once_with()


def test_posix_a_network_mount_names_its_server(mocker: MockerFixture) -> None:
    """A path under a CIFS mount is on the network, grouped by the mount point and probed on the share's port.

    **Test steps:**

    * force Linux and classify a path under a CIFS mount
    * verify a network device rooted at the mount with its host and port
    """
    mocker.patch(f"{MODULE}.sys.platform", "linux")

    device = device_of(Path("/mnt/nas/a.rehu"), [NAS_MOUNT])

    assert device == Device(StorageKind.NETWORK, Path("/mnt/nas"), "nas", 445)


def test_posix_a_disc_is_optical(mocker: MockerFixture) -> None:
    """A path under an iso9660 mount is on a disc, even inside a removable container.

    **Test steps:**

    * force Linux and classify a path under an iso9660 mount in ``/media``
    * verify an optical device rooted at the mount
    """
    mocker.patch(f"{MODULE}.sys.platform", "linux")
    disc = Mount("/dev/sr0", Path("/media/cd"), "iso9660")

    assert device_of(Path("/media/cd/a.rehu"), [disc]) == Device(StorageKind.OPTICAL, Path("/media/cd"))


def test_posix_the_deepest_mount_decides(mocker: MockerFixture) -> None:
    """A share mounted below ``/`` wins over the root filesystem that also holds the path.

    **Test steps:**

    * force Linux and classify a path with both ``/`` and a CIFS mount holding it
    * verify the CIFS mount decided
    """
    mocker.patch(f"{MODULE}.sys.platform", "linux")
    root = Mount("/dev/sda1", Path("/"), "ext4")

    assert device_of(Path("/mnt/nas/a.rehu"), [root, NAS_MOUNT]).kind is StorageKind.NETWORK


def test_posix_a_local_mount_in_a_container_is_removable(mocker: MockerFixture) -> None:
    """A mount that is neither network nor a disc does not decide: the container the path sits in does.

    **Test steps:**

    * force Linux and classify a path under an ext4 mount in ``/mnt``
    * verify a removable device rooted at the volume folder
    """
    mocker.patch(f"{MODULE}.sys.platform", "linux")
    disk = Mount("/dev/sdb1", Path("/mnt/disk"), "ext4")

    assert device_of(Path("/mnt/disk/a.rehu"), [disk]) == Device(StorageKind.REMOVABLE, Path("/mnt/disk"))


@pytest.mark.parametrize(
    ("path", "volume"),
    [
        ("/Volumes/USB/a/b.rehu", "/Volumes/USB"),
        ("/mnt/nas/a.rehu", "/mnt/nas"),
        ("/run/media/me/DISK/a.rehu", "/run/media/me/DISK"),
    ],
)
def test_posix_removable_containers_name_their_volume(mocker: MockerFixture, path: str, volume: str) -> None:
    """A path under ``/Volumes``, ``/mnt`` or ``/run/media`` is removable whether or not anything is mounted.

    **Test steps:**

    * force Linux and classify paths under each container with an empty mount table
    * verify a removable device rooted at the volume folder -- one level down, two under ``/run/media``
    """
    mocker.patch(f"{MODULE}.sys.platform", "linux")

    assert device_of(Path(path), []) == Device(StorageKind.REMOVABLE, Path(volume))


def test_posix_media_with_the_users_name_has_a_user_level(
    mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Under ``/media`` the first level is the user's folder only when it is the current user's name.

    **Test steps:**

    * force Linux, set ``USER`` and classify a path under ``/media/<user>/<label>``
    * verify the volume is the label folder
    """
    mocker.patch(f"{MODULE}.sys.platform", "linux")
    monkeypatch.setenv("USER", "me")

    assert device_of(Path("/media/me/DISK/a.rehu"), []).root == Path("/media/me/DISK")


def test_posix_media_without_the_users_name_has_no_user_level(
    mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Older systems mount straight into ``/media/<label>``.

    **Test steps:**

    * force Linux, set ``USER`` and classify a path under ``/media/<label>``
    * verify the volume is the label folder
    """
    mocker.patch(f"{MODULE}.sys.platform", "linux")
    monkeypatch.setenv("USER", "me")

    assert device_of(Path("/media/DISK/a.rehu"), []) == Device(StorageKind.REMOVABLE, Path("/media/DISK"))


def test_posix_media_with_no_user_set_has_no_user_level(mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    """With no ``USER`` in the environment nothing can be the user's folder.

    **Test steps:**

    * force Linux, remove ``USER`` and classify a path under ``/media/<label>``
    * verify the volume is the label folder
    """
    mocker.patch(f"{MODULE}.sys.platform", "linux")
    monkeypatch.delenv("USER", raising=False)

    assert device_of(Path("/media/DISK/a.rehu"), []).root == Path("/media/DISK")


@pytest.mark.parametrize("path", ["/Volumes", "/mnt", "/run/media/me"])
def test_posix_a_path_directly_in_a_container_names_no_volume(mocker: MockerFixture, path: str) -> None:
    """The container folder itself, or a user folder with no volume under it, is an ordinary local folder.

    **Test steps:**

    * force Linux and classify the container folders themselves
    * verify each is local
    """
    mocker.patch(f"{MODULE}.sys.platform", "linux")

    assert device_of(Path(path), []).kind is StorageKind.LOCAL


def test_posix_a_plain_path_is_local(mocker: MockerFixture) -> None:
    """Outside every mount and container, a path is on this machine's own disk.

    **Test steps:**

    * force Linux and classify a path under ``/home`` with only the root filesystem mounted
    * verify a local device rooted at ``/``
    """
    mocker.patch(f"{MODULE}.sys.platform", "linux")
    root = Mount("/dev/sda1", Path("/"), "ext4")

    device = device_of(Path("/home/me/a.rehu"), [root])

    assert device == Device(StorageKind.LOCAL, Path("/"))
    assert device.is_local


# --- device_of: Windows -----------------------------------------------------------------------------------------


@mark.windows
def test_windows_a_path_with_no_drive_is_local() -> None:
    """``\\folder\\file`` is on whichever drive the process runs from.

    **Test steps:**

    * classify a path with a root but no drive
    * verify it is local
    """
    assert device_of(Path("\\folder\\file.rehu")).kind is StorageKind.LOCAL


@mark.windows
def test_windows_a_unc_path_is_smb_on_its_host() -> None:
    """A UNC path is remote by its form and names its server, which is asked on 445 -- without asking the OS.

    **Test steps:**

    * classify a UNC path
    * verify a network device rooted at the share with the host and the SMB port
    """
    device = device_of(Path("\\\\nas\\share\\folder\\file.rehu"))

    assert device == Device(StorageKind.NETWORK, Path("\\\\nas\\share\\"), "nas", 445)


@mark.windows
def test_windows_a_wsl_path_has_no_port_to_probe() -> None:
    """``wsl.localhost`` is a 9P server, not SMB.

    **Test steps:**

    * classify a path under ``\\\\wsl.localhost``
    * verify it is network, with the host and no port
    """
    device = device_of(Path("\\\\wsl.localhost\\Ubuntu\\home\\me\\file.rehu"))

    assert device.kind is StorageKind.NETWORK
    assert device.host == "wsl.localhost"
    assert device.port is None


@mark.windows
def test_windows_a_mapped_drive_names_its_share_host(mocker: MockerFixture) -> None:
    """A network drive letter takes its server from the share it maps to.

    **Test steps:**

    * make the drive classifier say a letter is remote and map to a share
    * verify a network device rooted at the letter with the share's host and the SMB port
    """
    mocker.patch("borco_core.platforms.windows.drives.drive_type", return_value=4)
    share = mocker.patch("borco_core.platforms.windows.drives.mapped_share", return_value="\\\\nas\\share")

    device = device_of(Path("W:\\folder\\file.rehu"))

    assert device == Device(StorageKind.NETWORK, Path("W:\\"), "nas", 445)
    share.assert_called_once_with("W:")


@mark.windows
def test_windows_a_mapped_drive_without_a_share_has_no_host(mocker: MockerFixture) -> None:
    """A remote letter whose share cannot be read is still network, with nobody to ask.

    **Test steps:**

    * make the drive classifier say a letter is remote and map to no share
    * verify a network device with neither host nor port
    """
    mocker.patch("borco_core.platforms.windows.drives.drive_type", return_value=4)
    mocker.patch("borco_core.platforms.windows.drives.mapped_share", return_value=None)

    device = device_of(Path("W:\\file.rehu"))

    assert device.kind is StorageKind.NETWORK
    assert device.host is None
    assert device.port is None


@mark.windows
def test_windows_a_cd_drive_is_optical(mocker: MockerFixture) -> None:
    """A CD-ROM letter is a disc.

    **Test steps:**

    * make the drive classifier say a letter is a CD-ROM
    * verify an optical device rooted at the letter
    """
    mocker.patch("borco_core.platforms.windows.drives.drive_type", return_value=5)

    assert device_of(Path("E:\\file.rehu")) == Device(StorageKind.OPTICAL, Path("E:\\"))


@mark.windows
def test_windows_a_ram_disk_is_local(mocker: MockerFixture) -> None:
    """A RAM disk is on this machine.

    **Test steps:**

    * make the drive classifier say a letter is a RAM disk
    * verify a local device rooted at the letter
    """
    mocker.patch("borco_core.platforms.windows.drives.drive_type", return_value=6)

    assert device_of(Path("R:\\file.rehu")) == Device(StorageKind.LOCAL, Path("R:\\"))


@mark.windows
def test_windows_the_system_drive_is_local(tmp_path: Path) -> None:
    """A fixed drive is local -- a fact about this machine, so it is asked of it.

    **Test steps:**

    * classify a path in the temporary folder, which is on a fixed drive
    * verify it is local and rooted at the drive
    """
    device = device_of(tmp_path)

    assert device.is_local
    assert device.root == Path(tmp_path.anchor)


@mark.windows
@mark.parametrize("kind", [1, 2, 0])
def test_windows_a_removable_or_missing_drive_is_removable(mocker: MockerFixture, kind: int) -> None:
    """A removable drive, and a letter with nothing behind it (an unplugged one), are removable.

    **Test steps:**

    * make the drive classifier say a letter is removable, has no root, or is unknown
    * verify a removable device rooted at the letter
    """
    mocker.patch("borco_core.platforms.windows.drives.drive_type", return_value=kind)

    assert device_of(Path("U:\\file.rehu")) == Device(StorageKind.REMOVABLE, Path("U:\\"))


@mark.windows
def test_windows_a_letter_nothing_is_mapped_to_is_removable() -> None:
    """The real answer for an unused letter is ``DRIVE_NO_ROOT_DIR``, which reads as unplugged.

    **Test steps:**

    * classify a path on the first drive letter nothing is mounted at
    * verify it is removable
    """
    letter = next((c for c in "ZYXWVUTSRQPONMLKJIHGFED" if not Path(f"{c}:\\").exists()), None)
    if letter is None:
        pytest.skip("every drive letter is in use")

    assert device_of(Path(f"{letter}:\\file.rehu")).kind is StorageKind.REMOVABLE


# --- _exists / _volume_present / _reachable ----------------------------------------------------------------------


@mark.disk
def test_exists_tells_present_from_absent(tmp_path: Path) -> None:
    """A stat that finds the file says ``True``; one that finds nothing, or a file where a folder should be, ``False``.

    **Test steps:**

    * stat a file, a missing file, and a path below a file
    * verify ``True``, ``False`` and ``False``
    """
    present = tmp_path / "file"
    present.write_bytes(b"x")

    assert path_presence._exists(present) is True  # pylint: disable=protected-access
    assert path_presence._exists(tmp_path / "missing") is False  # pylint: disable=protected-access
    assert path_presence._exists(present / "below") is False  # pylint: disable=protected-access


def test_exists_without_a_verdict_is_none(mocker: MockerFixture) -> None:
    """A permission error is not an absence.

    **Test steps:**

    * make the stat raise a permission error
    * verify the answer is ``None``
    """
    mocker.patch(f"{MODULE}.os.stat", side_effect=PermissionError)

    assert path_presence._exists(FILE) is None  # pylint: disable=protected-access


@pytest.mark.parametrize(("found", "expected"), [(True, True), (False, False), (None, False)])
def test_windows_a_volume_is_present_when_its_root_exists(
    mocker: MockerFixture, found: bool | None, expected: bool
) -> None:
    """On Windows the volume is there when its drive root can be stat-ed; no verdict is not presence.

    **Test steps:**

    * force Windows and make the stat of the root answer ``True``, ``False`` or no verdict
    * verify the volume is present only for ``True``
    """
    mocker.patch(f"{MODULE}.sys.platform", "win32")
    mocker.patch(f"{MODULE}._exists", return_value=found)

    assert path_presence._volume_present(Path("/vol")) is expected  # pylint: disable=protected-access


@pytest.mark.parametrize("mounted", [True, False])
def test_posix_a_volume_is_present_when_it_is_a_mount_point(mocker: MockerFixture, mounted: bool) -> None:
    """On POSIX the volume is there when its folder is a mount point.

    **Test steps:**

    * force Linux and make the mount-point check answer ``True`` or ``False``
    * verify the volume follows it
    """
    mocker.patch(f"{MODULE}.sys.platform", "linux")
    mocker.patch(f"{MODULE}.os.path.ismount", return_value=mounted)

    assert path_presence._volume_present(Path("/vol")) is mounted  # pylint: disable=protected-access


@pytest.mark.parametrize("device", [network(host=None), network(port=None), local()])
def test_reachable_where_there_is_no_server_to_ask(probe: Probe, device: Device) -> None:
    """With no host or no port there is nobody to probe, and the answer is yes without a connection.

    **Test steps:**

    * ask about devices with no host, no port, and a local one
    * verify each is reachable and no connection was made
    """
    assert path_presence._reachable(device) is True  # pylint: disable=protected-access
    assert not probe.calls


def test_reachable_when_the_server_accepts(probe: Probe) -> None:
    """A server that accepts a connection within the limit is reachable.

    **Test steps:**

    * ask about a server whose connection succeeds
    * verify it is reachable and was asked once, on its port, with the timeout
    """
    assert path_presence._reachable(network()) is True  # pylint: disable=protected-access
    assert probe.calls == [(("nas", 445), REACH_TIMEOUT)]


def test_unreachable_when_the_connection_fails(probe: Probe) -> None:
    """A refused or timed-out connection means the server is off.

    **Test steps:**

    * ask about a server whose connection times out
    * verify it is not reachable
    """
    probe.error = TimeoutError()

    assert path_presence._reachable(network()) is False  # pylint: disable=protected-access


# --- _judge / presence_of ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("found", "verdict"), [(True, Presence.PRESENT), (False, Presence.GONE), (None, Presence.OFFLINE)]
)
def test_judge_local(mocker: MockerFixture, found: bool | None, verdict: Presence) -> None:
    """On a fixed local drive the stat alone decides, and the server is never asked.

    **Test steps:**

    * judge a path on a local device with the stat answering ``True``, ``False`` or no verdict
    * verify present, gone, and offline, with the server check never called
    """
    mocker.patch(f"{MODULE}._exists", return_value=found)
    reachable = mocker.Mock(return_value=True)

    assert path_presence._judge(FILE, local(), reachable) is verdict  # pylint: disable=protected-access
    reachable.assert_not_called()


def test_judge_an_unreachable_server_is_offline(mocker: MockerFixture) -> None:
    """A server that does not answer proves nothing, and the file is not even stat-ed.

    **Test steps:**

    * judge a network path whose server check says no
    * verify offline and no stat
    """
    stat = mocker.patch(f"{MODULE}._exists")

    assert path_presence._judge(FILE, network(), lambda: False) is Presence.OFFLINE  # pylint: disable=protected-access
    stat.assert_not_called()


@pytest.mark.parametrize(("found", "verdict"), [(True, Presence.PRESENT), (None, Presence.OFFLINE)])
def test_judge_a_reachable_server_with_a_verdict_or_none(
    mocker: MockerFixture, found: bool | None, verdict: Presence
) -> None:
    """Past a server that answered, a found file is present and a stat with no verdict is offline.

    **Test steps:**

    * judge a network path on a reachable server with the stat answering ``True`` or no verdict
    * verify present and offline
    """
    mocker.patch(f"{MODULE}._exists", return_value=found)

    assert path_presence._judge(FILE, network(), lambda: True) is verdict  # pylint: disable=protected-access


def test_judge_a_file_missing_from_a_disc_is_never_gone(mocker: MockerFixture) -> None:
    """What is in the drive is whatever was last put in it.

    **Test steps:**

    * judge an absent path on an optical device whose volume reads as present
    * verify offline
    """
    mocker.patch(f"{MODULE}._exists", return_value=False)
    mocker.patch(f"{MODULE}._volume_present", return_value=True)
    disc = Device(StorageKind.OPTICAL, Path("/media/cd"))

    assert path_presence._judge(FILE, disc, lambda: True) is Presence.OFFLINE  # pylint: disable=protected-access


def test_judge_a_missing_volume_is_offline(mocker: MockerFixture) -> None:
    """A removable volume that is not there holds the file somewhere out of reach.

    **Test steps:**

    * judge an absent path on a removable device whose volume is absent
    * verify offline
    """
    mocker.patch(f"{MODULE}._exists", return_value=False)
    mocker.patch(f"{MODULE}._volume_present", return_value=False)
    usb = Device(StorageKind.REMOVABLE, Path("/Volumes/USB"))

    assert path_presence._judge(FILE, usb, lambda: True) is Presence.OFFLINE  # pylint: disable=protected-access


@pytest.mark.parametrize("device", [Device(StorageKind.REMOVABLE, Path("/Volumes/USB")), network()])
def test_judge_a_file_missing_from_a_present_volume_is_gone(mocker: MockerFixture, device: Device) -> None:
    """The device answered and does not hold the file.

    **Test steps:**

    * judge an absent path on a removable and on a network device whose volume is present
    * verify gone
    """
    mocker.patch(f"{MODULE}._exists", return_value=False)
    mocker.patch(f"{MODULE}._volume_present", return_value=True)

    assert path_presence._judge(FILE, device, lambda: True) is Presence.GONE  # pylint: disable=protected-access


def test_presence_of_classifies_the_path_when_not_told(mocker: MockerFixture) -> None:
    """Without a device the path is classified, with the table the caller passed.

    **Test steps:**

    * replace the classifier with one answering a local device, and the stat with one finding the file
    * ask with a mount table
    * verify the answer is present and the classifier got the path and the table
    """
    classify = mocker.patch(f"{MODULE}.device_of", return_value=local())
    mocker.patch(f"{MODULE}._exists", return_value=True)
    mounts = [NAS_MOUNT]

    assert presence_of(FILE, mounts) is Presence.PRESENT
    classify.assert_called_once_with(FILE, mounts)


def test_presence_of_trusts_a_device_it_is_given(mocker: MockerFixture, probe: Probe) -> None:
    """A caller that already classified the path is not made to do it twice, and a dead server is offline.

    **Test steps:**

    * replace the classifier, and make the server refuse connections
    * ask about a path with a network device
    * verify offline, the classifier never called, and the server probed
    """
    classify = mocker.patch(f"{MODULE}.device_of")
    probe.error = ConnectionRefusedError()

    assert presence_of(FILE, device=network()) is Presence.OFFLINE
    classify.assert_not_called()
    assert probe.calls


@mark.disk
def test_presence_of_a_real_local_file(tmp_path: Path) -> None:
    """A file on a local device is present while it exists and gone after.

    **Test steps:**

    * write a file and ask with a local device, then delete it and ask again
    * verify present and then gone
    """
    path = tmp_path / "file.rehu"
    path.write_bytes(b"x")
    device = Device(StorageKind.LOCAL, Path(path.anchor))

    assert presence_of(path, device=device) is Presence.PRESENT

    path.unlink()

    assert presence_of(path, device=device) is Presence.GONE
