"""CLI entry point: ``rehuco-agent [--version] [--info] [--register|--unregister] [--settings-dir DIR] [paths...]``
(register/unregister: Windows and Linux); ``rehuco-agent --scrape URL [--scrapers-folder DIR]
[--output PATH]`` and ``rehuco-agent --scrape-schema PATH`` run a scrape from the console, no GUI
([[acquisition-tooling#scraper-registry]]); ``rehuco-agent --node [--settings-dir DIR]`` runs the local node
(#506)."""

import argparse
import ctypes
import os
import sys
from pathlib import Path
from typing import Final

from rehuco_agent import __version__
from rehuco_agent.archives import ARCHIVE_EXTENSIONS

SETTINGS_DIR_ENVIRONMENT_VARIABLE: Final = "REHUCO_AGENT_SETTINGS_DIR"
"""Names a folder that replaces the platform's settings, data and cache locations for this run (#494); the
``--settings-dir`` flag wins over it."""

NODE_FLAG: Final = "--node"
"""Runs the local node (``rehuco_node``) in this process instead of the agent; every other argument is the
node's (#506)."""

REGISTRATION_PLATFORMS: Final = ("win32", "linux")
"""Platforms whose parser defines ``--register``/``--unregister``.

macOS is absent on purpose: there the association is the app bundle's own declaration, with no
per-user registration to write ([[packaging-deployment#app-identity]])."""


def print_registration_info(exe_path: Path) -> None:
    """Print whether this app is registered as the ``.rehu``/``.tc`` handler, and where.

    Read-only counterpart of ``--register``/``--unregister``, for ``--info``. Windows has no
    equivalent of Linux's "registered, but to a different path" state -- ``is_registered`` only
    answers "is *this* path the one registered", so that is what gets printed. Linux instead reads
    the installed desktop entry's own ``Exec=`` value (:func:`registration_linux.registered_command`)
    independent of ``exe_path`` -- the AppImage the user is running right now may not be the one
    installed, which is the ordinary case there rather than an edge one
    ([[packaging-deployment#linux-format]]).

    :param exe_path: same resolution ``--register``/``--unregister`` use.
    """
    if sys.platform == "win32":
        # pylint: disable-next=import-outside-toplevel
        from rehuco_agent import registration_windows

        if registration_windows.is_registered(exe_path, ARCHIVE_EXTENSIONS):
            print(f"registered: {exe_path}")
        else:
            print("not registered")
    elif sys.platform == "linux":
        # pylint: disable-next=import-outside-toplevel
        from rehuco_agent import registration_linux

        command = registration_linux.registered_command()
        if command is None:
            print("not registered")
        else:
            print(f"registered: {command}")
    else:
        print("registration is declared by the app bundle on macOS; there is no runtime state to query")


def resolve_settings_dir(flag: Path | None, environment: str | None) -> Path | None:
    """The folder this run keeps its settings, data and cache in (#494): the flag's, else the environment's.

    Made absolute here, against the launch directory, because the GUI leaves that directory before it first
    reads a setting (``leave_launch_directory``).

    :param flag: ``--settings-dir``, or ``None`` when absent.
    :param environment: :data:`SETTINGS_DIR_ENVIRONMENT_VARIABLE`'s value; ``None`` or empty when unset.
    :returns: the absolute folder, or ``None`` for the platform's locations.
    """
    if flag is not None:
        return flag.resolve()
    if environment:
        return Path(environment).resolve()
    return None


def apply_settings_dir(parser: argparse.ArgumentParser, flag: Path | None) -> None:
    """Put this run's settings, data and cache in the folder :func:`resolve_settings_dir` names, creating it.

    Runs before anything reads a setting -- the scrape CLI and the GUI both do.

    :param parser: reports a path that is not a folder, and exits.
    :param flag: ``--settings-dir``, or ``None`` when absent.
    """
    folder = resolve_settings_dir(flag, os.environ.get(SETTINGS_DIR_ENVIRONMENT_VARIABLE))
    if folder is None:
        return
    if folder.exists() and not folder.is_dir():
        parser.error(f"--settings-dir: {folder} is not a folder")
    folder.mkdir(parents=True, exist_ok=True)
    # imported only here: the module pulls in PySide6.QtCore, which a plain --register need not pay for
    # pylint: disable-next=import-outside-toplevel
    from rehuco_agent.settings.persistent_settings import set_settings_dir

    set_settings_dir(folder)


