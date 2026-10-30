"""What the video tree's tests share: a real tutorial of four videos under ``tmp_path``, opened as an open builds it
(#572). The document, its records and its progress are tested elsewhere; these tests wire the tree to them."""

from pathlib import Path
from typing import Final

from pytest import fixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_core.access import Records, ResourceKey

from rehuco_agent_tests.delete_at_teardown import DeleteAtTeardown
from rehuco_agent_tests.documents.test_rehu_document_model_progress import write_tutorial
from rehuco_agent_tests.record_reads import read_now

VIDEOS: Final = ("a.mp4", "01 Basics/b.mp4", "01 Basics/c.mp4", "02 More/d.mp4")
"""The tutorial's videos: one at the top, two in a folder, one in another."""

KEYS: Final = tuple(sorted(VIDEOS))
"""The same, as the listing of the tutorial's folder returns them, for the tree to take."""


@fixture(name="model")
def fixture_model(tmp_path: Path, qtbot: QtBot, delete_at_teardown: DeleteAtTeardown) -> RehuDocumentModel:
    """A model over a real tutorial.

    :param tmp_path: the resource's parent folder.
    :param qtbot: pytest-qt fixture.
    :param delete_at_teardown: deletes the bare model when the test ends.
    :returns: the model.
    """
    del qtbot
    path = write_tutorial(tmp_path / "t", VIDEOS)
    records = Records()
    record = read_now(records, ResourceKey(path))
    return delete_at_teardown(
        RehuDocumentModel(record.document, records=records, version=record.version, signature=record.signature)
    )
