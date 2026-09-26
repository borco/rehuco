"""One process holding a file open -- what :func:`borco_core.file_holders` answers with.

A module of its own so that the platform-neutral entry point and the Windows query behind it can both
name the type without importing each other.
"""

from typing import NamedTuple


class FileHolder(NamedTuple):
    """One process that has at least one of the asked-about files open.

    :param pid: its process id -- compare with :func:`os.getpid` to tell this process apart.
    :param name: its display name, as the operating system reports it (e.g. ``Windows Explorer``).
    """

    pid: int
    name: str
