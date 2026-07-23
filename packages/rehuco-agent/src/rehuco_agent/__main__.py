"""CLI entry point: ``rehuco-agent [--register|--unregister] [paths...]`` (register/unregister: Windows only)."""

import argparse
import ctypes
import sys
from pathlib import Path

from rehuco_agent.app import run
from rehuco_agent.main_window import ARCHIVE_EXTENSIONS


def main() -> int:
    """Register/unregister the Windows file association and context menus, or launch the GUI.

    ``--register``/``--unregister`` are Windows-only and not offered at all on other
    platforms: the argument parser only defines them when ``sys.platform == "win32"``, so
    ``rehuco-agent --register`` on macOS/Linux fails with argparse's own "unrecognized
    arguments" rather than a custom runtime message -- there is nothing for it to do there
    ([[packaging-deployment#app-identity]] is explicitly OS-specific; only the Windows half is built so far, issue #1).
    ``rehuco_agent.windows_registration`` (which owns rehuco's own identity constants and the
    register/unregister/is_registered orchestration, shared with the settings dialog's Registry
    page, #47) is imported lazily, only once inside that Windows-only branch: it imports
    ``borco_core.platforms.windows.*``, which do ``import winreg`` at module scope, so an
    unconditional top-level import here would break this entry point on every other platform. The
    folder/folder-background shell verbs and the archive-file shell verb (#43) both open the
    resource's own ``.rehu`` if it exists, or start a new one if it doesn't
    (``DocumentsDock.open_folder``/``DocumentsDock.open_archive``).

    Both flags register/unregister *this running exe* (``sys.argv[0]``), not a hardcoded
    guess -- so the same code path works whether invoked as the real packaged
    ``rehuco-agent.exe`` console-script entry point or as ``packages/rehuco-agent/launcher``'s
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
        from rehuco_agent import windows_registration

        if args.register or args.unregister:
            if not windows_registration.is_running_from_exe(exe_path):
                # sys.argv[0] is a .py source path, not an executable, when invoked via
                # `python -m rehuco_agent` (or running __main__.py directly) rather than
                # through a real console-script/exe entry point -- registering it would write
                # a shell\open\command Windows cannot meaningfully run and a DefaultIcon with
                # no icon resource to extract from, silently "succeeding" into a broken state
                print(
                    f"cannot register/unregister from {exe_path} -- not an .exe; run via the "
                    "rehuco-agent console script or the dev launcher "
                    "(packages/rehuco-agent/launcher), not `python -m rehuco_agent`",
                    file=sys.stderr,
                )
                return 1
            if args.register:
                windows_registration.register(exe_path, ARCHIVE_EXTENSIONS)
            else:
                windows_registration.unregister(ARCHIVE_EXTENSIONS)
            return 0

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(windows_registration.AUMID)

    return run([str(exe_path), *args.paths])


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