def print_settings_info() -> None:
    """Print where this run's settings file, durable state and cache folder are, for ``--info``."""
    # pylint: disable-next=import-outside-toplevel
    from rehuco_agent.settings.persistent_settings import APPLICATION_NAME, folders

    where = folders()
    print(f"settings: {where.settings / f'{APPLICATION_NAME}.ini'}")
    print(f"data: {where.data}")
    print(f"cache: {where.cache}")


def run_node(arguments: list[str]) -> int:
    """Run the local node's own ``main`` in this process instead of the agent (#506).

    The packaged exe, the dev launcher and the console script all host the node as themselves this way, with no
    second executable to ship. Decided before the agent's parser sees anything, since none of its flags apply.

    :param arguments: the process's arguments after the program name, :data:`NODE_FLAG` included.
    :returns: the node's exit code.
    """
    # pylint: disable-next=import-outside-toplevel
    from rehuco_node.__main__ import main as node_main

    return node_main([argument for argument in arguments if argument != NODE_FLAG])


# pylint: disable-next=too-many-return-statements,too-many-branches,too-many-statements
def main() -> int:
    """Print version/registration info, register/unregister this app as the ``.rehu`` handler, or
    launch the GUI.

    ``--version`` and ``--info`` (:func:`print_registration_info`) are plain flags rather than
    argparse's own ``action="version"`` specifically so they combine with each other and with
    ``--register``/``--unregister`` on one command line -- ``rehuco-agent --info --register`` prints
    the state *before* registering, then registers. Any of the four present at all means this call
    is a CLI query/action, not a GUI launch: each returns before ``run()`` at the bottom, on every OS.

    ``--register``/``--unregister`` are defined only on the platforms that have something to
    register (:data:`REGISTRATION_PLATFORMS`), so ``rehuco-agent --register`` on macOS fails with
    argparse's own "unrecognized arguments" rather than a custom runtime message. Each platform's
    flags drive its own module -- ``rehuco_agent.registration_windows`` (HKCU file association plus
    the folder/archive shell verbs, #43) or ``rehuco_agent.registration_linux`` (the XDG desktop
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
    ``registration_linux.executable_path``). Both also refuse to run when that path isn't something
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
    if NODE_FLAG in sys.argv[1:]:
        return run_node(sys.argv[1:])

    exe_path = Path(sys.argv[0]).resolve()

    parser = argparse.ArgumentParser(prog="rehuco-agent")
    # Plain store_true flags, not argparse's own `action="version"` -- that action prints and calls
    # sys.exit() from inside parse_args() itself, which would make `--info --version --register` stop
    # after printing the version and never reach --register. Combinable with each other and with
    # --register/--unregister on one command line; on their own they still print-and-exit rather than
    # falling through to a GUI launch (below). This is also the release workflow's per-platform smoke
    # check for each packaged artifact ([[appendices.continuous-integration#release-agent]]) -- on Windows
    # an exit-code check only, since a packaged GUI-subsystem build prints nowhere at all
    # ([[appendices.release-runbook#windows-console]]).
    parser.add_argument("-v", "--version", action="store_true", help="print the app version")
    parser.add_argument(
        "-i",
        "--info",
        action="store_true",
        help="print whether this app is registered as the .rehu/.tc handler, and where",
    )
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
    scrape_group = parser.add_mutually_exclusive_group()
    scrape_group.add_argument("--scrape", metavar="URL", help="scrape URL and print the result as JSON")
    parser.add_argument(
        "--scrapers-folder",
        metavar="DIR",
        type=Path,
        help="build the scraper registry over DIR for this --scrape call only, ignoring the saved Scrapers setting",
    )
    parser.add_argument("--output", metavar="PATH", type=Path, help="write --scrape's JSON to PATH instead of stdout")
    scrape_group.add_argument(
        "--scrape-schema", metavar="PATH", type=Path, help="write the scrape-result JSON schema to PATH and exit"
    )
    parser.add_argument(
        "--settings-dir",
        metavar="DIR",
        type=Path,
        help=f"keep this run's settings, data and cache in DIR, with its own running instance (default: "
        f"${SETTINGS_DIR_ENVIRONMENT_VARIABLE}, else the platform's locations)",
    )
    args = parser.parse_args()
    if args.scrape is None and (args.scrapers_folder is not None or args.output is not None):
        parser.error("--scrapers-folder and --output only apply with --scrape")
    apply_settings_dir(parser, args.settings_dir)

    # Checked first and returns immediately: neither combines with --version/--info/--register/
    # --unregister, and both need none of the platform machinery below. Imported here, not at module
    # scope, for the same reason `rehuco_agent.app` is imported lazily further down -- a plain
    # register/unregister or GUI launch pays nothing for `fastjsonschema` or the scraping package.
    # pylint: disable-next=import-outside-toplevel
    from rehuco_agent.scraping import cli as scraping_cli  # noqa: PLC0415

    if args.scrape_schema is not None:
        return scraping_cli.write_scrape_schema(args.scrape_schema)
    if args.scrape is not None:
        return scraping_cli.scrape_url_to_json(args.scrape, scrapers_folder=args.scrapers_folder, output=args.output)

    # Printed before any --register/--unregister action below, so --info reports the *previous*
    # state -- matching how `rehuco-agent --info --register` reads left to right.
    if args.version:
        print(f"version: {__version__}")
    if args.info:
        print_registration_info(exe_path)
        print_settings_info()
    queried = args.version or args.info

    # args.register/args.unregister don't exist at all off REGISTRATION_PLATFORMS (the parser never
    # defined them above), so every reference to them nests under one of the platform checks below.
    if sys.platform == "win32":
        # pylint: disable-next=import-outside-toplevel
        from rehuco_agent import registration_windows

        if args.register or args.unregister:
            if not registration_windows.is_running_from_exe(exe_path):
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
                registration_windows.register(exe_path, ARCHIVE_EXTENSIONS)
            else:
                registration_windows.unregister(ARCHIVE_EXTENSIONS)
            return 0

        if not queried:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(registration_windows.AUMID)

    # A separate `if`, not an `elif`: with the win32 block above excluded from coverage off Windows,
    # an elif chain would take this branch out of the report along with it.
    if sys.platform == "linux" and (args.register or args.unregister):
        # pylint: disable-next=import-outside-toplevel
        from borco_pyside.logging import setup_console_logging

        # pylint: disable-next=import-outside-toplevel
        from rehuco_agent import registration_linux

        setup_console_logging()  # so register()/unregister()'s own LOG.info reaches the console
        if args.unregister:
            blocker = registration_linux.unregistration_blocker()
            if blocker is not None:
                print(blocker, file=sys.stderr)
                return 1
            registration_linux.unregister()
        else:
            # not exe_path: inside an AppImage the launched file is $APPIMAGE, and sys.argv[0]
            # points into a temporary mount that is gone by the time anyone double-clicks the entry
            target = registration_linux.executable_path()
            blocker = registration_linux.registration_blocker(target)
            if blocker is not None:
                print(blocker, file=sys.stderr)
                return 1
            registration_linux.register(target)
        return 0

    if queried:
        return 0

    # Imported here, not at module scope: rehuco_agent.app pulls in PySide6, QtAds, borco_pyside and
    # the compiled Qt resources, which costs ~1s of process startup. The --register/--unregister
    # branches above return before this point and need none of it (Linux's icon read reaches
    # PySide6.QtCore/QtGui for the qrc, but never the dock shell) -- and on Windows it is what the
    # installer runs from a post-install script, where that second is a console window the user
    # watches ([[appendices.briefcase-packaging#windows]]).
    # pylint: disable-next=import-outside-toplevel
    from rehuco_agent.app import run

    # pylint: disable-next=import-outside-toplevel
    from rehuco_agent.run_log import shared_run_log

    try:
        return run([str(exe_path), *args.paths])
    except Exception as error:
        # ``run()`` itself already logs and re-raises an exception from ``app.exec()`` -- this instead
        # covers one from anywhere else inside ``run()`` (before ``app.exec()``, or its own ``finally``),
        # which would otherwise reach here having never been logged at all
        shared_run_log().log_exception(error, "main()")
        raise


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
