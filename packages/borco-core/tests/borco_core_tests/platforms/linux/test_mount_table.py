"""Tests for the Linux/macOS mount-table reader (#464).

Importable on any OS, like the module: the two parsers are text in, mounts out, and :func:`read_mounts` is tested
with its file and its ``mount`` command replaced, so none of this reads the developer's real mount table.
"""

import subprocess
from pathlib import Path
from typing import Final

import pytest
from borco_core.platforms.linux import mount_table
from borco_core.platforms.linux.mount_table import Mount, parse_mount_command, parse_proc_mounts, read_mounts
from pytest_mock import MockerFixture

MODULE: Final = "borco_core.platforms.linux.mount_table"
"""Module path prefix for the patch targets below."""


def test_a_proc_line_gives_device_point_and_type() -> None:
    """The first three fields of a ``/proc/self/mounts`` line are what is mounted, where, and as what.

    **Test steps:**

    * parse a CIFS line and an ext4 line
    * verify both mounts, in file order, with the options and dump fields ignored
    """
    text = "//nas/share /mnt/nas cifs rw,relatime 0 0\n/dev/sda1 / ext4 rw 0 0\n"

    assert parse_proc_mounts(text) == [
        Mount("//nas/share", Path("/mnt/nas"), "cifs"),
        Mount("/dev/sda1", Path("/"), "ext4"),
    ]


def test_a_proc_octal_escape_is_a_space() -> None:
    """``/proc`` writes a space inside a field as ``\\040``.

    **Test steps:**

    * parse a line whose device and mount point both contain an escaped space
    * verify the spaces are restored
    """
    mounts = parse_proc_mounts("//nas/my\\040share /mnt/my\\040disk cifs rw 0 0")

    assert mounts == [Mount("//nas/my share", Path("/mnt/my disk"), "cifs")]


def test_a_proc_filesystem_type_is_lower_case() -> None:
    """The type is normalised so the module's lookup sets, which are lower case, match.

    **Test steps:**

    * parse a line with an upper-case type
    * verify the type comes back lower case
    """
    assert parse_proc_mounts("//nas/share /mnt/nas CIFS rw 0 0")[0].fstype == "cifs"


def test_a_short_or_blank_proc_line_is_skipped() -> None:
    """A line without three fields is not a mount.

    **Test steps:**

    * parse text made of a blank line, a two-field line and one good line
    * verify only the good line is returned
    """
    mounts = parse_proc_mounts("\nonly two\n/dev/sda1 / ext4 rw 0 0\n")

    assert mounts == [Mount("/dev/sda1", Path("/"), "ext4")]


def test_a_mount_command_line_gives_device_point_and_type() -> None:
    """macOS prints ``device on point (type, options...)``; the type is the first option.

    **Test steps:**

    * parse an smbfs line and an apfs line
    * verify both mounts, in output order
    """
    text = "//user@nas/share on /Volumes/share (smbfs, nodev, nosuid)\n/dev/disk3s1 on / (apfs, local)\n"

    assert parse_mount_command(text) == [
        Mount("//user@nas/share", Path("/Volumes/share"), "smbfs"),
        Mount("/dev/disk3s1", Path("/"), "apfs"),
    ]


def test_a_mount_command_point_may_hold_spaces() -> None:
    """A mount point with a space is matched whole, and an upper-case type is lowered.

    **Test steps:**

    * parse a line whose point contains a space and whose type is upper case
    * verify the point is complete and the type lower case
    """
    mounts = parse_mount_command("/dev/disk4s1 on /Volumes/My Disk (MSDOS, local)")

    assert mounts == [Mount("/dev/disk4s1", Path("/Volumes/My Disk"), "msdos")]


def test_a_mount_command_line_in_another_shape_is_skipped() -> None:
    """Anything that is not ``device on /point (options)`` is ignored.

    **Test steps:**

    * parse a blank line, a line without options and one without an absolute point
    * verify nothing is returned
    """
    assert not parse_mount_command("\nnothing to see here\nmap auto_home on auto_home (autofs)\n")


def test_a_network_mount_names_its_host_and_port() -> None:
    """A ``//host/share`` device names its server, and the filesystem names the port.

    **Test steps:**

    * build CIFS mounts with a bare and a ``user@`` device
    * verify both are network, serve from ``nas`` and are asked on 445
    """
    for device in ("//nas/share", "//user@nas/share"):
        mount = Mount(device, Path("/mnt/nas"), "cifs")

        assert mount.is_network
        assert not mount.is_optical
        assert mount.host == "nas"
        assert mount.port == 445


