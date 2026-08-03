"""Console logging setup, shared by console and GUI apps."""

import logging
from typing import Final

from colorama import Fore, Style

DEFAULT_CONSOLE_LEVEL: Final = logging.INFO
"""What the console prints unless told otherwise -- info and up, as it always has."""


def setup_console_logging(level: int = logging.DEBUG, console_level: int = DEFAULT_CONSOLE_LEVEL) -> None:
    """Configure the root logger to print to the console, colorized by level.

    **Two levels, deliberately.** ``level`` is the root logger's, and it is what every *other* handler
    is offered -- a record the root logger rejects reaches nothing at all, so a root at ``INFO`` would
    leave an in-app log surface with a debug filter that can never have anything to show. The console
    keeps its own, higher, ``console_level``, so lowering the root one does not turn a terminal into a
    firehose.

    **Call this first.** ``logging.basicConfig`` does nothing at all when the root logger already has a
    handler -- not even set the level -- so an app that attaches its own handler before calling this
    gets neither a console nor the floor it asked for.

    :param level: the root logger's minimum level -- the floor for every handler on it.
    :param console_level: the minimum level the console itself prints.
    """
    root = logging.getLogger()
    # only the handler basicConfig installs here gets the console level -- levelling every handler on
    # the root logger would silently raise the floor of any other one already attached, which for an
    # in-app log surface is precisely the records it exists to keep
    existing = set(root.handlers)
    logging.basicConfig(
        level=level,
        format=(
            f"{Fore.CYAN}{{levelname:>8s}}{Style.RESET_ALL} {{message}} "
            f"{Style.DIM}{{pathname}}:{{lineno}}{Style.RESET_ALL}"
        ),
        style="{",
    )
    for handler in root.handlers:
        if handler not in existing:
            handler.setLevel(console_level)
