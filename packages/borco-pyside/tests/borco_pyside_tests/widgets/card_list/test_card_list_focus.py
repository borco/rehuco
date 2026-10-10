"""Tests for how a card list finds the widgets of its cards' tab order -- without touching any other widget's
wrapper (rehuco#487)."""

import shiboken6
from PySide6.QtCore import QEvent
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QApplication, QColumnView, QListView
from pytestqt.qtbot import QtBot

from .test_card_list_editor import Page, fixture_page  # noqa: F401  # pylint: disable=unused-import


def test_deleting_a_card_leaves_the_wrappers_of_widgets_outside_the_list_valid(
    page: Page,
    qtbot: QtBot,
) -> None:
    """A card list once walked the whole window's focus chain to find a card's widgets; ``nextInFocusChain()`` hangs
    each widget it hands back from the wrapper it was called on, so deleting a card invalidated the wrapper of every
    Qt-made widget in the window while the widgets lived on -- another dock's list columns raised *already deleted* at
    the next click.

    **Test steps:**

    * put a column view, whose columns Qt makes, in the card list's window, and hold its columns
    * insert a card -- the tab order is stitched again -- and delete it
    * verify every column's wrapper is still valid
    """
    model = QStandardItemModel()
    folder = QStandardItem("folder")
    folder.appendRow(QStandardItem("file"))
    model.appendRow(folder)
    view = QColumnView()
    view.setModel(model)
    window = page.editor.window()
    layout = window.layout()
    assert layout is not None
    layout.addWidget(view)
    view.show()
    view.setCurrentIndex(model.index(0, 0))
    qtbot.wait(20)
    columns = view.findChildren(QListView)
    assert columns

    page.model.insert(0)
    page.model.delete(0)
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    assert all(shiboken6.isValid(column) for column in columns)
