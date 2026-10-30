"""Tests for QtAdsTitleBarActionVisibility: a title-bar button is shown exactly while its action is (#572)."""

from collections.abc import Iterator
from typing import NamedTuple

import PySide6QtAds as QtAds
from borco_pyside.qtads import QtAdsTitleBarActionVisibility
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QLabel, QMainWindow, QToolButton
from pytest import fixture
from pytestqt.qtbot import QtBot


class Shell(NamedTuple):
    """A manager with two tabbed docks, the second carrying two title-bar actions, one of them hidden."""

    manager: QtAds.CDockManager
    other: QtAds.CDockWidget
    dock: QtAds.CDockWidget
    shown: QAction
    hidden: QAction


def button_of(dock: QtAds.CDockWidget, action: QAction) -> QToolButton | None:
    """The title-bar button carrying ``action``.

    :param dock: a placed dock.
    :param action: one of its title-bar actions.
    :returns: the button, or ``None`` while the title bar has none for it.
    """
    area = dock.dockAreaWidget()
    assert area is not None
    return next((b for b in area.titleBar().findChildren(QToolButton) if b.defaultAction() is action), None)


def button_shown(dock: QtAds.CDockWidget, action: QAction) -> bool:
    """Whether ``dock``'s title bar shows a button for ``action``.

    :param dock: a placed dock.
    :param action: one of its title-bar actions.
    :returns: whether the button is there and not hidden.
    """
    button = button_of(dock, action)
    return button is not None and not button.isHidden()


@fixture(name="shell")
def fixture_shell(qtbot: QtBot) -> Iterator[Shell]:
    """A shown window whose second dock, current, carries a shown and a hidden action with the helper on it.

    A generator fixture so the window lives for the whole test: ``qtbot.addWidget`` keeps only a weakref.
    """
    window = QMainWindow()
    qtbot.addWidget(window)
    window.resize(800, 600)
    window.show()
    manager = QtAds.CDockManager(window)
    other = QtAds.CDockWidget(manager, "Other")
    other.setWidget(QLabel("other"))
    manager.addDockWidget(QtAds.CenterDockWidgetArea, other)
    dock = QtAds.CDockWidget(manager, "Dock")
    dock.setWidget(QLabel("dock"))
    shown, hidden = QAction("Shown", window), QAction("Hidden", window)
    hidden.setVisible(False)
    dock.setTitleBarActions([shown, hidden])
    manager.addDockWidget(QtAds.CenterDockWidgetArea, dock, other.dockAreaWidget())
    QtAdsTitleBarActionVisibility(dock)
    dock.setAsCurrentTab()
    yield Shell(manager, other, dock, shown, hidden)


def test_a_hidden_action_has_no_visible_button_and_a_shown_one_has(shell: Shell) -> None:
    """**Test steps:**

    * build the shell with one action hidden
    * verify its button is hidden and the other's shown
    """
    assert button_shown(shell.dock, shell.shown) is True
    assert button_shown(shell.dock, shell.hidden) is False


def test_a_button_follows_its_action_as_it_changes(shell: Shell) -> None:
    """**Test steps:**

    * hide the shown action and show the hidden one
    * verify each button followed
    """
    shell.shown.setVisible(False)
    shell.hidden.setVisible(True)

    assert button_shown(shell.dock, shell.shown) is False
    assert button_shown(shell.dock, shell.hidden) is True


def test_buttons_built_again_for_a_dock_made_current_follow_their_actions(shell: Shell) -> None:
    """QtAds builds the buttons anew when the current dock changes; the new ones must start as their actions are.

    **Test steps:**

    * make the other dock current, then this one again
    * verify the hidden action's new button is hidden and the shown one's shown
    """
    shell.other.setAsCurrentTab()
    assert button_of(shell.dock, shell.hidden) is None

    shell.dock.setAsCurrentTab()

    assert button_shown(shell.dock, shell.shown) is True
    assert button_shown(shell.dock, shell.hidden) is False


def test_a_dock_in_no_area_is_left_alone(qtbot: QtBot) -> None:
    """**Test steps:**

    * build a dock that was never placed, with the helper on it
    * verify a sync raises nothing
    """
    window = QMainWindow()
    qtbot.addWidget(window)
    manager = QtAds.CDockManager(window)
    dock = QtAds.CDockWidget(manager, "Loose")
    action = QAction("Act", window)
    dock.setTitleBarActions([action])
    helper = QtAdsTitleBarActionVisibility(dock)

    action.setVisible(False)
    helper.sync()
