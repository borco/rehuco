"""CLI entry point: ``rehuco-agent [--register|--unregister] [.rehu paths...]`` (register/unregister: Windows only)."""

import argparse
import ctypes
import sys
from pathlib import Path

from rehuco_agent.app import run


def main() -> int:
    """Register/unregister the Windows file association, or launch the GUI.

    ``--register``/``--unregister`` are Windows-only and not offered at all on other
    platforms: the argument parser only defines them when ``sys.platform == "win32"``, so
    ``rehuco-agent --register`` on macOS/Linux fails with argparse's own "unrecognized
    arguments" rather than a custom runtime message -- there is nothing for it to do there
    (§16.8 is explicitly OS-specific; only the Windows half is built so far, issue #1).
    ``rehuco_agent.platforms.windows.win_registration`` is imported lazily, only once inside that Windows-only
    branch: it does ``import winreg`` at module scope, which does not exist elsewhere, so an
    unconditional top-level import here would break this entry point on every other platform.

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
        group.add_argument("--register", action="store_true", help="register the .rehu file association")
        group.add_argument("--unregister", action="store_true", help="remove the .rehu file association")
    parser.add_argument("paths", nargs="*", help=".rehu files to open")
    args = parser.parse_args()

    # args.register/args.unregister don't exist at all on non-Windows (the parser never
    # defined them above), so all Windows-only behavior nests under one platform check.
    if sys.platform == "win32":
        from rehuco_agent.platforms.windows import win_registration  # pylint: disable=import-outside-toplevel

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
            if args.register:
                # no separate ico_path: falls back to the running exe's own icon (§DefaultIcon
                # `{exe_path},0`) -- correct either way, since the dev trampoline embeds this
                # same icon in its own PE resources (launcher.rc.in) and the real packaged exe
                # has no icon to fall back to regardless (§16.8, deferred distribution polish)
                win_registration.register(exe_path)
            else:
                win_registration.unregister()
            return 0

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(win_registration.AUMID)

    return run([str(exe_path), *args.paths])


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
