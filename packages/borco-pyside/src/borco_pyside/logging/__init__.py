"""Console logging setup, shared by console and GUI apps."""

import logging

from colorama import Fore, Style

__all__ = ["setup_console_logging"]


def setup_console_logging(level: int = logging.INFO) -> None:
    """Configure the root logger to print to the console, colorized by level.

    :param level: the root logger's minimum level.
    """
    logging.basicConfig(
        level=level,
        format=(
            f"{Fore.CYAN}{{levelname:>8s}}{Style.RESET_ALL} {{message}} "
            f"{Style.DIM}{{pathname}}:{{lineno}}{Style.RESET_ALL}"
        ),
        style="{",
    )
