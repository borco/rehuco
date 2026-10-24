"""Roots as this machine reaches them, for the tests that need a folder per root (#514).

A ``.rehuco`` holds a root's location and a machine's mapping holds its folder. A test that wants a folder per root
spells the location from the folder (:func:`location_at`) and reads it back (:func:`path_at`), so the pair needs no
mapping file and no mount table.
"""

from pathlib import Path, PurePath
from typing import Final

from rehuco_core import MappedRoot, RehucoFile

TEST_HOST: Final = "//test/"
"""The location prefix standing in for the share a test's folders are on."""


def location_at(path: Path | str) -> str:
    """The location a test gives the root at ``path``.

    :param path: the root's folder.
    :returns: its location, which :func:`path_at` turns back into the folder.
    """
    return TEST_HOST + PurePath(path).as_posix()


def path_at(location: str) -> Path:
    """The folder of a location :func:`location_at` spelled.

    :param location: a location made by :func:`location_at`.
    :returns: the folder.
    """
    return Path(location.removeprefix(TEST_HOST))


def mapped(file: RehucoFile) -> tuple[MappedRoot, ...]:
    """Every root of a catalog whose locations :func:`location_at` spelled, mapped to its folder.

    :param file: the catalog.
    :returns: its roots, in display order, each on the local storage.
    """
    return tuple(MappedRoot(root.root_id, root.label, root.location, path_at(root.location)) for root in file.roots)
