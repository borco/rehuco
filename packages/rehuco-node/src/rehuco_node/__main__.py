"""CLI entry point: ``rehuco-node [--version] [--settings-dir DIR]`` runs the local node until stopped (#506).

Stopped by SIGINT/SIGTERM, or by its stdin reaching EOF when a host that started it with a pipe goes away.
``rehuco-agent --node`` reaches this same :func:`main`, so a packaged agent needs no second executable to host
its node.
"""

import argparse
import sys
import threading
from collections.abc import Sequence
from pathlib import Path

from rehuco_core import AppFolders, app_folders

from . import __version__
from .local_node import LocalNode, install_signal_handlers, node_folder, setup_logging, watch_stdin


def folders_for(settings_dir: Path | None) -> AppFolders:
    """The folders this run uses: one folder when a settings dir is given, else the platform's.

    The same rule the agent applies to its ``--settings-dir`` (#494), so an agent and the node it starts with the
    same flag meet in the same folder.

    :param settings_dir: ``--settings-dir``, or ``None``.
    :returns: the folders.
    """
    return app_folders() if settings_dir is None else AppFolders.single(settings_dir.resolve())


def main(argv: Sequence[str] | None = None) -> int:
    """Run the node until stopped.

    :param argv: the arguments after the program name; the process's own when ``None``.
    :returns: the exit code.
    """
    parser = argparse.ArgumentParser(prog="rehuco-node")
    parser.add_argument("-v", "--version", action="store_true", help="print the node version and exit")
    parser.add_argument(
        "--settings-dir",
        metavar="DIR",
        type=Path,
        help="keep this run's files in DIR, as the agent started with the same flag does",
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else list(argv))
    if args.version:
        print(f"version: {__version__}")
        return 0

    folders = folders_for(args.settings_dir)
    handler = setup_logging(node_folder(folders))
    stop = threading.Event()
    install_signal_handlers(stop)
    if not sys.stdin.isatty():
        watch_stdin(stop)
    try:
        LocalNode(folders).run(stop)
    finally:
        handler.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
