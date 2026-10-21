"""Tests for a document adopting a save made elsewhere from a snapshot of it (#497): the blocks that save is owed the
logging of, and what the document takes on once it lands ([[sync#apply-payload]], [[plugins#plugin-blocks]]).
"""

import copy
import json
import logging
from pathlib import Path
from typing import Any, Final

from freezegun.api import FrozenDateTimeFactory
from pytest import LogCaptureFixture
from rehuco_core import RehuDocument, current_block_version

UPDATED: Final = "2026-01-01T00:00:00Z"
"""The ``updated`` stamp the records here are written with."""

LATER: Final = "2026-10-12T10:00:00Z"
"""When the saves here happen."""


def abandoned_audiopack() -> RehuDocument:
    """A document switched from ``audiopack`` to ``tutorial``, so its save drops the audiopack block, carrying a
    never-claimed ``reference_images`` block that is written.

    :returns: the document.
    """
    document = RehuDocument(
        {
            "type": "audiopack",
            "audiopack": {"bitrate": 320},
            "tutorial": {"complete": True},
            "reference_images": {"images_count": 12},
        }
    )
    document.set_active_type("tutorial")
    return document


def written(document: RehuDocument) -> dict[str, Any]:
    """What a save of ``document`` made elsewhere would have written.

    :param document: the document.
    :returns: its payload as written, a copy.
    """
    return copy.deepcopy(document.payload_to_write())


def discard_messages(caplog: LogCaptureFixture) -> list[str]:
    """The block-discard log lines captured so far.

    :param caplog: the log-capture fixture.
    :returns: their messages.
    """
    return [record.getMessage() for record in caplog.records if "discarded on save" in record.getMessage()]


# region unlogged dropped blocks
def test_the_unlogged_dropped_blocks_are_the_abandoned_ones_until_a_save_logs_them(tmp_path: Path) -> None:
    """The blocks a save drops are owed a log line until a save logs them; a carried block never is.

    **Test steps:**

    * switch a document from ``audiopack`` to ``tutorial``; verify only ``audiopack`` is named
    * save it; verify nothing is named any more
    """
    document = abandoned_audiopack()

    assert document.unlogged_dropped_block_keys() == ("audiopack",)
    document.save(tmp_path / "info.rehu")
    assert not document.unlogged_dropped_block_keys()


# region note written
def test_noting_a_write_adopts_the_files_versions_so_no_created_is_stamped(
    tmp_path: Path, freezer: FrozenDateTimeFactory
) -> None:
    """A record written elsewhere has a file now: its version stamps are the written ones, and a later save of the
    document is not its first write.

    **Test steps:**

    * build a document with no file behind it, and note a write of it
    * verify the on-disk file and block versions are the written payload's
    * save the document later; verify no ``created`` was stamped
    """
    document = RehuDocument({"type": "tutorial", "tutorial": {"complete": True}})
    payload = written(document)

    document.note_written(payload, ())

    assert document.on_disk_format_version == payload["format_version"]
    assert document.on_disk_active_block_format_version == payload["tutorial"]["format_version"]
    freezer.move_to(LATER)
    path = tmp_path / "info.rehu"
    document.save(path)
    assert "created" not in json.loads(path.read_text(encoding="utf-8"))["core"]


def test_noting_a_write_moves_the_baseline_updated_is_judged_against(
    tmp_path: Path, freezer: FrozenDateTimeFactory
) -> None:
    """An edit a save made elsewhere wrote is no edit to the next save: it does not stamp ``updated`` again.

    **Test steps:**

    * write a record, load it, and edit its description
    * note a write of the edited document
    * save it later; verify ``updated`` is the one it had
    """
    path = tmp_path / "info.rehu"
    path.write_text(
        json.dumps(
            {
                "format_version": 2,
                "core": {"type": "tutorial", "updated": UPDATED, "created": UPDATED},
                "tutorial": {"format_version": current_block_version("tutorial")},
            }
        ),
        encoding="utf-8",
    )
    document = RehuDocument.load(path)
    document.data["core"]["description"] = "edited"

    document.note_written(written(document), ())
    freezer.move_to(LATER)
    document.save()

    assert json.loads(path.read_text(encoding="utf-8"))["core"]["updated"] == UPDATED


def test_noting_a_write_marks_the_discards_it_logged(tmp_path: Path, caplog: LogCaptureFixture) -> None:
    """A block the save made elsewhere logged as dropped is not logged again by the document's next save.

    **Test steps:**

    * switch a document from ``audiopack`` to ``tutorial``, and note a write that logged ``audiopack``
    * verify nothing is owed a log line, and the document's own save logs no discard
    """
    document = abandoned_audiopack()

    document.note_written(written(document), ("audiopack",))

    assert not document.unlogged_dropped_block_keys()
    with caplog.at_level(logging.INFO, logger="rehuco_core.rehu_document"):
        document.save(tmp_path / "info.rehu")
    assert not discard_messages(caplog)


def test_noting_a_write_ignores_a_discard_of_a_block_it_wrote() -> None:
    """A block named as discarded that the save wrote was not dropped, so it stays owed a log line once it is.

    **Test steps:**

    * note a write of a document naming its carried ``reference_images`` block as discarded
    * claim and abandon ``reference_images``; verify it is owed a log line
    """
    document = abandoned_audiopack()

    document.note_written(written(document), ("audiopack", "reference_images"))
    document.set_active_type("reference_images")
    document.set_active_type("tutorial")

    assert document.unlogged_dropped_block_keys() == ("reference_images",)


def test_noting_a_write_forgets_the_mark_of_a_block_it_wrote_again() -> None:
    """A block written again since its discard was logged is a fresh discard once abandoned again.

    **Test steps:**

    * note a write that logged ``audiopack`` as dropped
    * switch back to ``audiopack`` and note a write of that, which carries it
    * switch away again; verify ``audiopack`` is owed a log line again
    """
    document = abandoned_audiopack()
    document.note_written(written(document), ("audiopack",))
    document.set_active_type("audiopack")

    document.note_written(written(document), ())
    document.set_active_type("tutorial")

    assert document.unlogged_dropped_block_keys() == ("audiopack",)
