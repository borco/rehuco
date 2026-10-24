"""Tests for a root's machine-independent location and for finding it on a machine (#514).

The POSIX half is fed a mount table and a forced ``linux`` platform, so no real table is read and it runs on every OS;
the Windows half asks the running machine (its system drive) with the share calls replaced, and carries ``windows``.
Nothing here touches the network.
"""

import os
from pathlib import Path
from typing import Final

import pytest
from borco_core.platforms.linux.mount_table import Mount
from pytest import mark, raises
from pytest_mock import MockerFixture
from rehuco_core.rehuco_file import RootStorage
from rehuco_core.root_location import (
    location_of,
    machine_name,
    mount_share,
    resolve_location,
    share_location,
    storage_of,
)

MODULE: Final = "rehuco_core.root_location"
"""Where the platform, the host name and the table reader are patched."""

ROOT: Final = Path(Path.cwd().anchor)
"""A root a fake absolute path can hang from on any OS."""

NAS: Final = Mount("//nas/data", ROOT / "mnt" / "nas", "cifs")
USER_NAS: Final = Mount("//me@NAS/data", ROOT / "mnt" / "user_nas", "smbfs")
EXPORT: Final = Mount("nas:/export", ROOT / "mnt" / "export", "nfs")
DISC: Final = Mount("/dev/sr0", ROOT / "media" / "disc", "iso9660")


@pytest.fixture(name="linux", autouse=False)
def linux_fixture(mocker: MockerFixture) -> None:
    """Judge paths as a Linux machine named ``ryzen-5600`` would, whatever the test runs on."""
    mocker.patch(f"{MODULE}.sys.platform", "linux")
    mocker.patch("borco_core.path_presence.sys.platform", "linux")
    mocker.patch(f"{MODULE}.socket.gethostname", return_value="Ryzen-5600.local")


def test_the_machine_name_is_the_first_label_in_lower_case(mocker: MockerFixture) -> None:
    """A location spells the machine the same on every box, so the name is the short, lower-case one.

    **Test steps:**

    * replace the host name with ``Ryzen-5600.local``
    * verify the machine name is ``ryzen-5600``
    """
    mocker.patch(f"{MODULE}.socket.gethostname", return_value="Ryzen-5600.local")

    assert machine_name() == "ryzen-5600"


def test_a_cifs_mount_is_a_share_location() -> None:
    """The server and share of a CIFS mount are its location.

    **Test steps:**

    * ask the share of a ``//nas/data`` mount
    * verify it is ``//nas/data``
    """
    assert mount_share(NAS) == "//nas/data"


def test_a_user_and_a_host_case_do_not_reach_the_location() -> None:
    """``//me@NAS/data`` and ``//nas/data`` are one place.

    **Test steps:**

    * ask the share of a mount whose device carries a user name and a capitalized host
    * verify the user is gone and the host is lower case
    """
    assert mount_share(USER_NAS) == "//nas/data"


def test_an_nfs_export_is_a_share_location() -> None:
    """``nas:/export`` reads as ``//nas/export``.

    **Test steps:**

    * ask the share of an NFS mount
    * verify it is ``//nas/export``
    """
    assert mount_share(EXPORT) == "//nas/export"


def test_a_server_with_no_share_is_just_the_server() -> None:
    """A device naming only a server has no share part.

    **Test steps:**

    * ask the share of ``//nas`` and of an NFS ``nas`` with no export
    * verify both are ``//nas``
    """
    assert mount_share(Mount("//nas", ROOT / "a", "cifs")) == "//nas"
    assert mount_share(Mount("nas", ROOT / "b", "nfs")) == "//nas"


def test_a_local_mount_is_no_share() -> None:
    """Only a network mount names a server.

    **Test steps:**

    * ask the share of a disc mount
    * verify there is none
    """
    assert mount_share(DISC) is None


