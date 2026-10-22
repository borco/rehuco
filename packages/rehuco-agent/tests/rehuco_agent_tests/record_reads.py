"""Records read the way a document reads them, on the test's own thread, and reads held until a test answers them
(#564); with the fixtures that hold or answer them, imported by name into the package's ``conftest.py``."""

from collections.abc import Callable
from typing import Final
from unittest.mock import Mock

from pytest import fixture
from pytest_mock import MockerFixture
from rehuco_agent.documents.record_reader import RecordReader
from rehuco_core.access import LoadedRecord, Records, ResourceKey


def read_now(records: Records, key: ResourceKey) -> LoadedRecord:
    """Read ``key`` as a document's reader would, under the identity set now, without its thread.

    The identity is the reader's own (:meth:`RecordReader.identity`), so a test standing in for it reaches this read
    too.

    :param records: what the record is read through.
    :param key: the record.
    :returns: the record, or a locked stub standing in for it.
    """
    username, unknown_username = RecordReader.identity()
    return RecordReader.read_record(records, key, username=username, unknown_username=unknown_username)


class HeldReads:
    """Every read a document asks for, held back until a test answers it -- in whatever order the test chooses, so a
    read arriving late, overtaken or never is something a test makes happen rather than waits for.

    :param read: the stand-in for :meth:`RecordReader.read`, autospecced, so each call carries its reader.
    """

    def __init__(self, read: Mock) -> None:
        self.read: Final = read

    @property
    def keys(self) -> list[ResourceKey]:
        """The record each read was asked for, in the order asked."""
        return [call.args[1] for call in self.read.call_args_list]

    def answer(self, index: int, record: LoadedRecord | None = None) -> None:
        """Hand read ``index`` its record, as its reader would on the GUI thread.

        :param index: which read, in the order asked.
        :param record: what it read; ``None`` reads the file now, through the reader's own records.
        """
        reader, key, callback = self.read.call_args_list[index].args
        if record is None:
            record = read_now(reader._RecordReader__records, key)  # pylint: disable=protected-access
        callback(record)


@fixture(name="inline_record_reads", autouse=True)
def fixture_inline_record_reads(mocker: MockerFixture) -> None:
    """Have every record a document reads arrive at once, on the caller's thread, unless a test patches it again (#564).

    :class:`~rehuco_agent.documents.record_reader.RecordReader` reads on a daemon thread and answers on the GUI thread;
    its own tests cover that, and the documents' tests of a read arriving late hold the answers themselves. Everything
    else here opens, reverts and loads a document and looks at it straight away, as it did while reads were inline.

    :param mocker: pytest-mock fixture.
    """

    def read(reader: RecordReader, key: ResourceKey, answer: Callable[[LoadedRecord], None]) -> None:
        answer(read_now(reader._RecordReader__records, key))  # type: ignore[attr-defined]  # pylint: disable=protected-access

    mocker.patch.object(RecordReader, "read", read)


@fixture(name="held_reads")
def fixture_held_reads(inline_record_reads: None, mocker: MockerFixture) -> HeldReads:
    """Hold back every record a document reads until the test answers it (#564), in place of
    :func:`inline_record_reads`.

    :param inline_record_reads: the inline stand-in this replaces, so it is in place first.
    :param mocker: pytest-mock fixture.
    :returns: the reads asked for.
    """
    del inline_record_reads
    return HeldReads(mocker.patch.object(RecordReader, "read", autospec=True))
