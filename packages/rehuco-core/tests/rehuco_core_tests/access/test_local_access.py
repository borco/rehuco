"""Tests for the local access's records group (#416)."""

from pathlib import Path

from rehuco_core import Changed, ChangeEvent, ChangeFeed, LocalAccess, LocalKey, LocalRecords, RehuDocument


def test_local_access_answers_records_on_its_own_change_feed(tmp_path: Path) -> None:
    """``records`` is one :class:`LocalRecords` for the access's life, and announces on the access's feed.

    **Test steps:**

    * build a local access over a listened-to feed
    * save a new record through its records
    * verify the group is the same object each time and the save was announced on the feed
    """
    feed = ChangeFeed()
    heard: list[ChangeEvent] = []
    feed.add_listener(heard.append)
    access = LocalAccess(feed)
    key = LocalKey(tmp_path / "info.rehu")

    access.records.save(key, RehuDocument({"format_version": 2, "core": {}}), None, username="admin", overwrite=False)

    assert isinstance(access.records, LocalRecords)
    assert access.records is access.records
    assert heard == [Changed((key,))]
