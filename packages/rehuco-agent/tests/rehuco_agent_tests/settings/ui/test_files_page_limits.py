"""Tests for the Files page's bucket limits (#680, #681). :mod:`test_files_page`, whose fixtures are imported by name,
tests the rest of the page.
"""

from PySide6.QtWidgets import QSpinBox
from rehuco_agent.settings.move_settings import MoveSettings, shared_move_settings
from rehuco_agent.settings.ui.files_page import FilesPage
from rehuco_core import DEFAULT_JOIN_LIMIT, DEFAULT_SPLIT_LIMIT

from .test_files_page import (  # noqa: F401  # pylint: disable=unused-import
    FakeSettings,
    check_box,
    fixture_clear_shared_instance_cache,
    fixture_fake_persistent_settings,
    fixture_page,
)


def spin_box(page: FilesPage, name: str) -> QSpinBox:
    """One of the page's spin boxes, by object name.

    :param page: the page under test.
    :param name: the box's object name.
    :returns: the spin box.
    """
    box = page.findChild(QSpinBox, name)
    assert isinstance(box, QSpinBox)
    return box


def test_the_bucket_limits_start_as_shipped(page: FilesPage) -> None:
    """A fresh install splits above 200 and joins at 100.

    **Test steps:**

    * build the page over no saved settings
    * verify both values, and that the page is clean
    """
    split, join = spin_box(page, "split_limit_spin_box"), spin_box(page, "join_limit_spin_box")

    assert (split.value(), join.value()) == (DEFAULT_SPLIT_LIMIT, DEFAULT_JOIN_LIMIT)
    assert not page.is_dirty()


def test_a_join_limit_over_half_the_split_is_saved_as_entered(
    page: FilesPage, fake_persistent_settings: FakeSettings
) -> None:
    """It is ignored only where it is used (#681), so raising the split limit later brings it back.

    **Test steps:**

    * enter a join limit over half the split limit, and save
    * verify the page is clean, still showing it, and a reload holds it
    """
    join = spin_box(page, "join_limit_spin_box")
    join.setValue(DEFAULT_SPLIT_LIMIT)

    page.save_changes()

    assert not page.is_dirty()
    assert join.value() == DEFAULT_SPLIT_LIMIT
    reloaded = MoveSettings()
    reloaded.load(fake_persistent_settings)  # type: ignore[arg-type]
    assert reloaded.join_limit == DEFAULT_SPLIT_LIMIT


def test_limits_saved_elsewhere_are_shown(page: FilesPage, fake_persistent_settings: FakeSettings) -> None:
    """The balance dialog saves the same limits (#681): the page shows them, rather than hold the old ones as a change
    *Apply changes as they're made* would write back. What else is staged stays.

    **Test steps:**

    * stage another choice, and save other limits through the shared settings
    * verify the page shows them, and that choice still staged
    """
    page_box = check_box(page, "remove_empty_folders_check_box")
    page_box.toggle()
    staged = page_box.isChecked()
    moves = shared_move_settings()
    moves.split_limit, moves.join_limit = 500, 150

    moves.save(fake_persistent_settings)  # type: ignore[arg-type]

    assert spin_box(page, "split_limit_spin_box").value() == 500
    assert spin_box(page, "join_limit_spin_box").value() == 150
    assert page_box.isChecked() is staged
    assert page.is_dirty()
    page_box.toggle()
    assert not page.is_dirty()


def test_limits_staged_here_stay_when_others_are_saved(page: FilesPage, fake_persistent_settings: FakeSettings) -> None:
    """A balance started while the page holds limits not applied yet leaves them staged (#681).

    **Test steps:**

    * stage a limit, and save the shared settings as the balance dialog does
    * verify the staged limit is still there, and Reset shows the saved ones
    """
    split = spin_box(page, "split_limit_spin_box")
    split.setValue(500)

    moves = shared_move_settings()
    moves.split_limit = 300
    moves.save(fake_persistent_settings)  # type: ignore[arg-type]

    assert split.value() == 500
    assert page.is_dirty()
    page.drop_changes()
    assert split.value() == 300
    assert not page.is_dirty()


def test_the_bucket_limits_are_staged_saved_and_dropped(
    page: FilesPage, fake_persistent_settings: FakeSettings
) -> None:
    """A changed limit makes the page dirty; Reset drops it, Apply saves and persists both.

    **Test steps:**

    * change the split limit, check the page is dirty, reset, and check it is back and clean
    * change both, apply, and check the shared settings and a reload hold them
    * seed the defaults and check both are back, the page dirty
    """
    split, join = spin_box(page, "split_limit_spin_box"), spin_box(page, "join_limit_spin_box")
    split.setValue(500)
    assert page.is_dirty()
    page.drop_changes()
    assert split.value() == DEFAULT_SPLIT_LIMIT
    assert not page.is_dirty()

    split.setValue(500)
    join.setValue(150)
    page.save_changes()

    assert (shared_move_settings().split_limit, shared_move_settings().join_limit) == (500, 150)
    reloaded = MoveSettings()
    reloaded.load(fake_persistent_settings)  # type: ignore[arg-type]
    assert (reloaded.split_limit, reloaded.join_limit) == (500, 150)

    page.seed_defaults()
    assert (split.value(), join.value()) == (DEFAULT_SPLIT_LIMIT, DEFAULT_JOIN_LIMIT)
    assert page.is_dirty()
