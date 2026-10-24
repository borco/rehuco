"""A root's machine-independent **location**, and how each machine finds it ([[mounts-and-storage#rehuco-scope]], #514).

A location is the same on every box: for a share, the server and share path (``//nas/data/Tutorials``), read from
this machine's mount table; for a folder on one machine's own disk, that machine's name and path
(``//ryzen-5600/d/Downloads/FOO`` on Windows, ``//ryzen-5600/home/me/FOO`` elsewhere). The host is lower-cased, so two
machines that spell a server differently in case agree; a server spelled by name on one machine and by address on
another is two locations.

Everything here answers from local state -- the drive table, the mount table -- and never asks the network, so none of
it can wait on a dead share ([[mounts-and-storage#offline-mounts]]).
"""

import socket
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from borco_core.path_presence import StorageKind, device_of
from borco_core.platforms.linux.mount_table import USER_PREFIX, Mount, read_mounts

from .rehuco_file import RootStorage

LOCATION_PREFIX: Final = "//"
"""What every location starts with: the host follows."""

STORAGE_OF_KIND: Final = {
    StorageKind.LOCAL: RootStorage.LOCAL,
    StorageKind.NETWORK: RootStorage.NETWORK,
    StorageKind.REMOVABLE: RootStorage.REMOVABLE,
    StorageKind.OPTICAL: RootStorage.COMPACT_DISK,
}
"""The detector's kinds, spelled as the storage a mapping records."""


def machine_name() -> str:
    """This machine's name as a location spells it: the host's first label, lower-cased.

    :returns: for example ``ryzen-5600``.
    """
    return socket.gethostname().split(".", 1)[0].casefold()


def storage_of(path: Path, mounts: Sequence[Mount] | None = None) -> RootStorage:
    """What ``path`` lives on, detected from this machine's drive or mount table.

    :param path: an absolute path; it need not exist.
    :param mounts: the mount table, for a caller classifying many paths (POSIX only); ``None`` reads it.
    :returns: the storage.
    """
    return STORAGE_OF_KIND[device_of(path, mounts).kind]


def share_location(share: str) -> str:
    """A Windows ``\\\\host\\share`` spelled as a location's share part.

    :param share: a UNC share, with or without a trailing separator.
    :returns: ``//host/share`` with the host lower-cased.
    """
    host, _, name = share.strip("\\").partition("\\")
    return f"{LOCATION_PREFIX}{host.casefold()}/{name.replace(chr(92), '/')}".rstrip("/")


def mount_share(mount: Mount) -> str | None:
    """The ``//host/share`` a network mount serves, as a location spells it.

    :param mount: a mount.
    :returns: for ``//user@nas/share`` and ``nas:/share`` alike ``//nas/share``; ``None`` for a mount that is not a
        network one or names no server.
    """
    host = mount.host
    if host is None:
        return None
    if mount.device.startswith(LOCATION_PREFIX):
        pieces = USER_PREFIX.sub("", mount.device.removeprefix(LOCATION_PREFIX)).split("/", 1)
        tail = pieces[1] if len(pieces) > 1 else ""
    else:
        tail = mount.device.partition(":")[2]
    return f"{LOCATION_PREFIX}{host.casefold()}/{tail.strip('/')}".rstrip("/")


def location_of(path: Path, mounts: Sequence[Mount] | None = None) -> str:
    """The machine-independent location of ``path``, from this machine's drive or mount table.

    :param path: an absolute path; it need not exist.
    :param mounts: the mount table, for a caller locating many paths (POSIX only); ``None`` reads it.
    :returns: ``//host/share/rest`` for a path on a share this machine has mounted; ``//<machine>/<d>/rest`` (Windows)
        or ``//<machine>/rest`` (elsewhere) for a path on its own disks.
    :raises ValueError: the path is not absolute.
    """
    if not path.is_absolute():
        raise ValueError(f"A location needs an absolute path: {path}")
    if sys.platform == "win32":
        return windows_location(path)
    table = read_mounts() if mounts is None else mounts
    holding = [mount for mount in table if mount.is_network and path.is_relative_to(mount.point)]
    best = max(holding, key=lambda mount: len(mount.point.parts), default=None)
    share = None if best is None else mount_share(best)
    if best is None or share is None:
        return "/".join([f"{LOCATION_PREFIX}{machine_name()}", *path.parts[1:]])
    return "/".join([share, *path.relative_to(best.point).parts])


def resolve_location(location: str, mounts: Sequence[Mount] | None = None) -> Path | None:
    """Where this machine finds ``location``, if it can without being told.

    :param location: a root's location.
    :param mounts: the mount table (POSIX only); ``None`` reads it.
    :returns: the folder -- a local one when the location names this machine, else one under a share this machine
        has mounted (a mapped drive letter on Windows); ``None`` when it reaches neither.
    """
    if not location.startswith(LOCATION_PREFIX):
        return None
    host, _, rest = location.removeprefix(LOCATION_PREFIX).partition("/")
    parts = [part for part in rest.split("/") if part]
    if host.casefold() == machine_name():
        return own_folder(parts)
    if sys.platform == "win32":
        return windows_share_folder(host, parts)
    folded = location.rstrip("/").casefold()
    found: Path | None = None
    longest = 0
    for mount in read_mounts() if mounts is None else mounts:
        share = mount_share(mount)
        if share is None or not (folded == share.casefold() or folded.startswith(f"{share.casefold()}/")):
            continue
        if len(share) > longest:
            longest = len(share)
            found = mount.point.joinpath(*location[len(share) :].strip("/").split("/"))
    return found


def windows_location(path: Path) -> str:  # win32-only
    """The location of an absolute Windows path: through its UNC share or mapped drive letter, else this machine's.

    :param path: an absolute path.
    :returns: its location.
    """
    # pylint: disable-next=import-outside-toplevel
    from borco_core.platforms.windows import drives

    share = None
    if path.anchor.startswith("\\\\"):
        share = path.drive
    elif device_of(path).kind is StorageKind.NETWORK:
        share = drives.mapped_share(path.drive)
    if share is not None:
        return "/".join([share_location(share), *path.parts[1:]])
    return "/".join([f"{LOCATION_PREFIX}{machine_name()}", path.drive.rstrip(":").casefold(), *path.parts[1:]])


def own_folder(parts: list[str]) -> Path | None:
    """The folder on this machine's own disks a location's path part names.

    :param parts: the location's segments after the host (``["d", "Downloads"]`` on Windows).
    :returns: the folder; ``None`` on Windows when the first segment is no drive letter.
    """
    if sys.platform == "win32":
        if not parts or len(parts[0]) != 1:
            return None
        return Path(f"{parts[0].upper()}:\\").joinpath(*parts[1:])
    return Path("/").joinpath(*parts)


def windows_share_folder(host: str, parts: list[str]) -> Path | None:  # win32-only
    """The folder under the drive letter this machine mapped to a location's share.

    :param host: the location's host.
    :param parts: the location's segments after the host: the share, then the path inside it.
    :returns: the folder; ``None`` when no mapped drive is that share.
    """
    # pylint: disable-next=import-outside-toplevel
    from borco_core.platforms.windows import drives

    if not parts:
        return None
    wanted = f"{LOCATION_PREFIX}{host.casefold()}/{parts[0]}".casefold()
    for letter, share in drives.mapped_drives().items():
        if share_location(share).casefold() == wanted:
            return Path(f"{letter}\\").joinpath(*parts[1:])
    return None
