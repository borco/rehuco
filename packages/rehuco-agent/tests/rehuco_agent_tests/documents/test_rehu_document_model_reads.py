"""Tests for a document model whose record is read off the GUI thread (#564, [[offline-editing#overview]]): what it
shows while a read is out, and how a read that arrives is judged -- taken, filled in under a save not landed, or
dropped.

Every read is held back (``held_reads``) and answered when the test says so, with a record made here: reading a file
is ``RecordReader``'s and ``Records``' to test, and the order reads arrive in is the subject.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_core import CURRENT_FORMAT_VERSION, RecordVersion, RehuDocument, SaveOutcome, SavePayload
from rehuco_core.access import KeyRelocation, LoadedRecord, Records, ResourceKey

from rehuco_agent_tests.delete_at_teardown import DeleteAtTeardown
from rehuco_agent_tests.record_reads import HeldReads

PATH: Final = Path.cwd() / "fake" / "a" / "info.rehu"
OTHER: Final = Path.cwd() / "fake" / "b" / "info.rehu"
MOVED: Final = Path.cwd() / "fake" / "moved" / "info.rehu"
READ_SIGNATURE: Final = (1, 10)
"""The file's signature as a read finds it."""

OLDER_FORMAT: Final = CURRENT_FORMAT_VERSION - 1


def document(title: str, path: Path = PATH, *, on_disk: int | None = None) -> RehuDocument:
    """A tutorial titled ``title``.

    :param title: its title.
    :param path: its file.
    :param on_disk: the format version of the file it was read from, or ``None`` for none.
    :returns: the document.
    """
    data = {"type": "Tutorial", "sources": [{"title": title, "primary": True}]}
    return RehuDocument(data, path, on_disk_format_version=on_disk)


def record(
    title: str, path: Path = PATH, *, signature: tuple[int, int] = READ_SIGNATURE, on_disk: int = OLDER_FORMAT
) -> LoadedRecord:
    """A record as a read of its file answers it.

    :param title: what the file titles it.
    :param path: the file.
    :param signature: the file's signature.
    :param on_disk: the file's format version.
    :returns: the record.
    """
    return LoadedRecord(document(title, path, on_disk=on_disk), RecordVersion("meta", title, ()), (), signature)


def unread(path: Path = PATH) -> LoadedRecord:
    """The locked stub a read answers for a file it could not read -- its share offline, or the file gone.

    :param path: the file.
    :returns: the stub.
    """
    stub = RehuDocument.locked_stub_for_error(path, OSError("the share does not answer"))
    return LoadedRecord(stub, None, tuple(stub.lock_reasons), None)


@fixture(name="pending")
def fixture_pending() -> dict[ResourceKey, SavePayload]:
    """The saves not landed, by record, as the window's save owner answers them; none until a test adds one.

    :returns: the saves.
    """
    return {}


@fixture(name="build")
def fixture_build(
    qtbot: QtBot,
    mocker: MockerFixture,
    held_reads: HeldReads,
    pending: dict[ResourceKey, SavePayload],
    delete_at_teardown: DeleteAtTeardown,
) -> Callable[..., RehuDocumentModel]:
    """Build a model over the mocked reader: one read at :data:`PATH` titled ``Old``, or a placeholder for it.

    :param qtbot: pytest-qt fixture.
    :param mocker: pytest-mock fixture.
    :param held_reads: the reads, held until a test answers them.
    :param pending: the saves not landed it follows.
    :param delete_at_teardown: deletes the bare models when the test ends.
    :returns: the builder; ``placeholder=True`` builds an unread one.
    """
    del qtbot, held_reads

    def build(*, placeholder: bool = False) -> RehuDocumentModel:
        common: dict[str, Any] = {
            "records": mocker.Mock(spec=Records),
            "pending_save_of": pending.get,
        }
        if placeholder:
            return delete_at_teardown(RehuDocumentModel.create_pending(PATH, **common))
        read = record("Old")
        return delete_at_teardown(
            RehuDocumentModel(read.document, version=read.version, signature=read.signature, **common)
        )

    return build


def save_of(title: str, path: Path = PATH) -> SavePayload:
    """A Save titling the record ``title``, as a document hands it to its save.

    :param title: the title saved.
    :param path: the record.
    :returns: the payload.
    """
    return RehuDocumentModel(document(title, path)).snapshot()


def disk_signature(model: RehuDocumentModel) -> tuple[int, int] | None:
    """The file's signature as ``model`` last learned it -- what a later stat is compared with.

    :param model: the model.
    :returns: the signature.
    """
    return model._RehuDocumentModel__disk_signature  # type: ignore[attr-defined]  # pylint: disable=protected-access


# region nothing pending: the document waits for its file


