"""Tests for which archives the Roots view takes for reference packs, through the real cache rows (#484, #456).

The records are real files under ``tmp_path`` that the catalog reads when their folder is listed (#487), so the cache
rows the answers come from are the ones a session would have. The docks, the in-memory cache and the folders are
:mod:`test_catalog_docks`' own fixtures, imported by name.
"""

import threading
from collections.abc import Generator
from pathlib import Path
from typing import Any

from PySide6.QtCore import QModelIndex
from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco.roots_lightbox import ImagesOwner
from rehuco_agent.rehuco.roots_management import PackInfo, PackState, pack_info
from rehuco_core import CatalogRecordReader, RehuDocument

from .test_catalog_docks import (  # noqa: F401  # pylint: disable=unused-import
    REHUCO_PATH,
    WAIT_TIMEOUT_MS,
    CatalogDocks,
    fixture_database,
    fixture_dock,
    fixture_folders,
    fixture_no_open_scan,
    fixture_queue,
    fixture_served,
    open_root_folder,
    without_separators,
)
from .test_catalog_verify import settle


def write_record(path: Path, type_name: str) -> None:
    """Write a ``.rehu`` of the given type.

    :param path: where the record goes.
    :param type_name: its active type, as a record spells it.
    """
    path.touch()  # the suite's default ``Path.stat`` answers a missing file with a mock the atomic write cannot use
    document = RehuDocument.new(path)
    document.set_active_type(type_name)
    document.title = path.stem
    document.save()


def add_packs(folders: Path) -> None:
    """Give the first root the archives and records the recognition tests ask about.

    ``my folder`` holds ``pack.zip`` with its own reference-images ``pack.rehu``, ``talk.zip`` with a tutorial
    ``talk.rehu``, and ``loose.zip`` with no record; ``alpha`` holds a reference-images ``info.rehu`` with ``inner.zip``
    under it.

    :param folders: the first root's folder.
    """
    inside = folders / "my folder"
    for name in ("pack.zip", "talk.zip", "loose.zip"):
        (inside / name).write_bytes(b"z")
    write_record(inside / "pack.rehu", "ReferenceImages")
    write_record(inside / "talk.rehu", "tutorial")
    (folders / "alpha" / "inner.zip").write_bytes(b"z")
    write_record(folders / "alpha" / "info.rehu", "ReferenceImages")


def pack_of(dock: CatalogDocks, index: QModelIndex) -> PackInfo:
    """What the Roots view knows of an archive row: the real model and the real cache.

    :param dock: the catalog's docks.
    :param index: the archive's row.
    :returns: the answer.
    """
    info = pack_info(dock.roots.roots_model, index, dock.catalog.resource_type)
    assert info is not None
    return info


def wait_for_rows(qtbot: QtBot, dock: CatalogDocks, *records: Path) -> None:
    """Wait until the cache has a row for each record.

    :param qtbot: pytest-qt fixture.
    :param dock: the catalog's docks.
    :param records: the records' paths.
    """
    qtbot.waitUntil(
        lambda: all(dock.catalog.resource_type(record) is not None for record in records), timeout=WAIT_TIMEOUT_MS
    )


@fixture(name="gated_reads")
def fixture_gated_reads(mocker: MockerFixture) -> Generator[threading.Event]:
    """Hold every record read a listing's verify makes until the test lets them go.

    :param mocker: pytest-mock fixture.
    :yields: the event that releases them; set when the test ends, so no pool thread stays blocked.
    """
    release = threading.Event()
    real = CatalogRecordReader.read

    def read(path: Path) -> Any:
        assert release.wait(WAIT_TIMEOUT_MS / 1000)
        return real(path)

    mocker.patch("rehuco_core.rehudb_updates.CatalogRecordReader.read", side_effect=read)
    yield release
    release.set()


