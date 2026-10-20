"""Tests for which archives the Roots view takes for reference packs, through the cache rows of the records that manage
them (#484, #456).

The folders are real, under ``tmp_path``, so the Roots view lists them; the rows the answers come from are held by the
mock catalog (``cached_rows``). The docks, the mock catalog and the folders are :mod:`test_catalog_docks`' own
fixtures, imported by name.
"""

from pathlib import Path
from unittest.mock import Mock

from PySide6.QtCore import QModelIndex
from pytest import mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco.roots_management import PackInfo, PackState, pack_info
from rehuco_agent.rehuco.roots_preview import RootsPreview
from rehuco_agent.resource_events import ResourceEvents
from rehuco_core import CatalogRecord, CatalogRow, RecordKind, TaskQueue
from rehuco_core.access import ResourceKey

from rehuco_agent_tests.delete_at_teardown import DeleteAtTeardown

from .test_catalog_docks import (  # noqa: F401  # pylint: disable=unused-import
    REHUCO_PATH,
    CatalogDocks,
    build_docks,
    catalog_row,
    fixture_cache,
    fixture_cached_rows,
    fixture_catalog,
    fixture_dock,
    fixture_folders,
    fixture_no_open_scan,
    fixture_queue,
    fixture_served,
    open_root_folder,
    publish_changed,
    without_separators,
)


def add_packs(folders: Path) -> None:
    """Give the first root the archives and records the recognition tests ask about.

    ``my folder`` holds ``pack.zip`` with its own ``pack.rehu``, ``talk.zip`` with ``talk.rehu``, and ``loose.zip``
    with no record; ``alpha`` holds an ``info.rehu`` with ``inner.zip`` under it. The records are empty: what they are
    is their cache rows' (:func:`hold_rows`).

    :param folders: the first root's folder.
    """
    inside = folders / "my folder"
    for name in ("pack.zip", "talk.zip", "loose.zip", "pack.rehu", "talk.rehu"):
        (inside / name).write_bytes(b"")
    (folders / "alpha" / "inner.zip").write_bytes(b"")
    (folders / "alpha" / "info.rehu").write_bytes(b"")


def typed_row(resource_id: int, path: str, type_name: str) -> CatalogRow:
    """A first-root record's row, of a type.

    :param resource_id: its id.
    :param path: root-relative.
    :param type_name: its type, as a record spells it.
    :returns: the row.
    """
    return catalog_row(resource_id, 0, CatalogRecord(path, RecordKind.REHU, type=type_name))


def hold_rows(cached_rows: list[CatalogRow]) -> None:
    """Make the cache hold a reference-images row for ``pack.rehu`` and ``alpha/info.rehu``, and a tutorial's for
    ``talk.rehu``.

    :param cached_rows: what the mock catalog holds.
    """
    cached_rows.extend(
        (
            typed_row(1, "my folder/pack.rehu", "ReferenceImages"),
            typed_row(2, "my folder/talk.rehu", "tutorial"),
            typed_row(3, "alpha/info.rehu", "ReferenceImages"),
        )
    )


def pack_of(dock: CatalogDocks, index: QModelIndex) -> PackInfo:
    """What the Roots view knows of an archive row.

    :param dock: the catalog's docks.
    :param index: the archive's row.
    :returns: the answer.
    """
    info = pack_info(dock.roots.roots_model, index, dock.catalog.resource_type)
    assert info is not None
    return info


@mark.usefixtures("served")
def test_a_pack_is_told_by_its_own_record_or_its_folders_and_a_zip_of_another_type_is_not_one(
    qtbot: QtBot, dock: CatalogDocks, folders: Path, cached_rows: list[CatalogRow]
) -> None:
    """The type in the cache row of the managing record decides, whichever record that is.

    **Test steps:**

    * list ``my folder`` and ``alpha``, which hold a reference pack with its own record, a zip beside a tutorial
      record, a zip with no record, and a zip under a folder's reference-images ``info.rehu``, each record with its row
    * verify the answer for each zip: the pack through ``pack.rehu``, the pack through ``info.rehu``, and the others
      not packs
    """
    add_packs(folders)
    hold_rows(cached_rows)
    dock.catalog.open_rehuco(REHUCO_PATH)
    inside = folders / "my folder"
    pack = open_root_folder(qtbot, dock, "my folder", "pack.zip")
    talk = open_root_folder(qtbot, dock, "my folder", "talk.zip")
    loose = open_root_folder(qtbot, dock, "my folder", "loose.zip")
    inner = open_root_folder(qtbot, dock, "alpha", "inner.zip")

    assert pack_of(dock, pack) == PackInfo(PackState.PACK, inside / "pack.rehu")
    assert pack_of(dock, inner) == PackInfo(PackState.PACK, folders / "alpha" / "info.rehu")
    assert pack_of(dock, talk) == PackInfo(PackState.NOT_PACK, inside / "talk.rehu")
    assert pack_of(dock, loose) == PackInfo(PackState.NOT_PACK)


