"""CLI entry point: ``rehuco-agent [--register|--unregister] [paths...]`` (register/unregister: Windows only)."""

import argparse
import ctypes
import sys
from pathlib import Path
from typing import Final

from rehuco_agent.app import run
from rehuco_agent.main_window import ARCHIVE_EXTENSIONS

PROGID: Final = "Rehuco.Document"
"""HKCU ProgID under ``Software\\Classes`` that owns the ``.rehu`` association."""

EXTENSION: Final = "rehu"
"""File extension (without the leading dot) registered to :data:`PROGID`."""

AUMID: Final = "borco.rehuco.agent"
"""Application User Model ID the running process declares via ``SetCurrentProcessExplicitAppUserModelID``."""

FRIENDLY_NAME: Final = "Rehuco Resource"
"""Human-readable type name shown in Explorer's Type column."""

DIRECTORY_SUB_KEY: Final = "Rehuco.OpenFolder"
"""HKCU sub-key under both ``Directory\\shell`` and ``Directory\\Background\\shell`` (#43)."""

DIRECTORY_MENU_TEXT: Final = "Open with Rehuco"
"""Menu label shown for both the folder and folder-background shell verbs."""

ARCHIVE_SUB_KEY: Final = "Rehuco.AddInfo"
"""HKCU sub-key under each of :data:`~rehuco_agent.main_window.ARCHIVE_EXTENSIONS`' own
``SystemFileAssociations\\<ext>\\shell`` (#43)."""

ARCHIVE_MENU_TEXT: Final = "Create or Open Rehuco Info"
"""Menu label shown for the archive-file shell verb -- static (not per-file, see #43's discussion of
why a dynamic "Open foo.rehu"/"Create foo.rehu" label would need a full COM shell extension)."""


def main() -> int:
    """Register/unregister the Windows file association and context menus, or launch the GUI.

    ``--register``/``--unregister`` are Windows-only and not offered at all on other
    platforms: the argument parser only defines them when ``sys.platform == "win32"``, so
    ``rehuco-agent --register`` on macOS/Linux fails with argparse's own "unrecognized
    arguments" rather than a custom runtime message -- there is nothing for it to do there
    ([[packaging-deployment#app-identity]] is explicitly OS-specific; only the Windows half is built so far, issue #1).
    ``borco_core.platforms.windows.file_association``/``directory_context_menu``/
    ``file_extension_context_menu`` are imported lazily, only once inside that Windows-only branch:
    they do ``import winreg`` at module scope, which does not exist elsewhere, so an unconditional
    top-level import here would break this entry point on every other platform. All three modules
    are generic (progid/sub-key/command/icon all passed in); this module owns rehuco's own identity
    constants above. The folder/folder-background shell verbs and the archive-file shell verb (#43)
    both open the resource's own ``.rehu`` if it exists, or start a new one if it doesn't
    (``DocumentsDock.open_folder``/``DocumentsDock.open_archive``).

    Both flags register/unregister *this running exe* (``sys.argv[0]``), not a hardcoded
    guess -- so the same code path works whether invoked as the real packaged
    ``rehuco-agent.exe`` console-script entry point or as ``apps/rehuco-agent/launcher``'s
    dev-only trampoline exe (which forwards argv here in-process, see launcher.c). Both also
    refuse to run if ``sys.argv[0]`` isn't a real ``.exe`` -- invoking via
    ``python -m rehuco_agent`` makes argv[0] the ``__main__.py`` source path, and while
    ``unregister`` doesn't actually need the exe path, treating both flags identically avoids
    a confusing "register refuses this but unregister silently accepts it" asymmetry.

    AUMID is set as the very first statement in the GUI-launch branch, before any
    ``QApplication`` or window exists -- Windows binds it to the process's first top-level HWND
    at creation time, so setting it later has no effect (carried from the file-association
    spike, issue #1).

    :returns: process exit code.
    """
    exe_path = Path(sys.argv[0]).resolve()

    parser = argparse.ArgumentParser(prog="rehuco-agent")
    if sys.platform == "win32":
        group = parser.add_mutually_exclusive_group()
        group.add_argument(
            "--register",
            action="store_true",
            help="register the .rehu file association and folder/archive context menus",
        )
        group.add_argument(
            "--unregister",
            action="store_true",
            help="remove the .rehu file association and folder/archive context menus",
        )
    parser.add_argument("paths", nargs="*", help=".rehu files, resource directories, or archives to open")
    args = parser.parse_args()

    # args.register/args.unregister don't exist at all on non-Windows (the parser never
    # defined them above), so all Windows-only behavior nests under one platform check.
    if sys.platform == "win32":
        # pylint: disable-next=import-outside-toplevel
        from borco_core.platforms.windows.directory_context_menu import DirectoryContextMenu

        # pylint: disable-next=import-outside-toplevel
        from borco_core.platforms.windows.file_association import FileAssociation

        # pylint: disable-next=import-outside-toplevel
        from borco_core.platforms.windows.file_extension_context_menu import FileExtensionContextMenu

        if args.register or args.unregister:
            if exe_path.suffix.lower() != ".exe":
                # sys.argv[0] is a .py source path, not an executable, when invoked via
                # `python -m rehuco_agent` (or running __main__.py directly) rather than
                # through a real console-script/exe entry point -- registering it would write
                # a shell\open\command Windows cannot meaningfully run and a DefaultIcon with
                # no icon resource to extract from, silently "succeeding" into a broken state
                print(
                    f"cannot register/unregister from {exe_path} -- not an .exe; run via the "
                    "rehuco-agent console script or the dev launcher "
                    "(apps/rehuco-agent/launcher), not `python -m rehuco_agent`",
                    file=sys.stderr,
                )
                return 1
            # no separate ico_path: falls back to the running exe's own icon (DefaultIcon
            # `{exe_path},0`) -- correct either way, since the dev trampoline embeds this
            # same icon in its own PE resources (launcher.rc.in) and the real packaged exe
            # has no icon to fall back to regardless ([[packaging-deployment#app-identity]],
            # deferred distribution polish)
            icon = f"{exe_path},0"
            if args.register:
                FileAssociation.register(PROGID, EXTENSION, FRIENDLY_NAME, f'"{exe_path}" "%1"', icon, AUMID)
                DirectoryContextMenu.register_folder(DIRECTORY_SUB_KEY, DIRECTORY_MENU_TEXT, f'"{exe_path}"', icon)
                DirectoryContextMenu.register_background(DIRECTORY_SUB_KEY, DIRECTORY_MENU_TEXT, f'"{exe_path}"', icon)
                FileExtensionContextMenu.register(
                    ARCHIVE_EXTENSIONS, ARCHIVE_SUB_KEY, ARCHIVE_MENU_TEXT, f'"{exe_path}"', icon
                )
            else:
                FileAssociation.unregister(PROGID, EXTENSION)
                DirectoryContextMenu.unregister_folder(DIRECTORY_SUB_KEY)
                DirectoryContextMenu.unregister_background(DIRECTORY_SUB_KEY)
                FileExtensionContextMenu.unregister(ARCHIVE_EXTENSIONS, ARCHIVE_SUB_KEY)
            return 0

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(AUMID)

    return run([str(exe_path), *args.paths])


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
