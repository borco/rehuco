"""Tests for qtads_utils.tab_label: a CDockWidget's own tab label widget."""

from collections.abc import Iterator

import PySide6QtAds as QtAds
from PySide6.QtCore import SignalInstance
from PySide6.QtWidgets import QWidget
from pytest import fixture
from pytestqt.qtbot import QtBot
from rehuco_agent.widgets.qtads_utils import tab_label


@fixture
def dock_widget(qtbot: QtBot) -> Iterator[QtAds.CDockWidget]:
    """A real `CDockWidget` placed in a real `CDockManager`, so its tab label actually exists.

    A generator fixture, not a plain ``return``: `CDockManager()` has no Qt parent, so Python is
    its sole owner -- `qtbot.addWidget` only keeps a `weakref` for teardown, not a strong
    reference, so a ``return``-based fixture would let ``manager`` be garbage-collected the
    moment this function returns, taking the dock it owns down with it. Pausing at ``yield``
    keeps ``manager`` alive in this (suspended) frame for the whole test.
    """
    manager = QtAds.CDockManager()
    qtbot.addWidget(manager)
    dock = QtAds.CDockWidget(manager, "Title")
    dock.setWidget(QWidget())
    manager.addDockWidget(QtAds.CenterDockWidgetArea, dock)
    yield dock


def test_tab_label_returns_the_docks_own_tab_label(dock_widget: QtAds.CDockWidget) -> None:
    """``tab_label`` returns the dock's own tab label, a real ``CElidingLabel``.

    **Test steps:**

    * call ``tab_label`` on a real dock
    * verify the result isn't ``None`` and is a ``CElidingLabel``
    """
    label = tab_label(dock_widget)

    assert label is not None
    assert isinstance(label, QtAds.CElidingLabel)


def test_double_clicking_the_tab_label_does_not_raise(dock_widget: QtAds.CDockWidget) -> None:
    """The returned label's ``doubleClicked`` is a real signal, and emitting it doesn't raise.

    **Test steps:**

    * call ``tab_label`` on a real dock
    * verify ``doubleClicked`` is a ``SignalInstance``
    * emit it and verify nothing raises
    """
    label = tab_label(dock_widget)
    assert isinstance(label.doubleClicked, SignalInstance)
    label.doubleClicked.emit()
