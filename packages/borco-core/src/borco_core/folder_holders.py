"""Which processes have a folder, or anything under it, open -- the holders :func:`borco_core.file_holders` cannot see.

A folder is renamed only once nothing holds it or anything under it, and the holder most often in the way holds no
file there: a shell whose working directory it is, an Explorer window showing it. Windows answers that only by
walking every open handle on the system, as PowerToys File Locksmith does; elsewhere there is nothing to ask --
POSIX renames under open handles anyway -- so the answer is always empty there.
"""

import sys
from pathlib import Path

from .file_holder import FileHolder


def folder_holders(folder: Path) -> tuple[FileHolder, ...]:
    """The processes other than this one with a handle on ``folder`` or on anything under it, each once.

    Slow -- every handle on the system is looked at, a couple of seconds on a busy machine -- so off the GUI thread.

    :param folder: the folder.
    :returns: the holders, named by their executable (``bash.exe``); empty where there is no way to ask.
    :raises OSError: the operating system refused the question, or the folder could not be opened.
    """
    # sys.platform, not os.name, for the reason atomic_write spells out
    if sys.platform == "win32":
        # pylint: disable-next=import-outside-toplevel
        from .platforms.windows.folder_holders import folder_holders as windows_folder_holders

        return windows_folder_holders(folder)
    return ()