def test_a_revert_keeps_what_the_document_shows_until_its_file_arrives(
    build: Callable[..., RehuDocumentModel], held_reads: HeldReads
) -> None:
    """A revert with nothing pending asks for the file and says it is reading it; what the document shows stays until
    the file arrives, and is then the file's.

    **Test steps:**

    * edit the title of a document read as ``Old``, and revert
    * verify the file was asked for, the document says it is reading it, and still shows the edit
    * answer the read with the file titled ``New``
    * verify the document shows ``New``, clean, and is no longer reading
    """
    model = build()
    model.title = "Edited"

    model.revert()

    assert held_reads.keys == [ResourceKey(PATH)]
    assert (model.reading, model.title, model.dirty) == (PATH, "Edited", True)

    held_reads.answer(0, record("New"))

    assert (model.reading, model.title, model.dirty) == (None, "New", False)


def test_a_read_overtaken_by_another_is_dropped(build: Callable[..., RehuDocumentModel], held_reads: HeldReads) -> None:
    """Only the last read asked for is taken: one that arrives after another was asked for is for a document that moved
    on.

    **Test steps:**

    * load another record, then the first one again, before either arrives
    * answer the first read
    * verify nothing was taken, and the document is still reading
    * answer the second
    * verify it was taken
    """
    model = build()
    model.load(OTHER)
    model.load(PATH)

    held_reads.answer(0, record("Other", OTHER))

    assert (model.path, model.title, model.reading) == (PATH, "Old", PATH)

    held_reads.answer(1, record("Again"))

    assert (model.path, model.title, model.reading) == (PATH, "Again", None)


def test_a_save_pending_by_the_time_the_file_arrives_is_shown_over_it(
    build: Callable[..., RehuDocumentModel], held_reads: HeldReads, pending: dict[ResourceKey, SavePayload]
) -> None:
    """The record's saved state is judged when its file arrives, not when it was asked for: a save not landed that
    appeared meanwhile is what the document shows, laid over the file read.

    **Test steps:**

    * revert with nothing pending; then have a save titling the record ``Mine`` appear
    * answer the read with the file titled ``Disk``
    * verify the document shows ``Mine``, clean, based on the file's signature
    """
    model = build()
    model.revert()
    pending[ResourceKey(PATH)] = save_of("Mine")

    held_reads.answer(0, record("Disk", signature=(2, 20)))

    assert (model.title, model.dirty, model.reading) == ("Mine", False, None)
    assert disk_signature(model) == (2, 20)


def test_a_placeholder_whose_read_is_out_is_not_read_again(
    build: Callable[..., RehuDocumentModel], held_reads: HeldReads
) -> None:
    """A second trigger of a placeholder's load while its read is out asks for nothing more (#66).

    **Test steps:**

    * load a placeholder twice before its read arrives
    * verify one read was asked for
    """
    model = build(placeholder=True)

    model.load_pending()
    model.load_pending()

    assert held_reads.keys == [ResourceKey(PATH)]


def test_a_change_on_disk_heard_while_reading_is_left_to_the_read(
    build: Callable[..., RehuDocumentModel], held_reads: HeldReads
) -> None:
    """A stat or a file gone heard while the file is being read reloads nothing and says nothing: the read out shows
    the file as it is.

    **Test steps:**

    * revert, then hear another signature and the file gone
    * verify no second read was asked for, and nothing is said to be gone
    """
    model = build()
    model.revert()

    model.note_file_signature(*(9, 90))
    model.note_file_gone(folder_gone=False)

    assert held_reads.keys == [ResourceKey(PATH)]
    assert model.gone == ""


# endregion

# region a save not landed: shown at once, the read filling in


def test_a_record_with_a_pending_save_opens_on_it_at_once_and_its_read_fills_in_only_what_it_is_based_on(
    build: Callable[..., RehuDocumentModel], held_reads: HeldReads, pending: dict[ResourceKey, SavePayload]
) -> None:
    """A placeholder whose record has a save not landed shows that save at once, editable; the file read arriving later
    fills in its signature and format version, and leaves what the document shows and the edits made meanwhile alone.

    **Test steps:**

    * have a save titling the record ``Mine``, and load a placeholder of it
    * verify it shows ``Mine``, clean, not reading, and the file was asked for
    * retitle it ``Later``
    * answer the read with the file titled ``Disk``, at an older format, with its signature
    * verify the document still shows ``Later``, dirty, and took the file's signature and format version
    """
    pending[ResourceKey(PATH)] = save_of("Mine")
    model = build(placeholder=True)

    model.load_pending()

    assert (model.title, model.dirty, model.reading, model.pending) == ("Mine", False, None, False)
    assert held_reads.keys == [ResourceKey(PATH)]

    model.title = "Later"
    held_reads.answer(0, record("Disk", signature=(3, 30)))

    assert (model.title, model.dirty) == ("Later", True)
    assert disk_signature(model) == (3, 30)
    assert model.document.on_disk_format_version == OLDER_FORMAT


