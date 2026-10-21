"""Tests for ``DocumentsDock`` opening a record its caller has just read: the read is handed on, not repeated (#497)."""

from pathlib import Path

from pytest import mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.document_registry import DocumentRegistry, load_record
from rehuco_agent.documents.documents_dock import DocumentsDock
from rehuco_core.access import Records, ResourceKey

from .test_rehu_document_model_conflict import write_record


@mark.usefixtures("real_path_stat")
def test_a_record_read_by_the_opener_is_handed_to_the_registry(
    qtbot: QtBot, tmp_path: Path, mocker: MockerFixture
) -> None:
    """Opening a record with the read the caller just made hands that read to the registry, which builds the
    document from it -- one read of the file, not two.

    **Test steps:**

    * read a record titled ``Old``, over a registry whose acquisitions are spied on
    * open the record in the dock with that read
    * verify the registry was asked for it with that very read, and the document shows the record
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old")
    records = Records()
    key = ResourceKey(path)
    read = load_record(records, key)
    registry = DocumentRegistry(records=records)
    acquire = mocker.spy(registry, "acquire")
    dock = DocumentsDock(registry=registry)
    qtbot.addWidget(dock)

    widget = dock.open_document(key, record=read)

    acquire.assert_called_once_with(key, new=False, lazy=False, record=read)
    assert widget.model.title == "Old"