@mark.usefixtures("served")
def test_a_record_the_cache_has_no_row_for_leaves_its_zip_unscanned_until_the_row_lands(
    qtbot: QtBot, dock: CatalogDocks, folders: Path, cached_rows: list[CatalogRow]
) -> None:
    """Until the cache has a row for the record that manages it, a zip is neither a pack nor not one.

    **Test steps:**

    * list a folder holding ``pack.zip`` with its ``pack.rehu``, with no row for the record
    * verify the zip is unscanned, naming the record that manages it
    * give the record its row
    * verify the zip is now a pack
    """
    add_packs(folders)
    dock.catalog.open_rehuco(REHUCO_PATH)
    record = folders / "my folder" / "pack.rehu"
    pack = open_root_folder(qtbot, dock, "my folder", "pack.zip")

    assert pack_of(dock, pack) == PackInfo(PackState.UNSCANNED, record)

    cached_rows.append(typed_row(1, "my folder/pack.rehu", "ReferenceImages"))

    assert pack_of(dock, pack) == PackInfo(PackState.PACK, record)


@mark.usefixtures("served")
def test_a_pack_through_its_folders_record_is_opened_by_default_with_the_lightbox_entry_in_bold(
    mocker: MockerFixture, qtbot: QtBot, dock: CatalogDocks, folders: Path, cached_rows: list[CatalogRow]
) -> None:
    """A zip under a reference-images ``info.rehu`` has the lightbox as its default, as a pack of its own record has.

    **Test steps:**

    * list ``alpha``, whose ``info.rehu`` has a reference-images row, and select ``inner.zip``
    * verify the menu and the buttons start with the lightbox entry, in bold, the external app's not
    * double-click the zip and verify the lightbox was asked for it
    """
    add_packs(folders)
    hold_rows(cached_rows)
    dock.catalog.open_rehuco(REHUCO_PATH)
    opened = mocker.patch.object(dock.roots.lightbox, "open_archive")
    inner = open_root_folder(qtbot, dock, "alpha", "inner.zip")
    roots = dock.roots

    assert without_separators(roots.roots_context_actions(inner))[:2] == [
        roots.open_lightbox_action,
        roots.open_file_action,
    ]
    assert roots.open_lightbox_action.font().bold() and not roots.open_file_action.font().bold()

    roots.roots_view.doubleClicked.emit(inner)

    opened.assert_called_once()
    assert opened.call_args.args[0] == folders / "alpha" / "inner.zip"


@mark.usefixtures("served")
# pylint: disable-next=too-many-arguments,too-many-positional-arguments
def test_a_change_to_the_record_the_pane_reads_shows_the_row_again_and_another_change_does_not(
    mocker: MockerFixture,
    qtbot: QtBot,
    queue: TaskQueue,
    catalog: Mock,
    folders: Path,
    cached_rows: list[CatalogRow],
    delete_at_teardown: DeleteAtTeardown,
) -> None:
    """The pane shows the current row again when a change touches the record its pack line comes from, or the record
    the row stands for -- and only then (#487, #511).

    **Test steps:**

    * select ``pack.zip``, whose pack line comes from ``pack.rehu``; publish ``talk.rehu`` changed, then ``pack.rehu``
    * verify only the second showed the row again
    * select ``talk.rehu`` itself and publish it changed: verify the row was shown again
    """
    add_packs(folders)
    hold_rows(cached_rows)
    events = delete_at_teardown(ResourceEvents())
    dock = build_docks(qtbot, queue, events, catalog=catalog)
    dock.catalog.open_rehuco(REHUCO_PATH)
    inside = folders / "my folder"
    try:
        dock.roots.roots_view.setCurrentIndex(open_root_folder(qtbot, dock, "my folder", "pack.zip"))
        mocker.patch.object(RootsPreview, "follow_changes")  # the preview's own following, tested with it
        refresh = mocker.spy(RootsPreview, "refresh")

        publish_changed(events, (ResourceKey(inside / "talk.rehu"),))
        refresh.assert_not_called()
        publish_changed(events, (ResourceKey(inside / "pack.rehu"),))
        refresh.assert_called_once()

        dock.roots.roots_view.setCurrentIndex(open_root_folder(qtbot, dock, "my folder", "talk.rehu"))
        refresh.reset_mock()
        publish_changed(events, (ResourceKey(inside / "talk.rehu"),))
        refresh.assert_called_once()
    finally:
        dock.detach()
