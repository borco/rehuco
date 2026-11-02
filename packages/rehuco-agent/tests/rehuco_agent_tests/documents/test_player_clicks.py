"""Tests for what a click on the player's picture means: a press, a click or a double-click (#573, #574)."""

from dataclasses import dataclass
from typing import Final

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QLineEdit, QVBoxLayout, QWidget
from pytest import fixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.player_clicks import PlayerClicks

INTERVAL_MS: Final = 50
"""How long a click waits for a second one in these tests."""

PAST_INTERVAL_MS: Final = 3 * INTERVAL_MS


@dataclass(frozen=True)
class Stage:
    """A player stand-in: a holder that takes the focus, a surface in it that takes none, and a field beside it, in a
    window kept alive with them."""

    window: QWidget
    holder: QWidget
    surface: QWidget
    field: QLineEdit
    clicks: PlayerClicks


@fixture(name="stage")
def fixture_stage(qtbot: QtBot) -> Stage:
    """A shown, active window holding a field and a player stand-in, with the field focused.

    :param qtbot: pytest-qt fixture.
    :returns: the parts.
    """
    window = QWidget()
    qtbot.addWidget(window)
    layout = QVBoxLayout(window)
    field = QLineEdit(window)
    holder = QWidget(window)
    holder.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    holder.setMinimumSize(60, 60)
    surface = QWidget(holder)
    surface.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    surface.resize(40, 40)
    layout.addWidget(field)
    layout.addWidget(holder)
    clicks = PlayerClicks((surface,), INTERVAL_MS, holder)
    window.show()
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    field.setFocus()
    qtbot.waitUntil(field.hasFocus)
    return Stage(window, holder, surface, field, clicks)


def press(
    qtbot: QtBot,
    widget: QWidget,
    button: Qt.MouseButton = Qt.MouseButton.LeftButton,
    modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier,
) -> None:
    """Click as a user does, through the window, which gives the focus before the widget sees the press.

    :param qtbot: pytest-qt fixture.
    :param widget: what is clicked.
    :param button: the button.
    :param modifiers: the keys held.
    """
    qtbot.mousePress(widget, button, modifiers, QPoint(5, 5))
    qtbot.mouseRelease(widget, button, modifiers, QPoint(5, 5))


def double_press(widget: QWidget) -> None:
    """Deliver a left press as the one Qt pairs with the press before it: a double-click.

    :param widget: what is pressed.
    """
    point = QPointF(5, 5)
    left = Qt.MouseButton.LeftButton
    event = QMouseEvent(
        QEvent.Type.MouseButtonDblClick, point, widget.mapToGlobal(point), left, left, Qt.KeyboardModifier.NoModifier
    )
    QApplication.sendEvent(widget, event)


def test_a_click_that_brings_the_focus_is_a_click_after_the_interval(stage: Stage, qtbot: QtBot) -> None:
    """The picture has nothing a stray click could harm, so the click that focuses the player counts (#574, owner).

    **Test steps:**

    * with the field focused, press on the surface
    * verify the press was reported and the holder took the focus, with no click yet
    * verify a click came once the interval passed, and no double-click
    """
    clicked: list[bool] = []
    stage.clicks.clicked.connect(lambda: clicked.append(True))

    with qtbot.waitSignal(stage.clicks.pressed), qtbot.assertNotEmitted(stage.clicks.double_clicked):
        press(qtbot, stage.surface)
        assert stage.holder.hasFocus()
        assert not clicked
        qtbot.waitUntil(lambda: clicked == [True], timeout=PAST_INTERVAL_MS)


def test_two_presses_are_a_double_click_and_no_click(stage: Stage, qtbot: QtBot) -> None:
    """**Test steps:**

    * press twice, the second with Ctrl held, as plain presses
    * verify a double-click came with Ctrl, and no click followed
    """
    with qtbot.waitSignal(stage.clicks.double_clicked) as double:
        press(qtbot, stage.surface)
        press(qtbot, stage.surface, modifiers=Qt.KeyboardModifier.ControlModifier)

    assert double.args == [Qt.KeyboardModifier.ControlModifier]
    with qtbot.assertNotEmitted(stage.clicks.clicked, wait=PAST_INTERVAL_MS):
        pass


def test_a_press_qt_calls_a_double_click_counts_as_the_second_press(stage: Stage, qtbot: QtBot) -> None:
    """**Test steps:**

    * press, then press again as Qt delivers a second press within its interval
    * verify a double-click came, two presses were reported and no click came
    """
    presses: list[bool] = []
    stage.clicks.pressed.connect(lambda: presses.append(True))

    with qtbot.waitSignal(stage.clicks.double_clicked):
        press(qtbot, stage.surface)
        double_press(stage.surface)

    assert presses == [True, True]

    with qtbot.assertNotEmitted(stage.clicks.clicked, wait=PAST_INTERVAL_MS):
        pass


def test_a_third_press_within_the_interval_counts_for_nothing(stage: Stage, qtbot: QtBot) -> None:
    """A triple-click maximizes and does not also pause.

    **Test steps:**

    * double-click, then press once more within the interval
    * verify every press was reported, and neither a click nor a second double-click came, past the interval
    """
    with qtbot.waitSignal(stage.clicks.double_clicked):
        press(qtbot, stage.surface)
        press(qtbot, stage.surface)
    presses: list[bool] = []
    stage.clicks.pressed.connect(lambda: presses.append(True))

    with (
        qtbot.assertNotEmitted(stage.clicks.double_clicked),
        qtbot.assertNotEmitted(stage.clicks.clicked, wait=PAST_INTERVAL_MS),
    ):
        press(qtbot, stage.surface)
    assert presses == [True]


def test_a_press_after_the_interval_starts_a_new_count(stage: Stage, qtbot: QtBot) -> None:
    """**Test steps:**

    * double-click, let the interval pass, then press once more
    * verify the last press is a click of its own once the interval passed again
    """
    with qtbot.waitSignal(stage.clicks.double_clicked):
        press(qtbot, stage.surface)
        press(qtbot, stage.surface)
    qtbot.wait(PAST_INTERVAL_MS)

    with qtbot.waitSignal(stage.clicks.clicked, timeout=PAST_INTERVAL_MS):
        press(qtbot, stage.surface)


def test_a_right_press_counts_for_nothing(stage: Stage, qtbot: QtBot) -> None:
    """**Test steps:**

    * right-press the surface
    * verify nothing was reported
    """
    with (
        qtbot.assertNotEmitted(stage.clicks.pressed),
        qtbot.assertNotEmitted(stage.clicks.clicked, wait=PAST_INTERVAL_MS),
    ):
        press(qtbot, stage.surface, button=Qt.MouseButton.RightButton)
