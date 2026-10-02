"""Tests for RehucoSettings: the open ``.rehuco`` and the recently opened ones (#377).

Persistence runs through the conftest's in-memory ``QSettings`` stand-in, so nothing real is touched. The recents
themselves are a `RecentFilesSettings`, tested in its own module; here only their composition is covered.
"""

from pathlib import Path
from typing import Final

from pytest import fixture
from rehuco_agent.settings.recent_files_settings import MAXIMUM_RECENT_FILES
from rehuco_agent.settings.rehuco_settings import RECENT_GROUP, RehucoSettings

from rehuco_agent_tests.conftest import FakeSettings

FIRST: Final = Path.cwd() / "fake" / "first.rehuco"
SECOND: Final = Path.cwd() / "fake" / "second.rehuco"


@fixture(name="settings")
def fixture_settings() -> FakeSettings:
    """A fresh in-memory settings stand-in."""
    return FakeSettings()


def test_nothing_is_open_or_remembered_by_default() -> None:
    """A fresh install reopens nothing and offers no recents.

    **Test steps:**

    * build the settings with nothing loaded
    * verify no current path and no recents
    """
    rehuco = RehucoSettings()

    assert rehuco.current_path is None
    assert not rehuco.newest_first()


def test_the_recents_are_a_recent_files_list_under_this_sections_group() -> None:
    """The root catalogs' recents are the ``File`` menu's own list shape, under a group of their own, so the
    two never read each other's paths.

    **Test steps:**

    * read the composed list's group
    * verify it is this section's recents group
    """
    assert RehucoSettings().recent.group == RECENT_GROUP


def test_record_lists_the_newest_first_without_duplicates() -> None:
    """Re-recording a path moves it to the front rather than repeating it.

    **Test steps:**

    * record two paths, then the first again
    * verify the first leads and appears once
    """
    rehuco = RehucoSettings()
    rehuco.record(FIRST)
    rehuco.record(SECOND)
    rehuco.record(FIRST)

    assert rehuco.newest_first() == [FIRST, SECOND]


def test_record_drops_the_oldest_past_the_cap() -> None:
    """One more than the cap leaves the cap, without the first.

    **Test steps:**

    * record one path more than the cap allows
    * verify the count is the cap and the oldest is gone
    """
    rehuco = RehucoSettings()
    paths = [Path.cwd() / "fake" / f"{index}.rehuco" for index in range(MAXIMUM_RECENT_FILES + 1)]
    for path in paths:
        rehuco.record(path)

    remembered = rehuco.newest_first()

    assert len(remembered) == MAXIMUM_RECENT_FILES
    assert paths[0] not in remembered
    assert remembered[0] == paths[-1]


def test_save_then_load_round_trips_the_open_file_and_the_recents(settings: FakeSettings) -> None:
    """What was open at quit, and the order of what was opened, come back.

    **Test steps:**

    * save a current path and two recents
    * load into a fresh instance from the same stand-in
    * verify both came back, resolved
    """
    saved = RehucoSettings(current_path=SECOND)
    saved.record(FIRST)
    saved.record(SECOND)

    saved.save(settings)  # type: ignore[arg-type]
    restored = RehucoSettings()
    restored.load(settings)  # type: ignore[arg-type]

    assert restored.current_path == SECOND.resolve()
    assert restored.newest_first() == [SECOND.resolve(), FIRST.resolve()]


def test_a_closed_session_loads_as_nothing_open(settings: FakeSettings) -> None:
    """No file open at quit is stored as such, not as a stale path.

    **Test steps:**

    * save with no current path, then load over an instance that had one
    * verify the current path is cleared
    """
    RehucoSettings().save(settings)  # type: ignore[arg-type]
    restored = RehucoSettings(current_path=FIRST)

    restored.load(settings)  # type: ignore[arg-type]

    assert restored.current_path is None


def test_loading_replaces_what_was_there(settings: FakeSettings) -> None:
    """A load is a replacement, not a merge.

    **Test steps:**

    * save an empty state, record a path, then load
    * verify the recorded path is gone
    """
    RehucoSettings().save(settings)  # type: ignore[arg-type]
    rehuco = RehucoSettings()
    rehuco.record(FIRST)

    rehuco.load(settings)  # type: ignore[arg-type]

    assert not rehuco.newest_first()
