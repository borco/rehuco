"""Opening a file for reading without locking it against a rename or a delete.

The counterpart of :mod:`borco_core.atomic_write`, and the same kind of thing: a one-function answer
to a filesystem detail that is invisible until it bites. A background job reading a file must not be
the reason someone else cannot move it, and on Windows a plain ``open`` is exactly that reason --
its share mode withholds ``FILE_SHARE_DELETE``, and a rename needs it.

Everywhere else this is ``path.open("rb")`` unchanged, because POSIX has nothing to withhold: a rename
there is an operation on a directory entry, and an open descriptor keeps reading the file it was
opened on whatever the entry is called afterwards.
"""

import sys
from io import BufferedReader
from pathlib import Path


def shared_read_open(path: Path | str) -> BufferedReader:
    """Open ``path`` for binary reading, denying nobody the right to rename or delete it.

    :param path: the file to open.
    :returns: the open file, positioned at the start -- an ordinary buffered reader either way, so
        nothing downstream branches on the platform.
    :raises OSError: the file could not be opened, with the same exception ``open`` would have raised.
    """
    # sys.platform, not os.name, for the reason atomic_write spells out: pathlib bakes os.name in at
    # interpreter start, so mocking it in a test breaks the very Path calls below.
    if sys.platform == "win32":
        # pylint: disable-next=import-outside-toplevel
        from .platforms.windows.shared_read import shared_read_open as windows_shared_read_open

        return windows_shared_read_open(path)
    return Path(path).open("rb")
