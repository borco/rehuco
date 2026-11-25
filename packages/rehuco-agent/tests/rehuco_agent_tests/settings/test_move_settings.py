"""Tests for MoveSettings announcing a save (#649), and its bucket limits (#680, #681)."""

from unittest.mock import Mock

from PySide6.QtCore import QSettings
from pytest import mark, param
from pytestqt.qtbot import QtBot
from rehuco_agent.settings.move_settings import MoveSettings
from rehuco_core import DEFAULT_JOIN_LIMIT, DEFAULT_SPLIT_LIMIT, MAX_SPLIT_LIMIT, MIN_SPLIT_LIMIT, max_join_limit


def test_saving_announces_a_change(qtbot: QtBot) -> None:
    """The path row marks a move by these settings, so a save tells it to redraw.

    **Test steps:**

    * change a box and save into a stand-in store
    * verify ``changed`` fired once, and the store was written
    """
    settings = MoveSettings()
    store = Mock(spec=QSettings)
    settings.verify_renamed_local = True

    with qtbot.waitSignal(settings.changed, timeout=1000):
        settings.save(store)

    store.setValue.assert_any_call("verify_renamed_local", True)


def test_loading_announces_nothing(qtbot: QtBot) -> None:
    """Loading is what the shared instance does once, before anything draws from it: it announces no change.

    **Test steps:**

    * load from a stand-in store that holds the factory values
    * verify ``changed`` did not fire
    """
    settings = MoveSettings()
    store = Mock(spec=QSettings)
    store.value.side_effect = lambda _key, default, **_: default

    with qtbot.assertNotEmitted(settings.changed):
        settings.load(store)


def stored(values: dict[str, object]) -> Mock:
    """A stand-in store holding ``values`` and the factory values for every other key.

    :param values: what it holds, by key.
    :returns: the store.
    """
    store = Mock(spec=QSettings)
    store.value.side_effect = lambda key, default, **_: values.get(key, default)
    return store


def test_the_bucket_limits_round_trip_and_ship_at_200_and_100() -> None:
    """A fresh object holds the shipped limits, and what is saved loads back (#680).

    **Test steps:**

    * read a fresh object's limits, then load a store holding 500 and 150
    * verify the shipped pair, then the stored pair
    """
    settings = MoveSettings()
    assert (settings.split_limit, settings.join_limit) == (DEFAULT_SPLIT_LIMIT, DEFAULT_JOIN_LIMIT)

    settings.load(stored({"split_limit": "500", "join_limit": 150}))

    assert (settings.split_limit, settings.join_limit) == (500, 150)


@mark.parametrize(
    "values, expected",
    [
        param({"split_limit": 10}, (MIN_SPLIT_LIMIT, DEFAULT_JOIN_LIMIT), id="a-split-under-its-floor"),
        param({"join_limit": 150}, (DEFAULT_SPLIT_LIMIT, 150), id="a-join-over-half-kept-as-entered"),
        param({"join_limit": -5}, (DEFAULT_SPLIT_LIMIT, 0), id="a-join-under-zero"),
        param(
            {"join_limit": 2 * MAX_SPLIT_LIMIT},
            (DEFAULT_SPLIT_LIMIT, max_join_limit(MAX_SPLIT_LIMIT)),
            id="a-join-over-every-split",
        ),
        param({"split_limit": "many", "join_limit": None}, (DEFAULT_SPLIT_LIMIT, DEFAULT_JOIN_LIMIT), id="no-numbers"),
    ],
)
def test_stored_bucket_limits_are_kept_within_what_their_boxes_take(
    values: dict[str, object], expected: tuple[int, int]
) -> None:
    """A split limit under 50, a join limit under 0 or over any split's half, or a value that is no number loads as one
    the box takes (#680); a join limit over half the split limit is kept as entered, and ignored only where it is used
    (#681).

    **Test steps:**

    * load each store
    * verify the limits
    """
    settings = MoveSettings()

    settings.load(stored(values))

    assert (settings.split_limit, settings.join_limit) == expected
