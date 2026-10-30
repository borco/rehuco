"""Tests for the holder of a player's engine, apart from the view that drives it (#319)."""

from unittest.mock import Mock

from PySide6.QtWidgets import QWidget
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents import player_engine
from rehuco_agent.documents.player_engine import PlayerEngine
from rehuco_agent.documents.vlc_surface import VlcSurface
from rehuco_agent.settings.videos_settings import VLC_PLAYER, shared_videos_settings


def holder(qtbot: QtBot) -> PlayerEngine:
    """An engine holder over an owner widget with both pages.

    :param qtbot: pytest-qt fixture.
    :returns: the holder.
    """
    owner = QWidget()
    qtbot.addWidget(owner)
    return PlayerEngine(owner, QWidget(owner), VlcSurface(owner))


def test_before_anything_is_built_there_is_nothing_to_drop_or_set(qtbot: QtBot) -> None:
    """**Test steps:**

    * drop and set the volume on a holder that built nothing
    * verify no engine, Qt's page as the surface, and nothing raised
    """
    engine = holder(qtbot)

    engine.drop()
    engine.set_volume(0.5)

    assert engine.player is None
    assert not engine.vlc
    assert engine.fallback_reason is None
    assert engine.surface is not None


def test_the_volume_reaches_whichever_engine_is_built(qtbot: QtBot, mocker: MockerFixture) -> None:
    """**Test steps:**

    * build Qt's engine with patched classes and set the volume; verify the audio output got it
    * choose VLC with a loaded library, build again and set the volume; verify the libvlc engine got it
    """
    audio = mocker.patch.object(player_engine, "QAudioOutput").return_value
    mocker.patch.object(player_engine, "QMediaPlayer")
    vlc_player = mocker.patch.object(player_engine, "VlcMediaPlayer").return_value
    library = Mock(available=True, reason=None)
    mocker.patch.object(player_engine, "shared_vlc_library", return_value=library)
    engine = holder(qtbot)

    engine.ensure(1.0, 1.0, lambda _player: None)
    engine.set_volume(0.25)
    audio.setVolume.assert_called_with(0.25)

    shared_videos_settings().player = VLC_PLAYER
    engine.ensure(1.0, 1.0, lambda _player: None)
    engine.set_volume(0.75)

    assert engine.vlc
    vlc_player.setVolume.assert_called_with(0.75)
    audio.deleteLater.assert_called_once_with()