def test_an_nfs_mount_names_its_host_before_the_colon() -> None:
    """``host:/export`` is how NFS names its server; it is asked on 2049.

    **Test steps:**

    * build an NFS mount
    * verify host and port
    """
    mount = Mount("nas:/export", Path("/mnt/nfs"), "nfs4")

    assert mount.host == "nas"
    assert mount.port == 2049


def test_a_network_filesystem_without_a_known_port_has_a_host_but_no_port() -> None:
    """sshfs is a network filesystem with nothing to probe.

    **Test steps:**

    * build an sshfs mount
    * verify it is network, has a host and has no port
    """
    mount = Mount("user@box:/dir", Path("/mnt/box"), "fuse.sshfs")

    assert mount.is_network
    assert mount.host == "box"
    assert mount.port is None


def test_a_network_device_that_names_no_host_has_neither_host_nor_port() -> None:
    """An empty host is no host, so there is no port to ask either.

    **Test steps:**

    * build network mounts whose devices name no server
    * verify host and port are ``None``
    """
    for device in ("//", ":/export"):
        mount = Mount(device, Path("/mnt/x"), "cifs")

        assert mount.host is None
        assert mount.port is None


def test_a_local_mount_has_no_host_or_port() -> None:
    """Only a network mount has a server.

    **Test steps:**

    * build an ext4 mount
    * verify it is not network and has no host or port
    """
    mount = Mount("/dev/sda1", Path("/"), "ext4")

    assert not mount.is_network
    assert mount.host is None
    assert mount.port is None


def test_a_disc_is_optical() -> None:
    """iso9660 is a disc.

    **Test steps:**

    * build an iso9660 mount
    * verify it is optical and not network
    """
    mount = Mount("/dev/sr0", Path("/media/cd"), "iso9660")

    assert mount.is_optical
    assert not mount.is_network


def test_linux_reads_the_proc_table(mocker: MockerFixture, tmp_path: Path) -> None:
    """On Linux the mounts come from ``/proc/self/mounts``.

    **Test steps:**

    * force Linux and point the table at a file holding one line
    * verify the line is returned as a mount
    """
    table = tmp_path / "mounts"
    table.write_text("/dev/sda1 / ext4 rw 0 0\n", encoding="utf-8")
    mocker.patch(f"{MODULE}.sys.platform", "linux")
    mocker.patch(f"{MODULE}.PROC_MOUNTS", table)

    assert read_mounts() == [Mount("/dev/sda1", Path("/"), "ext4")]


def test_linux_without_a_readable_table_has_no_mounts(mocker: MockerFixture, tmp_path: Path) -> None:
    """A table that cannot be read is an empty one, not an error.

    **Test steps:**

    * force Linux and point the table at a file that does not exist
    * verify the result is empty
    """
    mocker.patch(f"{MODULE}.sys.platform", "linux")
    mocker.patch(f"{MODULE}.PROC_MOUNTS", tmp_path / "missing")

    assert not read_mounts()


def test_macos_runs_mount_and_parses_it(mocker: MockerFixture) -> None:
    """On macOS the mounts come from the output of ``/sbin/mount``.

    **Test steps:**

    * force macOS and replace the subprocess call with one printing a line
    * verify the line is returned as a mount and the fixed executable was the one run
    """
    mocker.patch(f"{MODULE}.sys.platform", "darwin")
    run = mocker.patch(
        f"{MODULE}.subprocess.run",
        return_value=subprocess.CompletedProcess([], 0, stdout="/dev/disk3s1 on / (apfs, local)\n"),
    )

    assert read_mounts() == [Mount("/dev/disk3s1", Path("/"), "apfs")]
    assert run.call_args.args == ([mount_table.MOUNT_COMMAND],)


@pytest.mark.parametrize("error", [FileNotFoundError("no mount"), subprocess.TimeoutExpired("mount", 5)])
def test_macos_with_a_failing_mount_has_no_mounts(mocker: MockerFixture, error: Exception) -> None:
    """A ``mount`` that is missing or hangs is an empty table.

    **Test steps:**

    * force macOS and make the subprocess call raise an ``OSError`` or a ``SubprocessError``
    * verify the result is empty
    """
    mocker.patch(f"{MODULE}.sys.platform", "darwin")
    mocker.patch(f"{MODULE}.subprocess.run", side_effect=error)

    assert not read_mounts()


def test_windows_has_no_mount_table(mocker: MockerFixture) -> None:
    """Neither source applies elsewhere.

    **Test steps:**

    * force Windows
    * verify the result is empty
    """
    mocker.patch(f"{MODULE}.sys.platform", "win32")

    assert not read_mounts()
