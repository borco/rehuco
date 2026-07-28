"""CLI entry point: ``rehuco-agent [--register|--unregister] [paths...]`` (register/unregister: Windows and Linux)."""

import argparse
import ctypes
import sys
from pathlib import Path
from typing import Final

from rehuco_agent.archives import ARCHIVE_EXTENSIONS

REGISTRATION_PLATFORMS: Final = ("win32", "linux")
"""Platforms whose parser defines ``--register``/``--unregister``.

macOS is absent on purpose: there the association is the app bundle's own declaration, with no
per-user registration to write ([[packaging-deployment#app-identity]])."""


def main() -> int:
    """Register/unregister this app as the ``.rehu`` handler, or launch the GUI.

    ``--register``/``--unregister`` are defined only on the platforms that have something to
    register (:data:`REGISTRATION_PLATFORMS`), so ``rehuco-agent --register`` on macOS fails with
    argparse's own "unrecognized arguments" rather than a custom runtime message. Each platform's
    flags drive its own module -- ``rehuco_agent.windows_registration`` (HKCU file association plus
    the folder/archive shell verbs, #43) or ``rehuco_agent.linux_registration`` (the XDG desktop
    entry, MIME package and icon, #209) -- and both are the same modules the settings dialog's
    System Integration page uses, so the CLI and the GUI can never drift apart.

    The Windows module is imported lazily, only inside its own platform branch: it imports
    ``borco_core.platforms.windows.*``, which do ``import winreg`` at module scope, so an
    unconditional top-level import would break this entry point everywhere else. The Linux module
    needs no such gate (it is ``pathlib``/``subprocess`` underneath), but is imported the same way
    so that a plain GUI launch never pays for it.

    Both flags act on *this running executable*, not a hardcoded guess -- so the same code path
    works whether invoked as the real packaged ``rehuco-agent.exe`` console-script entry point, as
    ``packages/rehuco-agent/launcher``'s dev-only trampoline exe (which forwards argv here
    in-process, see launcher.c), as the ``uv tool install`` shim, or from inside an AppImage (where
    the path comes from ``$APPIMAGE`` rather than ``sys.argv[0]``, see
    ``linux_registration.executable_path``). Both also refuse to run when that path isn't something
    the OS could launch -- ``python -m rehuco_agent`` makes argv[0] the ``__main__.py`` source path
    -- and while ``unregister`` doesn't actually need the path, treating both flags identically
    avoids a confusing "register refuses this but unregister silently accepts it" asymmetry.

    AUMID is set as the very first statement in the GUI-launch branch, before any
    ``QApplication`` or window exists -- Windows binds it to the process's first top-level HWND
    at creation time, so setting it later has no effect (carried from the file-association
    spike, issue #1). Its Linux counterpart, the desktop file name, is set in
    ``rehuco_agent.app.run`` instead: unlike the AUMID it is a plain Qt call with no ``ctypes``
    behind it, so it belongs beside the ``QApplication`` it names.

    :returns: process exit code.
    """
    exe_path = Path(sys.argv[0]).resolve()

    parser = argparse.ArgumentParser(prog="rehuco-agent")
    if sys.platform in REGISTRATION_PLATFORMS:
        group = parser.add_mutually_exclusive_group()
        group.add_argument(
            "--register",
            action="store_true",
            help="register this app as the .rehu/.tc handler (Windows: plus the folder/archive context menus)",
        )
        group.add_argument(
            "--unregister",
            action="store_true",
            help="remove this app's .rehu/.tc handler registration (Windows: plus the context menus)",
        )
    parser.add_argument("paths", nargs="*", help=".rehu files, resource directories, or archives to open")
    args = parser.parse_args()

    # args.register/args.unregister don't exist at all off REGISTRATION_PLATFORMS (the parser never
    # defined them above), so every reference to them nests under one of the platform checks below.
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

    # A separate `if`, not an `elif`: with the win32 block above excluded from coverage off Windows,
    # an elif chain would take this branch out of the report along with it.
    if sys.platform == "linux" and (args.register or args.unregister):
        # pylint: disable-next=import-outside-toplevel
        from borco_pyside.logging import setup_console_logging

        # pylint: disable-next=import-outside-toplevel
        from rehuco_agent import linux_registration

        setup_console_logging()  # so register()/unregister()'s own LOG.info reaches the console
        if args.unregister:
            blocker = linux_registration.unregistration_blocker()
            if blocker is not None:
                print(blocker, file=sys.stderr)
                return 1
            linux_registration.unregister()
        else:
            # not exe_path: inside an AppImage the launched file is $APPIMAGE, and sys.argv[0]
            # points into a temporary mount that is gone by the time anyone double-clicks the entry
            target = linux_registration.executable_path()
            blocker = linux_registration.registration_blocker(target)
            if blocker is not None:
                print(blocker, file=sys.stderr)
                return 1
            linux_registration.register(target)
        return 0

    # Imported here, not at module scope: rehuco_agent.app pulls in PySide6, QtAds, borco_pyside and
    # the compiled Qt resources, which costs ~1s of process startup. The --register/--unregister
    # branches above return before this point and need none of it (Linux's icon read reaches
    # PySide6.QtCore/QtGui for the qrc, but never the dock shell) -- and on Windows it is what the
    # installer runs from a post-install script, where that second is a console window the user
    # watches ([[appendices.briefcase-packaging#windows]]).
    # pylint: disable-next=import-outside-toplevel
    from rehuco_agent.app import run

    return run([str(exe_path), *args.paths])


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
