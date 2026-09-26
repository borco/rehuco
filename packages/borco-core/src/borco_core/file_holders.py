"""Which processes have a set of files open -- the question a refused rename or delete leaves behind.

An operating system that refuses to move a file says only *that* something has it open ("being used by
another process"), never *what*. Asking is what turns that into something a person can act on: close
that program, or wait for it. Windows answers through the Restart Manager, the same source Explorer's
own "file in use" dialog reads. Elsewhere there is nothing to ask -- POSIX renames under open handles
anyway -- so the answer is always empty there.
"""

import sys
from collections.abc import Sequence
from pathlib import Path

from .file_holder import FileHolder


def file_holders(paths: Sequence[Path]) -> tuple[FileHolder, ...]:
    """The processes that have any of ``paths`` open, each once.

    Files only: a directory's own handles (an Explorer window showing it, a process's working
    directory) are not reported, which is the Restart Manager's limit rather than this function's.

    :param paths: the files to ask about.
    :returns: the holders, in the order the operating system listed them; empty where there is no way
        to ask.
    :raises OSError: the operating system refused the question.
    """
    # sys.platform, not os.name, for the reason atomic_write spells out
    if sys.platform == "win32":
        # pylint: disable-next=import-outside-toplevel
        from .platforms.windows.file_holders import file_holders as windows_file_holders

        return windows_file_holders(paths)
    return ()
