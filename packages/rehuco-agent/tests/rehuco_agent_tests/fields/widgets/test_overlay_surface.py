"""Tests for OverlaySurface's focus rule while its document is not on screen (#631)."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.widgets.overlay_surface import OverlayMode, OverlaySurface


def background_overlay(document: QWidget, qtbot: QtBot) -> OverlaySurface:
    """Reveal a document overlay, then put its document in the background, as a tab behind another is.

    :param document: the document stand-in.
    :param qtbot: pytest-qt fixture.
    :returns: the overlay: not visible, though never hidden itself.
    """
    overlay = OverlaySurface(OverlayMode.DOCUMENT_OVERLAY, document)
    qtbot.addWidget(overlay)
    overlay.reveal()
    assert overlay.hasFocus()
    document.hide()
    assert not overlay.isVisible()
    assert not overlay.isHidden()
    return overlay


def test_a_background_overlay_leaves_focus_on_its_container(document: QWidget, qtbot: QtBot) -> None:
    """Focus landing on a container of a background document stays there.

    Regression (#631): a document overlay whose tab was behind another took the keyboard back whenever focus landed on
    its containment line, becoming the app's focus widget while off screen; closing its document then freed it with
    the window still naming it, and the next layout pass crashed.

    **Test steps:**

    * reveal a document overlay, then hide its document as a background tab is hidden
    * focus the widget holding that document
    * verify the focus stays there
    """
    background_overlay(document, qtbot)
    container = document.parentWidget()
    assert container is not None
    container.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    container.setFocus()

    assert QApplication.focusWidget() is container


def test_a_background_overlay_does_not_take_back_focus_that_went_nowhere(document: QWidget, qtbot: QtBot) -> None:
    """Focus leaving a background overlay for nothing is not taken back.

    Regression (#631): hiding the document moves the keyboard off the overlay, and the overlay took it straight back
    while no longer on screen.

    **Test steps:**

    * reveal a document overlay, then hide its document as a background tab is hidden
    * clear the focus
    * verify nothing holds it, the overlay least of all
    """
    background_overlay(document, qtbot)
    focused = QApplication.focusWidget()
    if focused is not None:
        focused.clearFocus()

    assert QApplication.focusWidget() is None