def test_a_file_that_could_not_be_read_fills_in_nothing(
    build: Callable[..., RehuDocumentModel], held_reads: HeldReads, pending: dict[ResourceKey, SavePayload]
) -> None:
    """A read of a record with a save not landed that finds no file -- its share offline -- leaves the document as the
    save shows it, with nothing to compare a later stat with.

    **Test steps:**

    * load a placeholder of a record with a pending save, its file read as unreadable
    * verify the document shows the save, unlocked, with no signature and no on-disk format version
    """
    pending[ResourceKey(PATH)] = save_of("Mine")
    model = build(placeholder=True)
    model.load_pending()

    held_reads.answer(0, unread())

    assert (model.title, model.locked) == ("Mine", False)
    assert disk_signature(model) is None
    assert model.document.on_disk_format_version is None


def test_a_read_out_when_the_save_lands_is_dropped(
    build: Callable[..., RehuDocumentModel], held_reads: HeldReads, pending: dict[ResourceKey, SavePayload]
) -> None:
    """A save that lands while the read filling it in is out says more of the file than that read can: the read is
    dropped when it arrives.

    **Test steps:**

    * load a placeholder of a record with a pending save, and land that save with its own signature
    * answer the read with an older signature
    * verify the document keeps the landed save's signature
    """
    payload = save_of("Mine")
    pending[ResourceKey(PATH)] = payload
    model = build(placeholder=True)
    model.load_pending()
    model.begin_save()
    model.complete_save(payload, SaveOutcome(payload.payload, RecordVersion("meta", "landed", ()), (5, 50), False))

    held_reads.answer(0, record("Disk", signature=(3, 30)))

    assert disk_signature(model) == (5, 50)


def test_a_save_laid_over_a_read_the_caller_made_takes_that_read(
    build: Callable[..., RehuDocumentModel], held_reads: HeldReads, pending: dict[ResourceKey, SavePayload]
) -> None:
    """A holder that read the file itself hands that read over: the record's save not landed is laid over it, and
    nothing is read again.

    **Test steps:**

    * have a save titling the record ``Mine``; follow it with a read of the file the caller made
    * verify the document shows ``Mine``, clean, based on that read's signature, and nothing was asked of the reader
    """
    model = build()
    pending[ResourceKey(PATH)] = save_of("Mine")

    model.follow_pending_save(record("Disk", signature=(4, 40)))

    assert (model.title, model.dirty) == ("Mine", False)
    assert disk_signature(model) == (4, 40)
    assert not held_reads.keys


# endregion

# region waiting for a read, and letting go of one


def test_what_waits_for_a_read_runs_once_it_arrives(
    mocker: MockerFixture, build: Callable[..., RehuDocumentModel], held_reads: HeldReads
) -> None:
    """A caller judging what an open showed waits for the read out, and runs at once when none is.

    **Test steps:**

    * revert, and wait for the read
    * verify nothing ran yet
    * answer the read
    * verify it ran once, the file shown; and waiting again runs at once
    """
    model = build()
    model.revert()
    shown: list[str] = []
    waiting = mocker.Mock(side_effect=lambda: shown.append(model.title))

    model.when_read(waiting)

    waiting.assert_not_called()

    held_reads.answer(0, record("New"))

    assert shown == ["New"]
    model.when_read(waiting)
    assert shown == ["New", "New"]


def test_a_model_let_go_takes_nothing_from_its_read(
    mocker: MockerFixture, build: Callable[..., RehuDocumentModel], held_reads: HeldReads
) -> None:
    """A model its last holder let go of takes nothing from a read that arrives afterwards, and runs nothing that waited
    for it.

    **Test steps:**

    * revert, wait for the read, and stop reading
    * answer the read
    * verify the document did not take it, and nothing ran
    """
    model = build()
    model.revert()
    waiting = mocker.Mock()
    model.when_read(waiting)

    model.stop_reading()
    held_reads.answer(0, record("New"))

    assert model.title == "Old"
    waiting.assert_not_called()


def test_a_read_follows_a_rename_of_the_record_it_reads(
    build: Callable[..., RehuDocumentModel], held_reads: HeldReads
) -> None:
    """A rename that moves the record being read asks for it where it went; what the old path answers is dropped.

    **Test steps:**

    * load another record, and rename its folder before the read arrives
    * verify the record was asked for again at its new path
    * answer the first read, then the second
    * verify only the second was taken
    """
    model = build()
    model.load(OTHER)

    model.relocate(KeyRelocation(((ResourceKey(OTHER.parent), ResourceKey(MOVED.parent)),)))

    assert held_reads.keys == [ResourceKey(OTHER), ResourceKey(MOVED)]

    held_reads.answer(0, record("Stale", OTHER))

    assert model.reading == MOVED

    held_reads.answer(1, record("Moved", MOVED))

    assert (model.path, model.title, model.reading) == (MOVED, "Moved", None)


# endregion
