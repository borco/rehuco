"""Roots as this machine reaches them, for the tests that need a folder per root (#514).

A ``.rehuco`` holds a root's location and a machine's mapping holds its folder. A test that wants a folder per root
spells the location from the folder (:func:`location_at`) and reads it back (:func:`path_at`), so the pair needs no
mapping file and no mount table. Core's tests keep a copy of the same three helpers.
"""

from pathlib import Path, PurePath
from typing import Final
from uuid import UUID, uuid4

from rehuco_core import MappedRoot, RehucoFile, RootStorage

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


def resolve_test_location(location: str) -> Path | None:
    """This machine's folder for a location, as the tests spell them: the folder :func:`location_at` made it from, and
    nothing for any other location -- a share this machine has not mounted.

    :param location: a location.
    :returns: the folder; ``None`` when the location is not one :func:`location_at` spelled.
    """
    return path_at(location) if location.startswith(TEST_HOST) else None


def mapped_root(
    path: Path, label: str, storage: RootStorage = RootStorage.LOCAL, root_id: UUID | None = None
) -> MappedRoot:
    """A root of a catalog as this machine reaches it.

    :param path: the root's folder.
    :param label: its label.
    :param storage: what the folder lives on.
    :param root_id: its id; a fresh one when not given.
    :returns: the root.
    """
    return MappedRoot(root_id or uuid4(), label, location_at(path), path, storage)


def mapped(file: RehucoFile) -> tuple[MappedRoot, ...]:
    """Every root of a catalog whose locations :func:`location_at` spelled, mapped to its folder.

    :param file: the catalog.
    :returns: its roots, in display order, each on the local storage.
    """
    return tuple(MappedRoot(root.root_id, root.label, root.location, path_at(root.location)) for root in file.roots)