def test_a_windows_share_is_spelled_as_a_location() -> None:
    """``\\\\NAS\\data\\`` becomes ``//nas/data``.

    **Test steps:**

    * spell two UNC shares, one with a trailing separator and one with a nested name
    * verify the host is lower case and the separators are slashes
    """
    assert share_location("\\\\NAS\\data\\") == "//nas/data"
    assert share_location("\\\\nas\\data\\sub") == "//nas/data/sub"


@pytest.mark.usefixtures("linux")
def test_a_path_on_a_share_is_located_by_the_share() -> None:
    """A folder on a mounted share has the share's location, whatever the mount point.

    **Test steps:**

    * locate a folder under the ``//nas/data`` mount
    * verify the location is the share plus the folder's path under the mount
    """
    path = ROOT / "mnt" / "nas" / "Tutorials" / "Krita"

    assert location_of(path, [NAS]) == "//nas/data/Tutorials/Krita"


@pytest.mark.usefixtures("linux")
def test_the_deepest_mount_wins() -> None:
    """A share mounted inside another is located by the inner one.

    **Test steps:**

    * locate a folder under two nested network mounts
    * verify the inner mount's share is used
    """
    inner = Mount("//nas/more", NAS.point / "more", "cifs")

    assert location_of(inner.point / "x", [NAS, inner]) == "//nas/more/x"


@pytest.mark.usefixtures("linux")
def test_a_path_on_a_local_disk_is_located_by_the_machine() -> None:
    """A folder on this machine's own disk is the machine's name and the path.

    **Test steps:**

    * locate a folder that no network mount holds
    * verify the location starts with the machine name followed by the path
    """
    path = ROOT / "home" / "me" / "FOO"

    assert location_of(path, [NAS]) == "//ryzen-5600/home/me/FOO"


@pytest.mark.usefixtures("linux")
def test_a_network_mount_with_no_server_is_local() -> None:
    """A mount whose device names no server cannot give a location, so the path is this machine's own.

    **Test steps:**

    * locate a folder under a CIFS mount with an empty device
    * verify the machine's name is used
    """
    nameless = Mount("", ROOT / "mnt" / "odd", "cifs")

    assert location_of(nameless.point / "x", [nameless]) == "//ryzen-5600/mnt/odd/x"


@pytest.mark.usefixtures("linux")
def test_the_mount_table_is_read_when_none_is_given(mocker: MockerFixture) -> None:
    """A caller locating one path lets the function read the table.

    **Test steps:**

    * replace the table reader with one returning the NAS mount
    * locate a folder under it without passing a table
    * verify the reader was used and the share is the location
    """
    read = mocker.patch(f"{MODULE}.read_mounts", return_value=[NAS])

    assert location_of(NAS.point / "x") == "//nas/data/x"
    read.assert_called_once_with()


def test_a_relative_path_has_no_location() -> None:
    """A location is of a place, so the path must name one.

    **Test steps:**

    * locate a relative path
    * verify it is refused
    """
    with raises(ValueError, match="absolute"):
        location_of(Path("relative/folder"))


@pytest.mark.usefixtures("linux")
def test_a_share_this_machine_mounts_is_found() -> None:
    """The mount table says where a share is on this machine.

    **Test steps:**

    * resolve a location on the NAS's share against a table holding its mount
    * verify the folder is under the mount point
    """
    assert resolve_location("//nas/data/Tutorials", [NAS]) == NAS.point / "Tutorials"


@pytest.mark.usefixtures("linux")
def test_a_share_is_found_whatever_the_case_or_the_user() -> None:
    """The host and share compare without case, and a mount's user name does not matter.

    **Test steps:**

    * resolve ``//NAS/DATA/x`` against a mount of ``//me@NAS/data``
    * verify the folder is found under the mount point
    """
    assert resolve_location("//NAS/DATA/x", [USER_NAS]) == USER_NAS.point / "x"


