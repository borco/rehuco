"""Tests for records recording per-user notes and favorites (#571, [[field-schema#video-notes]]): core's write under
the caller's identity, answered with the record read after it.
"""

from pathlib import Path

from pytest_mock import MockerFixture
from rehuco_core import Records

from rehuco_core_tests.access.test_records import USERNAME, load, tutorial_data, write_record


def test_a_notes_write_goes_through_core_and_answers_the_record_as_read_after(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    """Recording notes is core's write path with the caller's identity as both the user and the one the record is
    opened as, answered with the record read after it.

    **Test steps:**

    * write a record, and replace core's write with a mock
    * record notes through the records
    * verify core was called with the key's path, the identity twice and what was written, and the answer is the
      record loaded after it
    """
    key = write_record(tmp_path / "info.rehu", tutorial_data())
    write = mocker.patch("rehuco_core.access.records.record_notes")

    loaded = Records().record_notes(
        key, username=USERNAME, notes="About it", video_notes={"a.mp4": "note"}, favorites={"b.mp4": True}
    )

    write.assert_called_once_with(
        key.path,
        USERNAME,
        notes="About it",
        video_notes={"a.mp4": "note"},
        favorites={"b.mp4": True},
        current_username=USERNAME,
    )
    assert loaded.version == load(Records(), key).version
