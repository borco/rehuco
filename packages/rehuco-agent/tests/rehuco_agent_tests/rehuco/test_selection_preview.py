"""Tests for SelectionPreview: a selection is shown once it settles, resolved by the catalog, and a selection that is
nothing calls off one still waiting (#381)."""

from pathlib import Path
from typing import Final
from unittest.mock import MagicMock
from uuid import UUID, uuid4

from pytest import MonkeyPatch, fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco import selection_preview
from rehuco_agent.rehuco.selection_preview import SelectionPreview

ROOT_ID: Final = uuid4()
SETTLE_MS: Final = 20
"""A settle short enough to wait out in a test; the real one is :data:`~selection_preview.SELECTION_SETTLE_MS`."""
WAIT_MS: Final = SETTLE_MS * 6


def path_of(relative: str) -> Path:
    """Where a test resource lives.

    :param relative: its path below the root.
    :returns: the resolved path.
    """
    return Path("/fake/root") / relative


@fixture(name="catalog")
def fixture_catalog(mocker: MockerFixture) -> MagicMock:
    """A stand-in catalog resolving every key under one root, and no other."""
    catalog = mocker.MagicMock()
    catalog.resource_path.side_effect = lambda root_id, relative: path_of(relative) if root_id == ROOT_ID else None
    return catalog


@fixture(name="shown")
def fixture_shown(mocker: MockerFixture) -> MagicMock:
    """What the preview is asked to show."""
    return mocker.MagicMock()


@fixture(name="selection")
def fixture_selection(qtbot: QtBot, monkeypatch: MonkeyPatch, catalog: MagicMock, shown: MagicMock) -> SelectionPreview:
    """A preview driver with a short settle, over the stand-in catalog."""
    del qtbot
    monkeypatch.setattr(selection_preview, "SELECTION_SETTLE_MS", SETTLE_MS)
    return SelectionPreview(catalog, shown)


def test_a_selection_is_shown_once_it_has_settled(qtbot: QtBot, selection: SelectionPreview, shown: MagicMock) -> None:
    """Nothing is shown while a selection is new, and the resource it names is shown when it has stood.

    **Test steps:**

    * select a resource and look at once
    * wait for the settle
    * verify nothing was shown at first, and then the resolved path, once
    """
    selection.select((ROOT_ID, "a/info.rehu"))

    shown.assert_not_called()
    qtbot.waitUntil(lambda: shown.call_count == 1)
    shown.assert_called_once_with(path_of("a/info.rehu"))


def test_moving_through_rows_shows_only_the_one_it_rests_on(
    qtbot: QtBot, selection: SelectionPreview, shown: MagicMock
) -> None:
    """Rows passed in quick succession -- the arrow keys held down -- load nothing: one document per settled
    selection.

    **Test steps:**

    * select three resources one after another, faster than the settle
    * wait out the settle
    * verify only the last was shown
    """
    for relative in ("a/info.rehu", "b/info.rehu", "c/info.rehu"):
        selection.select((ROOT_ID, relative))

    qtbot.wait(WAIT_MS)

    shown.assert_called_once_with(path_of("c/info.rehu"))


def test_selecting_nothing_calls_off_a_selection_still_waiting(
    qtbot: QtBot, selection: SelectionPreview, shown: MagicMock
) -> None:
    """No row, several rows, a table a scan reset: none of them is a new resource, and a selection still waiting
    when one arrives is not shown.

    **Test steps:**

    * select a resource, then select nothing before it settles
    * wait out the settle
    * verify nothing was shown
    """
    selection.select((ROOT_ID, "a/info.rehu"))
    selection.select(None)

    qtbot.wait(WAIT_MS)

    shown.assert_not_called()


def test_a_resource_is_resolved_when_it_settles(
    qtbot: QtBot, selection: SelectionPreview, catalog: MagicMock, shown: MagicMock
) -> None:
    """The key is read when the selection settles, not when it is made, so a root removed in between is not shown.

    **Test steps:**

    * select a resource, then have the catalog lose its root
    * wait out the settle
    * verify the catalog was asked once, after the selection, and nothing was shown
    """
    selection.select((ROOT_ID, "a/info.rehu"))
    catalog.resource_path.assert_not_called()
    catalog.resource_path.side_effect = None
    catalog.resource_path.return_value = None

    qtbot.wait(WAIT_MS)

    catalog.resource_path.assert_called_once_with(ROOT_ID, "a/info.rehu")
    shown.assert_not_called()


def test_a_root_the_catalog_does_not_list_shows_nothing(
    qtbot: QtBot, selection: SelectionPreview, shown: MagicMock
) -> None:
    """A key under a root the catalog does not know has no path, so there is nothing to show.

    **Test steps:**

    * select a resource under an unknown root and wait out the settle
    * verify nothing was shown
    """
    unknown: UUID = uuid4()

    selection.select((unknown, "a/info.rehu"))
    qtbot.wait(WAIT_MS)

    shown.assert_not_called()
