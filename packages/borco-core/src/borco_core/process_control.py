"""Showing and ending a process that holds a file -- what a person does once :func:`borco_core.file_holders`
has named it.

Naming a holder is half of what PowerToys File Locksmith offers; the other half is acting on it: bring the
program forward to close the file there, or end it. Windows only, as naming is: elsewhere nobody is ever
named, so there is never anything to show or end, and every answer is *no*.
"""

import sys


def has_window(pid: int) -> bool:
    """Whether the process has a window :func:`show_window` can bring to the front -- one the taskbar shows.

    :param pid: the process.
    :returns: whether it has one; ``False`` off Windows.
    """
    # sys.platform, not os.name, for the reason atomic_write spells out
    if sys.platform == "win32":
        # pylint: disable-next=import-outside-toplevel
        from .platforms.windows.process_control import has_window as windows_has_window

        return windows_has_window(pid)
    return False


def show_window(pid: int) -> bool:
    """Bring the process's topmost taskbar window to the front, restoring it if it is minimized.

    Call it from a click in this process: that input is what lets Windows hand over the foreground.

    :param pid: the process.
    :returns: whether it had a window and it came to the front; ``False`` off Windows.
    """
    # sys.platform, not os.name, for the reason atomic_write spells out
    if sys.platform == "win32":
        # pylint: disable-next=import-outside-toplevel
        from .platforms.windows.process_control import show_window as windows_show_window

        return windows_show_window(pid)
    return False


def end_process(pid: int, timeout: float) -> bool:
    """End the process without asking it -- whatever it had unsaved is lost -- and wait for it to go.

    Blocks for up to ``timeout``: call it off the GUI thread.

    :param pid: the process.
    :param timeout: how long to wait for it to exit, in seconds.
    :returns: whether it has gone, also when it had already exited; ``False`` off Windows.
    :raises OSError: the operating system refused to end it -- access denied for an elevated process.
    """
    # sys.platform, not os.name, for the reason atomic_write spells out
    if sys.platform == "win32":
        # pylint: disable-next=import-outside-toplevel
        from .platforms.windows.process_control import end_process as windows_end_process

        return windows_end_process(pid, timeout)
    return False
