"""What the storage under a path does to a reader that holds a handle open (#241).

**A declaration, not a platform branch scattered through every job.** Whether a reader has to let go of
its handle before a directory can be renamed is a property of the *storage*, not of the work: Windows
local storage says yes, POSIX says no, and a future backend that is not a filesystem at all -- a node's
REST API ([[architecture-design#components]]), a FUSE mount -- says no for a third reason again. Asking
here means a job never contains ``if sys.platform``, and means adding a backend is answering this
question rather than finding every place that assumed an answer.

**It gates the handle, never the barrier.** A reader always takes part in
:class:`~rehuco_core.RenameCoordinator`'s yield protocol, whatever this says; what a ``False`` here buys
is that the reader yields *without closing the file*, so the one protocol is exercised on every
platform and only the close is conditional.
"""

import sys
from pathlib import Path


def readers_must_yield_for_directory_rename(path: Path) -> bool:
    """Whether a reader under ``path`` must close its handle before a directory above it can be renamed.

    ``True`` on Windows: NTFS refuses to rename a directory while **any** handle is open anywhere
    beneath it, whatever share mode that handle was opened with -- it is a rule about the subtree, so
    :func:`~borco_core.shared_read_open`'s ``FILE_SHARE_DELETE`` (which does settle the file-scoped
    case) cannot buy it. ``False`` on POSIX, where a rename touches a directory entry and an open
    descriptor never notices.

    :param path: the file or directory being read; ignored today, and taken so that a backend which
        varies by location -- a share mounted from a node, a directory on a different filesystem -- can
        answer per-path rather than per-process without every caller changing.
    :returns: whether the reader has to let go.
    """
    del path  # see above: the parameter is the seam, not yet a discriminator
    return sys.platform == "win32"
