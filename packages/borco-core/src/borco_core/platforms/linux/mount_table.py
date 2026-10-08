"""The mounted filesystems of a Linux or macOS machine, read as text -- the one source that says, without touching a
mount, which of them is a network share and which host serves it.

Importable (and testable) on any OS, like its siblings in this package: it is text parsing plus one read of a file or
one run of ``mount``. Only :func:`read_mounts` is platform-bound.

Two formats, one result:

- Linux, ``/proc/self/mounts``: ``//nas/share /mnt/nas cifs rw,... 0 0`` -- a space-separated line, with a space in a
  field written as the octal escape ``\\040``.
- macOS, the output of ``mount``: ``//user@nas/share on /Volumes/share (smbfs, nodev, nosuid)``.
"""

import re
import subprocess  # nosec B404  # only ever runs the one fixed ``mount`` listing below
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

PROC_MOUNTS: Final = Path("/proc/self/mounts")
MOUNT_COMMAND: Final = "/sbin/mount"
"""macOS's ``mount``, by absolute path: nothing is resolved off ``PATH``."""

NETWORK_PORTS: Final = {"cifs": 445, "smb3": 445, "smbfs": 445, "smb": 445, "nfs": 2049, "nfs4": 2049}
"""The filesystems whose server answers on a port this can ask, and the port. A *network* filesystem not named here
(see :data:`NETWORK_TYPES`) is still network; it just has no port to probe."""

NETWORK_TYPES: Final = frozenset(
    {*NETWORK_PORTS, "afpfs", "fuse.sshfs", "sshfs", "davfs", "fuse.davfs", "webdav", "9p", "ceph", "glusterfs", "afs"}
)
OPTICAL_TYPES: Final = frozenset({"iso9660", "udf", "cd9660", "cddafs"})
"""A disc: what is mounted there is whatever was last put in the drive, so a path that is not on it proves nothing."""

PROC_ESCAPE: Final = re.compile(r"\\([0-7]{3})")
MOUNT_LINE: Final = re.compile(r"^(?P<device>.+?) on (?P<point>/.*?) \((?P<options>[^)]*)\)\s*$")
USER_PREFIX: Final = re.compile(r"^[^@/]*@")


@dataclass(frozen=True)
class Mount:
    """One mounted filesystem."""

    device: str
    """What is mounted: ``//nas/share``, ``nas:/export``, ``/dev/sda1``."""

    point: Path
    """Where it is mounted."""

    fstype: str
    """The filesystem type, lower case: ``cifs``, ``smbfs``, ``ext4``."""

    @property
    def is_network(self) -> bool:
        """Whether a server somewhere else holds what is mounted here."""
        return self.fstype in NETWORK_TYPES

    @property
    def is_optical(self) -> bool:
        """Whether it is a disc."""
        return self.fstype in OPTICAL_TYPES

    @property
    def host(self) -> str | None:
        """The server of a network mount, or ``None`` when it is not one or the device names none."""
        if not self.is_network:
            return None
        device = USER_PREFIX.sub("", self.device.removeprefix("//"))
        host = device.split("/", 1)[0] if self.device.startswith("//") else device.split(":", 1)[0]
        return host or None

    @property
    def port(self) -> int | None:
        """The port to ask whether the server is there, or ``None`` when this filesystem has none to ask."""
        return NETWORK_PORTS.get(self.fstype) if self.host is not None else None


def parse_proc_mounts(text: str) -> list[Mount]:
    """Read the lines of ``/proc/self/mounts``.

    :param text: the file's content.
    :returns: its mounts, in file order; a malformed line is skipped.
    """
    mounts: list[Mount] = []
    for line in text.splitlines():
        fields = line.split()
        if len(fields) < 3:
            continue
        device, point, fstype = (
            PROC_ESCAPE.sub(lambda match: chr(int(match.group(1), 8)), field) for field in fields[:3]
        )
        mounts.append(Mount(device, Path(point), fstype.lower()))
    return mounts


def parse_mount_command(text: str) -> list[Mount]:
    """Read the output of macOS's ``mount``.

    :param text: its output.
    :returns: the mounts, in output order; a line in another shape is skipped.
    """
    mounts: list[Mount] = []
    for line in text.splitlines():
        found = MOUNT_LINE.match(line)
        if found is None:
            continue
        fstype = found.group("options").split(",", 1)[0].strip().lower()
        mounts.append(Mount(found.group("device"), Path(found.group("point")), fstype))
    return mounts


def read_mounts() -> list[Mount]:
    """The machine's mounts now. Empty where there is no way to ask (and on Windows, which has no mount table).

    :returns: the mounts; empty when the table cannot be read.
    """
    try:
        if sys.platform == "linux":
            return parse_proc_mounts(PROC_MOUNTS.read_text(encoding="utf-8"))
        if sys.platform == "darwin":
            completed = subprocess.run(  # nosec B603  # a fixed absolute executable, no arguments, never a shell
                [MOUNT_COMMAND], check=True, capture_output=True, text=True, timeout=5
            )
            return parse_mount_command(completed.stdout)
    except OSError, subprocess.SubprocessError:
        pass
    return []
