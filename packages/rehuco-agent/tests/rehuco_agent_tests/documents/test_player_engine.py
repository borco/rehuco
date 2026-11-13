"""Tests for the holder of a player's engine, apart from the view that drives it (#319)."""

from unittest.mock import Mock

from PySide6.QtMultimedia import QMediaPlayer, QVideoSink
from PySide6.QtWidgets import QWidget
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents import player_engine
from rehuco_agent.documents.player_engine import PlayerEngine
from rehuco_agent.documents.vlc_surface import VlcSurface
from rehuco_agent.settings.videos_settings import VLC_PLAYER, shared_videos_settings


def holder(qtbot: QtBot, sink: QVideoSink | None = None) -> PlayerEngine:
    """An engine holder over an owner widget with both pages.

    :param qtbot: pytest-qt fixture.
    :param sink: where Qt's player is to decode into; one of the owner's when ``None``.
    :returns: the holder.
    """
    owner = QWidget()
    qtbot.addWidget(owner)
    return PlayerEngine(owner, QWidget(owner), VlcSurface(owner), sink if sink is not None else QVideoSink(owner))


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
    # the player answers the output it was given, as a real one does
    mocker.patch.object(player_engine, "QMediaPlayer").return_value.audioOutput.return_value = audio
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


def test_qts_engine_stands_in_until_vlc_can_be_used(qtbot: QtBot, mocker: MockerFixture) -> None:
    """A new ``QAudioOutput`` at every video would be one more chance each time for Qt Multimedia's own thread to
    wait for the GIL under a signal-slot mutex (#654).

    **Test steps:**

    * choose VLC with the library unavailable and ask for the engine twice, the reason changing in between
    * verify one Qt player and one audio output were built, connected once, with the later reason
    * make the library available and ask again
    * verify the libvlc engine took over, connected, with no reason left, and Qt's player and output were deleted
    """
    audio_class = mocker.patch.object(player_engine, "QAudioOutput")
    audio = audio_class.return_value
    qt_class = mocker.patch.object(player_engine, "QMediaPlayer")
    qt_player = qt_class.return_value
    # the player answers the output it was given, as a real one does
    qt_player.audioOutput.return_value = audio
    vlc_player = mocker.patch.object(player_engine, "VlcMediaPlayer").return_value
    library = Mock(available=False, reason="No VLC is set up on the Tools page.")
    mocker.patch.object(player_engine, "shared_vlc_library", return_value=library)
    shared_videos_settings().player = VLC_PLAYER
    connect = Mock()
    engine = holder(qtbot)

    first = engine.ensure(1.0, 1.0, connect)
    library.reason = "The VLC on the Tools page is gone."
    second = engine.ensure(1.0, 1.0, connect)

    assert first is qt_player
    assert second is qt_player
    assert not engine.vlc
    assert engine.fallback_reason == "The VLC on the Tools page is gone."
    qt_class.assert_called_once()
    audio_class.assert_called_once()
    connect.assert_called_once_with(qt_player)
    audio.deleteLater.assert_not_called()

    library.available = True
    library.reason = None
    third = engine.ensure(0.5, 2.0, connect)

    assert third is vlc_player
    assert engine.player is vlc_player
    assert engine.vlc
    assert engine.fallback_reason is None
    vlc_player.setVolume.assert_called_once_with(0.5)
    vlc_player.setPlaybackRate.assert_called_once_with(2.0)
    connect.assert_called_with(vlc_player)
    audio.deleteLater.assert_called_once_with()
    qt_player.deleteLater.assert_called_once_with()


def test_qts_player_decodes_into_the_sink_it_was_given(qtbot: QtBot) -> None:
    """The view hands the frames on from there, so a pause can hold the last one on the video widget (#574).

    **Test steps:**

    * build Qt's engine over a sink
    * verify the player decodes into that sink
    """
    sink = QVideoSink()
    engine = holder(qtbot, sink)

    player = engine.ensure(1.0, 1.0, lambda _player: None)

    assert isinstance(player, QMediaPlayer)
    assert player.videoSink() is sink
    engine.drop()
