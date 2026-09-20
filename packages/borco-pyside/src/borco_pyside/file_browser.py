"""Revealing a path in the OS's file browser, wrapped behind one call (#314).

Qt Creator's own ``showInGraphicalShell`` recipe: Explorer's ``/select`` switch on Windows, ``open -R``
on macOS, and a ``org.freedesktop.FileManager1`` D-Bus call on Linux -- falling back to ``xdg-open``
where no such service answers (a minimal desktop, or a file manager that predates the freedesktop
spec). A vanished file reveals its parent folder instead of asking any of these to select nothing; a
vanished parent gives up rather than walking further up looking for one that exists.
"""

import sys
from pathlib import Path

from PySide6.QtCore import QDir, QProcess, QUrl


class FileBrowser:  # pylint: disable=too-few-public-methods
    """Reveals a path in the system's file browser, one platform recipe per method."""

    def reveal(self, path: Path) -> bool:
        """Reveal ``path`` in the system's file browser: a file selected in its folder, a folder opened.

        :param path: the file (or folder) to reveal.
        :returns: whether a launch was attempted -- never raises for a missing tool.
        """
        if path.exists():
            # a folder is opened, not selected inside its parent: the Files sub-dock hands its browsed
            # folder here, and what the reader wants is that folder's contents, the same as for a file
            return self.__reveal(path, select=not path.is_dir())
        parent = path.parent
        if not parent.exists():
            return False
        return self.__reveal(parent, select=False)

    def __reveal(self, path: Path, *, select: bool) -> bool:
        """Dispatch to the current platform's recipe.

        :param path: the file or folder to reveal -- selected within its parent, or opened plainly.
        :param select: whether ``path`` is a file to select, as opposed to a folder to just open.
        :returns: whether a launch was attempted.
        """
        match sys.platform:
            case "win32":
                return self.__reveal_on_windows(path, select=select)
            case "darwin":
                return self.__reveal_on_macos(path, select=select)
            case _:
                return self.__reveal_on_linux(path, select=select)

    def __reveal_on_windows(self, path: Path, *, select: bool) -> bool:
        """Open ``path`` in Explorer, through its ``/select`` switch for a file.

        The comma stays glued to the switch and the path is a separate argument, so ``QProcess`` quotes
        a path with spaces on its own rather than the switch being quoted along with it.

        :param path: the file or folder to reveal.
        :param select: whether ``path`` is a file to select, as opposed to a folder to just open.
        :returns: whether a launch was attempted.
        """
        native = QDir.toNativeSeparators(str(path))
        if select:
            return self.__start_detached("explorer.exe", ["/select,", native])
        return self.__start_detached("explorer.exe", [native])

    def __reveal_on_macos(self, path: Path, *, select: bool) -> bool:
        """Open ``path`` in Finder, through ``open -R`` for a file.

        :param path: the file or folder to reveal.
        :param select: whether ``path`` is a file to select, as opposed to a folder to just open.
        :returns: whether a launch was attempted.
        """
        if select:
            return self.__start_detached("open", ["-R", str(path)])
        return self.__start_detached("open", [str(path)])

    def __reveal_on_linux(self, path: Path, *, select: bool) -> bool:
        """Ask the desktop's file manager to reveal ``path`` over D-Bus, falling back to ``xdg-open``.

        :param path: the file or folder to reveal.
        :param select: whether ``path`` is a file to select (``ShowItems``) or a folder to just open
            (``ShowFolders``).
        :returns: whether a launch was attempted.
        """
        # pylint: disable-next=import-outside-toplevel
        from PySide6.QtDBus import QDBusConnection, QDBusMessage

        message = QDBusMessage.createMethodCall(
            "org.freedesktop.FileManager1",
            "/org/freedesktop/FileManager1",
            "org.freedesktop.FileManager1",
            "ShowItems" if select else "ShowFolders",
        )
        message.setArguments([[QUrl.fromLocalFile(str(path)).toString()], ""])
        if QDBusConnection.sessionBus().send(message):
            return True
        # xdg-open on a file launches its handler, not a file manager -- the folder is the most it can do
        return self.__start_detached("xdg-open", [str(path.parent if select else path)])

    @staticmethod
    def __start_detached(program: str, arguments: list[str]) -> bool:
        """Launch ``program`` detached, reporting only success -- the pid Qt hands back alongside it is
        of no interest to a fire-and-forget reveal.

        :param program: the executable to launch.
        :param arguments: its command-line arguments.
        :returns: whether the launch succeeded.
        """
        started, _pid = QProcess.startDetached(program, arguments)
        return started


def reveal_in_file_browser(path: Path) -> bool:
    """Reveal ``path`` in the system's file browser: a file selected in its folder, a folder opened.

    :param path: the file (or folder) to reveal.
    :returns: whether a launch was attempted -- never raises for a missing tool.
    """
    return FileBrowser().reveal(path)
