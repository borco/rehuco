"""Tests for the Roots model's freshness window: a listing is not asked for again while it is fresh (#487).

The window is a time stamp of the last answer compared at the next ask, so the clock here is moved by hand.
"""

from pathlib import Path

from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco.root_folder_loader import RootFolderLoader
from rehuco_agent.rehuco.roots_folder_model import NodeListing

from .test_roots_folder_model import (  # noqa: F401  # pylint: disable=unused-import
    child,
    library_fixture,
    make_model,
    make_root,
    open_folder,
)


class Clock:  # pylint: disable=too-few-public-methods
    """A clock the test moves by hand, standing in for ``time.monotonic``."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_a_listing_notes_when_it_landed_and_a_fresh_one_is_not_asked_again(
    qtbot: QtBot, library: Path, mocker: MockerFixture
) -> None:
    """The freshness window is a time stamp compared at the next ask: no timer runs (#487).

    **Test steps:**

    * list a folder on a clock held by hand
    * ask for it again within the window, and verify nothing is started
    * move the clock past the window, ask again, and verify one listing is started
    * ask with no window at all, as F5 does: verify it lists whatever the age
    """
    clock = Clock()
    mocker.patch("rehuco_agent.rehuco.roots_folder_model.time.monotonic", clock)
    model = make_model(qtbot, [make_root(library)])
    root = model.index(0, 0)
    folder = child(model, root, "alpha")
    open_folder(qtbot, model, folder)
    start = mocker.patch.object(RootFolderLoader, "start")

    assert not model.relist(folder, unless_listed_within=5.0)
    clock.now += 4.9
    assert not model.relist(folder, unless_listed_within=5.0)
    start.assert_not_called()

    clock.now += 0.2
    assert model.relist(folder, unless_listed_within=5.0)
    assert start.call_count == 1

    assert model.relist(folder)
    assert start.call_count == 2


def test_a_folder_whose_listing_is_still_out_is_not_asked_again_inside_the_window(
    qtbot: QtBot, library: Path, mocker: MockerFixture
) -> None:
    """A listing in flight counts as fresh: asking again would only start a second read of the same folder (#487).

    **Test steps:**

    * list a folder and let that listing go stale
    * ask for it again with no window, and hold the answer back
    * ask inside the window, and verify nothing more is started
    """
    clock = Clock()
    mocker.patch("rehuco_agent.rehuco.roots_folder_model.time.monotonic", clock)
    model = make_model(qtbot, [make_root(library)])
    root = model.index(0, 0)
    folder = child(model, root, "alpha")
    open_folder(qtbot, model, folder)
    clock.now += 60
    start = mocker.patch.object(RootFolderLoader, "start")
    assert model.relist(folder)
    assert model.listing_state(folder) is NodeListing.PENDING

    assert not model.relist(folder, unless_listed_within=5.0)

    assert start.call_count == 1


def test_an_unreachable_listing_is_noted_as_landed_too(qtbot: QtBot, tmp_path: Path, mocker: MockerFixture) -> None:
    """A folder that would not list is not asked again at once either: the answer was an answer (#487).

    **Test steps:**

    * show a root whose folder is not there, and wait for its listing
    * ask again inside the window, and verify nothing is started
    """
    model = make_model(qtbot, [make_root(tmp_path / "missing")])
    root = model.index(0, 0)
    assert model.listing_state(root) is NodeListing.UNREACHABLE
    start = mocker.patch.object(RootFolderLoader, "start")

    assert not model.relist(root, unless_listed_within=5.0)

    start.assert_not_called()