@pytest.mark.usefixtures("linux")
def test_the_share_itself_is_its_mount_point() -> None:
    """A location with nothing after the share is the mount point.

    **Test steps:**

    * resolve ``//nas/data``
    * verify the mount point
    """
    assert resolve_location("//nas/data", [NAS]) == NAS.point


@pytest.mark.usefixtures("linux")
def test_the_longest_matching_share_is_used() -> None:
    """A location under two mounted shares, one inside the other, resolves through the longer.

    **Test steps:**

    * resolve a location under ``//nas/data/more`` against mounts of it and of ``//nas/data``
    * verify the folder is under the longer one's mount point
    """
    inner = Mount("//nas/data/more", ROOT / "mnt" / "inner", "cifs")

    assert resolve_location("//nas/data/more/x", [NAS, inner]) == inner.point / "x"
    assert resolve_location("//nas/data/more/x", [inner, NAS]) == inner.point / "x"
    assert resolve_location("//nas/data/other/x", [NAS, inner]) == NAS.point / "other" / "x"


@pytest.mark.usefixtures("linux")
def test_a_share_this_machine_has_not_mounted_is_not_found() -> None:
    """Nothing is guessed for a server or share the table does not hold.

    **Test steps:**

    * resolve a location on another share, one on another server, and a local-disk mount's name
    * verify none is found
    """
    assert resolve_location("//nas/other/x", [NAS, DISC]) is None
    assert resolve_location("//elsewhere/data/x", [NAS]) is None
    assert resolve_location("//nas/database/x", [NAS]) is None


@pytest.mark.usefixtures("linux")
def test_a_text_that_is_no_location_is_not_found() -> None:
    """Only a ``//host/...`` text is a location.

    **Test steps:**

    * resolve a plain path
    * verify it is not found
    """
    assert resolve_location("/mnt/nas/x", [NAS]) is None


@pytest.mark.usefixtures("linux")
def test_a_location_on_this_machine_is_its_own_folder() -> None:
    """A location naming this machine needs no table.

    **Test steps:**

    * resolve ``//ryzen-5600/home/me/FOO``
    * verify the folder is ``/home/me/FOO``
    """
    assert resolve_location("//Ryzen-5600/home/me/FOO", []) == Path("/home/me/FOO")


@pytest.mark.usefixtures("linux")
def test_resolving_reads_the_mount_table_when_none_is_given(mocker: MockerFixture) -> None:
    """A caller resolving one location lets the function read the table.

    **Test steps:**

    * replace the table reader with one returning the NAS mount
    * resolve a location without passing a table
    * verify the reader was used
    """
    read = mocker.patch(f"{MODULE}.read_mounts", return_value=[NAS])

    assert resolve_location("//nas/data/x") == NAS.point / "x"
    read.assert_called_once_with()


@pytest.mark.usefixtures("linux")
def test_the_storage_is_detected_from_the_table() -> None:
    """A mounted share is network, a disc is a compact disk, anything else is local.

    **Test steps:**

    * detect the storage under a CIFS mount, under a disc mount and under neither
    * verify network, compact disk and local
    """
    mounts = [NAS, DISC]

    assert storage_of(NAS.point / "x", mounts) is RootStorage.NETWORK
    assert storage_of(DISC.point / "x", mounts) is RootStorage.COMPACT_DISK
    assert storage_of(ROOT / "home" / "me", mounts) is RootStorage.LOCAL


@mark.windows
def test_a_unc_path_is_located_by_its_share(mocker: MockerFixture) -> None:
    """A UNC path needs no drive table: its share is its location.

    **Test steps:**

    * locate a folder spelled ``\\\\NAS\\data\\Tutorials``
    * verify ``//nas/data/Tutorials``
    """
    mocker.patch(f"{MODULE}.socket.gethostname", return_value="ryzen-5600")

    assert location_of(Path("\\\\NAS\\data\\Tutorials")) == "//nas/data/Tutorials"


