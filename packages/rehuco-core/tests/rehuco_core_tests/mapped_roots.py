"""Roots as this machine reaches them, for the tests that need a folder per root (#514).

A ``.rehuco`` holds a root's location and a machine's mapping holds its folder. A test that wants a folder per root
spells the location from the folder (:func:`location_at`) and reads it back (:func:`path_at`), so the pair needs no
mapping file and no mount table.
"""

from pathlib import Path, PurePath
from typing import Final
from uuid import uuid4

from rehuco_core import CURRENT_REHUCO_VERSION, MappedRoot, RehucoFile

TEST_HOST: Final = "//test/"
"""The location prefix standing in for the share a test's folders are on."""

UNSAVED_REHUCO: Final = Path("/unsaved/home.rehuco")
"""Where :func:`new_catalog` says its file is: a folder that does not exist, never written."""


def new_catalog() -> RehucoFile:
    """A catalog with no roots, at a path nothing writes to: :meth:`RehucoFile.add_root` has a folder to name each
    root's file in (#577), and a test that never saves it touches no disk.

    :returns: the catalog.
    """
    return RehucoFile({"format_version": CURRENT_REHUCO_VERSION, "id": str(uuid4()), "roots": []}, UNSAVED_REHUCO)


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