@mark.usefixtures("served")
def test_a_pack_is_told_by_its_own_record_or_its_folders_and_a_zip_of_another_type_is_not_one(
    qtbot: QtBot, dock: CatalogDocks, folders: Path
) -> None:
    """The type in the cache row of the managing record decides, whichever record that is.

    **Test steps:**

    * list ``my folder`` and ``alpha``, which hold a reference pack with its own record, a zip beside a tutorial
      record, a zip with no record, and a zip under a folder's reference-images ``info.rehu``
    * wait for the cache to have a row for each record
    * verify the answer for each zip: the pack through ``pack.rehu``, the pack through ``info.rehu``, and the others
      not packs
    """
    add_packs(folders)
    dock.catalog.open_rehuco(REHUCO_PATH)
    inside = folders / "my folder"
    pack = open_root_folder(qtbot, dock, "my folder", "pack.zip")
    talk = open_root_folder(qtbot, dock, "my folder", "talk.zip")
    loose = open_root_folder(qtbot, dock, "my folder", "loose.zip")
    inner = open_root_folder(qtbot, dock, "alpha", "inner.zip")
    wait_for_rows(qtbot, dock, inside / "pack.rehu", inside / "talk.rehu", folders / "alpha" / "info.rehu")

    assert pack_of(dock, pack) == PackInfo(PackState.PACK, inside / "pack.rehu")
    assert pack_of(dock, inner) == PackInfo(PackState.PACK, folders / "alpha" / "info.rehu")
    assert pack_of(dock, talk) == PackInfo(PackState.NOT_PACK, inside / "talk.rehu")
    assert pack_of(dock, loose) == PackInfo(PackState.NOT_PACK)


@mark.usefixtures("served")
def test_a_record_the_cache_has_no_row_for_leaves_its_zip_unscanned_until_the_row_lands(
    qtbot: QtBot, dock: CatalogDocks, folders: Path, gated_reads: threading.Event
) -> None:
    """Between listing a folder and the verify that reads its records, a zip is neither a pack nor not one.

    **Test steps:**

    * hold the record reads, and list a folder holding ``pack.zip`` with its ``pack.rehu``
    * verify the zip is unscanned, naming the record that manages it
    * let the reads go and wait for the row
    * verify the zip is now a pack
    """
    add_packs(folders)
    dock.catalog.open_rehuco(REHUCO_PATH)
    record = folders / "my folder" / "pack.rehu"
    pack = open_root_folder(qtbot, dock, "my folder", "pack.zip")

    assert pack_of(dock, pack) == PackInfo(PackState.UNSCANNED, record)

    gated_reads.set()
    wait_for_rows(qtbot, dock, record)

    assert pack_of(dock, pack) == PackInfo(PackState.PACK, record)


@mark.usefixtures("served")
def test_a_pack_through_its_folders_record_is_opened_by_default_with_the_lightbox_entry_in_bold(
    mocker: MockerFixture, qtbot: QtBot, dock: CatalogDocks, folders: Path
) -> None:
    """A zip under a reference-images ``info.rehu`` has the lightbox as its default, as a pack of its own record has.

    **Test steps:**

    * list ``alpha``, wait for the cache to type its ``info.rehu``, and select ``inner.zip``
    * verify the menu and the buttons start with the lightbox entry, in bold, the external app's not
    * double-click the zip and verify the lightbox was asked for it
    """
    add_packs(folders)
    dock.catalog.open_rehuco(REHUCO_PATH)
    opened = mocker.patch.object(dock.roots.lightbox, "open_archive")
    inner = open_root_folder(qtbot, dock, "alpha", "inner.zip")
    wait_for_rows(qtbot, dock, folders / "alpha" / "info.rehu")
    settle(qtbot)
    roots = dock.roots

    assert without_separators(roots.roots_context_actions(inner))[:2] == [
        roots.open_lightbox_action,
        roots.open_file_action,
    ]
    assert roots.open_lightbox_action.font().bold() and not roots.open_file_action.font().bold()

    roots.roots_view.doubleClicked.emit(inner)

    opened.assert_called_once()
    assert opened.call_args.args[0] == folders / "alpha" / "inner.zip"
    assert isinstance(opened.call_args.args[1], ImagesOwner)
