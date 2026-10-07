"""Tests for the checksum state the Roots view's model gives a covered file, read where the folder is listed (#457).

The folders and the records are real, under ``tmp_path``: what is under test is what a listing reads and how the model
keeps its rows up with it.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QModelIndex, Qt
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.files_rows import FileChecksumState
from rehuco_agent.rehuco.roots_checksum import RowChecksum
from rehuco_agent.rehuco.roots_folder_model import NodeListing, RootFolderLoader, RootsFolderModel
from rehuco_core import Relocation

from rehuco_agent_tests.rehuco.test_roots_folder_model import (
    WAIT_TIMEOUT_MS,
    Recorder,
    child,
    make_model,
    make_root,
    names,
    open_folder,
)


def stamp(days: float) -> str:
    """When a check was made, ``days`` ago, as a record writes it.

    :param days: how long ago.
    :returns: the stamp.
    """
    return (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def record_entry(name: str, status: str = "matched", days: float = 1) -> dict[str, str]:
    """One checksum entry, hashed and dated.

    :param name: the file's name under the record.
    :param status: what the check answered.
    :param days: how long ago it was made.
    :returns: the entry.
    """
    return {"name": name, "crc32": "aabbccdd", "verified": stamp(days), "status": status}


def write_checksum(path: Path, *entries: dict[str, str]) -> None:
    """Write a ``.checksum`` record.

    :param path: the record.
    :param entries: its entries.
    """
    path.write_text(json.dumps({"version": 1, "files": list(entries)}), encoding="utf-8")


@fixture(name="covered_library")
def covered_library_fixture(tmp_path: Path) -> Path:
    """A root holding ``pack``, a directory-scoped resource with a checksum record and a covered subfolder, ``legacy``,
    one an ``info.tc`` describes, and ``bare``, an ``info.rehu`` with no checksum file.

    :param tmp_path: pytest's temporary directory.
    :returns: the root folder.
    """
    root = tmp_path / "covered"
    for folder in ("pack/sub", "legacy/sub", "bare/sub"):
        (root / folder).mkdir(parents=True)
    for name in ("pack/info.rehu", "bare/info.rehu", "bare/sub/x.mp4", "legacy/info.tc", "legacy/sub/z.mp4"):
        (root / name).write_text("{}", encoding="utf-8")
    for name in ("fresh.mp4", "stale.mp4", "bad.mp4", "unlisted.mp4", "info00.jpg", "sub/deep.mp4"):
        (root / "pack" / name).write_bytes(b"x")
    write_checksum(
        root / "pack" / "info.checksum",
        record_entry("fresh.mp4"),
        record_entry("stale.mp4", days=400),
        record_entry("bad.mp4", "mismatched"),
        record_entry("sub/deep.mp4"),
    )
    write_checksum(root / "legacy" / "info.checksum", record_entry("sub/z.mp4"))
    return root


def state_of(model: RootsFolderModel, index: QModelIndex) -> FileChecksumState | None:
    """The checksum state a row shows.

    :param model: the model.
    :param index: the row.
    :returns: its state; ``None`` for a row no record covers.
    """
    checksum = model.data(index, RootsFolderModel.CHECKSUM_ROLE)
    return checksum.state if isinstance(checksum, RowChecksum) else None


def test_a_covered_file_carries_what_its_record_found_and_the_rest_carry_nothing(
    qtbot: QtBot, covered_library: Path
) -> None:
    """The state is read where the folder is listed, and every file reads it from the record that covers it.

    **Test steps:**

    * list a folder whose ``info.checksum`` has a fresh match, an old match, a mismatch and no entry for one file
    * verify each file's state, that a record and a screenshot carry none and are bookkeeping, and that a row's
      tooltip is the state's own words
    """
    model = make_model(qtbot, [make_root(covered_library)])
    pack = child(model, model.index(0, 0), "pack")
    open_folder(qtbot, model, pack)

    states = {name: state_of(model, child(model, pack, name)) for name in names(model, pack)}

    assert states == {
        "sub": None,
        "bad.mp4": FileChecksumState.BAD,
        "fresh.mp4": FileChecksumState.OK,
        "info00.jpg": None,
        "info.checksum": None,
        "info.rehu": None,
        "stale.mp4": FileChecksumState.OLD_OK,
        "unlisted.mp4": FileChecksumState.MISSING,
    }
    assert child(model, pack, "info00.jpg").data(RootsFolderModel.BOOKKEEPING_ROLE) is True
    assert child(model, pack, "fresh.mp4").data(RootsFolderModel.BOOKKEEPING_ROLE) is False
    assert child(model, pack, "fresh.mp4").data(Qt.ItemDataRole.ToolTipRole) == "Checksum matched, checked recently."


def test_a_folder_below_a_resource_is_read_from_the_record_above_it(qtbot: QtBot, covered_library: Path) -> None:
    """The model names the record from the listings it already holds, so a subfolder costs no extra disk read.

    **Test steps:**

    * open ``pack`` and then its ``sub``, and do the same under ``legacy`` (an ``info.tc``)
    * verify the files in each subfolder read their entry from ``info.checksum`` above
    """
    model = make_model(qtbot, [make_root(covered_library)])
    root = model.index(0, 0)
    pack = child(model, root, "pack")
    open_folder(qtbot, model, pack)
    pack_sub = child(model, pack, "sub")
    open_folder(qtbot, model, pack_sub)
    legacy = child(model, root, "legacy")
    open_folder(qtbot, model, legacy)
    legacy_sub = child(model, legacy, "sub")
    open_folder(qtbot, model, legacy_sub)

    assert state_of(model, child(model, pack_sub, "deep.mp4")) is FileChecksumState.OK
    assert state_of(model, child(model, legacy_sub, "z.mp4")) is FileChecksumState.OK


def test_a_resource_with_no_checksum_file_covers_nothing_below_it(qtbot: QtBot, covered_library: Path) -> None:
    """An ``info.rehu`` alone gives no file a state, and does not borrow one from a record further up.

    **Test steps:**

    * open ``bare`` and its ``sub``
    * verify the file in ``sub`` has no state
    """
    model = make_model(qtbot, [make_root(covered_library)])
    bare = child(model, model.index(0, 0), "bare")
    open_folder(qtbot, model, bare)
    sub = child(model, bare, "sub")
    open_folder(qtbot, model, sub)

    assert state_of(model, child(model, sub, "x.mp4")) is None


def test_a_rewritten_record_changes_the_rows_in_place(qtbot: QtBot, covered_library: Path) -> None:
    """A verify rewrites the record: listing every loaded folder under it again moves the states without a reset.

    **Test steps:**

    * open ``pack`` and its ``sub``, then record a mismatch for ``sub/deep.mp4`` and an entry for ``unlisted.mp4``
    * list everything under ``pack`` again
    * verify both rows show their new state, and the model announced changes, not a reset
    """
    model = make_model(qtbot, [make_root(covered_library)])
    pack = child(model, model.index(0, 0), "pack")
    open_folder(qtbot, model, pack)
    sub = child(model, pack, "sub")
    open_folder(qtbot, model, sub)
    deep, unlisted = child(model, sub, "deep.mp4"), child(model, pack, "unlisted.mp4")
    assert state_of(model, deep) is FileChecksumState.OK
    assert state_of(model, unlisted) is FileChecksumState.MISSING
    recorder = Recorder(model)

    write_checksum(
        covered_library / "pack" / "info.checksum",
        record_entry("fresh.mp4"),
        record_entry("sub/deep.mp4", "mismatched"),
        record_entry("unlisted.mp4"),
    )
    model.relist_under(covered_library / "pack")
    qtbot.waitUntil(lambda: state_of(model, deep) is FileChecksumState.BAD, timeout=WAIT_TIMEOUT_MS)
    qtbot.waitUntil(lambda: state_of(model, unlisted) is FileChecksumState.OK, timeout=WAIT_TIMEOUT_MS)

    assert recorder.count("reset") == 0
    assert recorder.count("changed") >= 2


def test_listing_under_a_folder_the_model_does_not_hold_does_nothing(qtbot: QtBot, covered_library: Path) -> None:
    """A verify of a resource nobody has opened is not the Roots view's business.

    **Test steps:**

    * ask for everything under a folder no root holds
    * verify no row changed
    """
    model = make_model(qtbot, [make_root(covered_library)])
    recorder = Recorder(model)

    model.relist_under(covered_library.parent / "elsewhere")

    assert not recorder.events


def test_a_folder_being_listed_again_still_names_what_it_holds(
    qtbot: QtBot, mocker: MockerFixture, covered_library: Path
) -> None:
    """The pane rebuilds its buttons from the names while a relist is out; "nothing" there would disable them for good.

    **Test steps:**

    * open ``pack``, hold every further listing back, list ``pack`` again and a root's other folder for the first time
    * verify the folder with rows still answers with them, and the one with none says it knows nothing
    """
    model = make_model(qtbot, [make_root(covered_library)])
    root = model.index(0, 0)
    pack, bare = child(model, root, "pack"), child(model, root, "bare")
    open_folder(qtbot, model, pack)
    before = model.child_names(pack)
    assert before
    mocker.patch.object(RootFolderLoader, "start")

    model.relist(pack)
    model.fetchMore(bare)

    assert model.listing_state(pack) is NodeListing.PENDING
    assert model.child_names(pack) == before
    assert model.listing_state(bare) is NodeListing.PENDING
    assert model.child_names(bare) is None


# endregion


def test_a_renamed_file_keeps_its_state(qtbot: QtBot, covered_library: Path) -> None:
    """A rename the app made moves the row in place and reads nothing: the state travels with it until the next listing.

    **Test steps:**

    * open ``pack``, rename its mismatched file on disk and tell the model
    * verify the row under its new name still reads *not matching*, and nothing was reset
    """
    model = make_model(qtbot, [make_root(covered_library)])
    pack = child(model, model.index(0, 0), "pack")
    open_folder(qtbot, model, pack)
    recorder = Recorder(model)
    source, destination = covered_library / "pack" / "bad.mp4", covered_library / "pack" / "zz.mp4"
    source.rename(destination)

    model.relocate(Relocation(((source, destination),)))

    assert state_of(model, child(model, pack, "zz.mp4")) is FileChecksumState.BAD
    assert recorder.count("reset") == 0
