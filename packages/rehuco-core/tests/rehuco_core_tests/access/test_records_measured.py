"""Tests for a save meeting lengths a Measure wrote into the record meanwhile (#648, [[field-schema#watch-progress]]):
the app's own write, so never a conflict, and kept rather than undone.
"""

from pathlib import Path
from typing import Final

from rehuco_core import VIDEOS_KEY, Records, VideoFacts

from rehuco_core_tests.access.test_records import USERNAME, load, on_disk, tutorial_data, write_record

MEASURED: Final = {"a.mp4": VideoFacts(60.0)}
"""What a Measure finds in the tutorial."""


def test_lengths_a_measure_wrote_meanwhile_are_no_conflict_and_are_kept(tmp_path: Path) -> None:
    """A Measure landing between a document's read and its save leaves the save to land: the edit is written, and the
    lengths stay as the Measure wrote them, not as the document last read them.

    **Test steps:**

    * load a tutorial; meanwhile, a Measure writes its lengths
    * change the loaded description and save against the loaded version
    * verify the file holds the new description and the Measure's lengths
    """
    path = tmp_path / "info.rehu"
    key = write_record(path, tutorial_data())
    records = Records()
    loaded = load(records, key)
    records.record_videos(key, MEASURED, username=USERNAME)

    loaded.document.description = "mine"
    records.save(key, loaded.document, loaded.version, username=USERNAME, overwrite=False)

    stored = on_disk(path)
    assert stored["core"]["description"] == "mine"
    assert stored["tutorial"][VIDEOS_KEY] == {"a.mp4": MEASURED["a.mp4"].to_stored()}


def test_lengths_a_measure_removed_meanwhile_stay_removed(tmp_path: Path) -> None:
    """A Measure that found no video meanwhile removes the map, and the save does not bring the read one back.

    **Test steps:**

    * write a tutorial with measured lengths and load it; meanwhile, a Measure finds none
    * change the loaded description and save against the loaded version
    * verify the file holds the new description and no lengths
    """
    path = tmp_path / "info.rehu"
    key = write_record(path, tutorial_data())
    records = Records()
    records.record_videos(key, MEASURED, username=USERNAME)
    loaded = load(records, key)
    records.record_videos(key, {}, username=USERNAME)

    loaded.document.description = "mine"
    records.save(key, loaded.document, loaded.version, username=USERNAME, overwrite=False)

    stored = on_disk(path)
    assert stored["core"]["description"] == "mine"
    assert VIDEOS_KEY not in stored["tutorial"]
