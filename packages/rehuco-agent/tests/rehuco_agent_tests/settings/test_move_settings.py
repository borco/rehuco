"""Tests for MoveSettings announcing a save (#649)."""

from unittest.mock import Mock

from PySide6.QtCore import QSettings
from pytestqt.qtbot import QtBot
from rehuco_agent.settings.move_settings import MoveSettings


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