@mark.windows
def test_a_mapped_drive_is_located_by_its_share(mocker: MockerFixture) -> None:
    """A path on a mapped drive letter is located by the share the letter maps.

    **Test steps:**

    * make the drive classify as a network one and map to ``\\\\nas\\data``
    * locate ``W:\\Tutorials\\Krita``
    * verify ``//nas/data/Tutorials/Krita``
    """
    from borco_core.path_presence import Device, StorageKind  # pylint: disable=import-outside-toplevel

    mocker.patch(f"{MODULE}.device_of", return_value=Device(StorageKind.NETWORK, Path("W:\\"), "nas"))
    mocker.patch("borco_core.platforms.windows.drives.mapped_share", return_value="\\\\nas\\data")

    assert location_of(Path("W:\\Tutorials\\Krita")) == "//nas/data/Tutorials/Krita"


@mark.windows
def test_a_local_drive_is_located_by_the_machine(mocker: MockerFixture) -> None:
    """A fixed drive's location is the machine, the lower-case letter and the path.

    **Test steps:**

    * locate a folder on the system drive
    * verify ``//ryzen-5600/<letter>/...``
    """
    mocker.patch(f"{MODULE}.socket.gethostname", return_value="ryzen-5600")
    system = os.environ.get("SystemDrive", "C:")

    assert location_of(Path(f"{system}\\Users\\me")) == f"//ryzen-5600/{system[0].lower()}/Users/me"


@mark.windows
def test_a_drive_that_maps_to_no_share_is_located_by_the_machine(mocker: MockerFixture) -> None:
    """A network letter whose share cannot be read falls back to the machine's own spelling.

    **Test steps:**

    * make the drive classify as a network one that maps to nothing
    * locate a folder on it
    * verify the machine's location
    """
    from borco_core.path_presence import Device, StorageKind  # pylint: disable=import-outside-toplevel

    mocker.patch(f"{MODULE}.socket.gethostname", return_value="ryzen-5600")
    mocker.patch(f"{MODULE}.device_of", return_value=Device(StorageKind.NETWORK, Path("W:\\"), None))
    mocker.patch("borco_core.platforms.windows.drives.mapped_share", return_value=None)

    assert location_of(Path("W:\\x")) == "//ryzen-5600/w/x"


@mark.windows
def test_a_location_on_this_machine_is_its_drive(mocker: MockerFixture) -> None:
    """``//ryzen-5600/d/Downloads`` is ``D:\\Downloads`` here; a first segment that is no letter is nothing.

    **Test steps:**

    * resolve a location on this machine with a drive letter, with none, and with a long name
    * verify ``D:\\Downloads\\FOO`` and then ``None`` twice
    """
    mocker.patch(f"{MODULE}.socket.gethostname", return_value="ryzen-5600")

    assert resolve_location("//ryzen-5600/d/Downloads/FOO") == Path("D:\\Downloads\\FOO")
    assert resolve_location("//ryzen-5600") is None
    assert resolve_location("//ryzen-5600/users/me") is None


@mark.windows
def test_a_share_is_found_through_a_mapped_drive(mocker: MockerFixture) -> None:
    """The drive letter mapped to the location's share is where it is on this machine.

    **Test steps:**

    * replace the mapped drives with ``W:`` -> ``\\\\nas\\data``
    * resolve ``//NAS/data/Tutorials``, a share no letter maps, and a bare server
    * verify ``W:\\Tutorials``, then ``None`` twice
    """
    mocker.patch(f"{MODULE}.socket.gethostname", return_value="ryzen-5600")
    mocker.patch("borco_core.platforms.windows.drives.mapped_drives", return_value={"W:": "\\\\nas\\data"})

    assert resolve_location("//NAS/data/Tutorials") == Path("W:\\Tutorials")
    assert resolve_location("//nas/other/x") is None
    assert resolve_location("//nas") is None
