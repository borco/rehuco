"""Tests for WaitingOverlay: what stands on a maximized view's surface while the view cannot be opened yet (#698)."""

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget
from pytest import fixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.waiting_overlay import WaitingOverlay
from rehuco_agent.fields.widgets.overlay_surface import OverlayMode


@fixture(name="overlay")
def fixture_overlay(qtbot: QtBot) -> WaitingOverlay:
    """A waiting overlay over a shown document.

    :param qtbot: pytest-qt fixture.
    :returns: the overlay, revealed.
    """
    document = QWidget()
    qtbot.addWidget(document)
    document.resize(400, 300)
    document.show()
    qtbot.waitExposed(document)
    overlay = WaitingOverlay(OverlayMode.DOCUMENT_OVERLAY, document)
    overlay.reveal()
    return overlay


def test_it_says_what_it_is_told_and_turns_only_while_busy(overlay: WaitingOverlay) -> None:
    """**Test steps:**

    * say something is being tried, and verify the words and the turning arc
    * say nothing is being tried any more, and verify the new words and the arc stopped
    """
    overlay.say("Restoring the player…", busy=True)

    assert overlay.text == "Restoring the player…"
    assert overlay.busy

    overlay.say("Its storage does not answer.", busy=False)

    assert overlay.text == "Its storage does not answer."
    assert not overlay.busy


def test_a_double_click_dismisses_it(overlay: WaitingOverlay, qtbot: QtBot) -> None:
    """The reader leaves a view being restored the way they leave a maximized player.

    **Test steps:**

    * double-click the overlay
    * verify it reported its dismissal and is no longer shown
    """
    with qtbot.waitSignal(overlay.closed):
        QTest.mouseDClick(overlay, Qt.MouseButton.LeftButton)

    assert not overlay.isVisible()


def test_escape_dismisses_it(overlay: WaitingOverlay, qtbot: QtBot) -> None:
    """**Test steps:**

    * press Esc on the overlay
    * verify it reported its dismissal
    """
    with qtbot.waitSignal(overlay.closed):
        qtbot.keyClick(overlay, Qt.Key.Key_Escape)

    assert not overlay.isVisible()
