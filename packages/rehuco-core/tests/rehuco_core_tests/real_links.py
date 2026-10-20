"""Real links on ``tmp_path``, for the tests a declared tree cannot prove -- what a walk does with a junction, a
symlink or a hardlink is what the operating system answers for one (#498).

Each helper makes the link the platform allows and skips the test where it cannot: a symlink on Windows needs a
privilege or developer mode, a junction exists only there, and a hardlink needs a filesystem that has them.
"""

import os
import sys
from pathlib import Path

from pytest import importorskip, skip


def junction(link: Path, target: Path) -> Path:
    """Make ``link`` a Windows junction to the directory ``target``, or skip where there are none or this filesystem
    will not hold one.

    :param link: the junction to create.
    :param target: the existing directory it points at.
    :returns: ``link``.
    """
    winapi = importorskip("_winapi")
    try:
        winapi.CreateJunction(str(target), str(link))
    except OSError as error:
        skip(f"junctions are not allowed here: {error}")
    return link


def symlink(link: Path, target: Path) -> Path:
    """Make ``link`` a symlink to ``target``, a file or a directory, or skip where this process may not.

    :param link: the symlink to create.
    :param target: what it points at.
    :returns: ``link``.
    """
    try:
        os.symlink(target, link, target_is_directory=target.is_dir())
    except OSError as error:
        skip(f"symlinks are not allowed here: {error}")
    return link


def directory_link(link: Path, target: Path) -> Path:
    """Make ``link`` the directory link a user would make here: a junction on Windows, a symlink elsewhere.

    :param link: the link to create.
    :param target: the existing directory it points at.
    :returns: ``link``.
    """
    return junction(link, target) if sys.platform == "win32" else symlink(link, target)


def hardlink(link: Path, target: Path) -> Path:
    """Make ``link`` a second name of the file ``target``, or skip where the filesystem has no hardlinks.

    :param link: the new name.
    :param target: the existing file.
    :returns: ``link``.
    """
    try:
        os.link(target, link)
    except OSError as error:
        skip(f"hardlinks are not allowed here: {error}")
    return link
