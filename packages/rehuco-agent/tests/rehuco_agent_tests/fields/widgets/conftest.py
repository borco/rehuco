"""Shared fixtures for the field toolkit's widget tests."""

from collections.abc import Iterator

from PySide6.QtWidgets import QMainWindow, QVBoxLayout, QWidget
from pytest import fixture
from pytestqt.qtbot import QtBot


@fixture
def document(qtbot: QtBot) -> Iterator[QWidget]:
    """A stand-in for the open document a maximized viewer belongs to, inside a main window's client area.

    Shaped like the real host chain -- a document widget nested in a `QMainWindow`'s central widget --
    so both overlay modes have a genuine surface to resolve and cover. Shared by the read-only viewer's
    tests and the curating one's (#370).

    A generator fixture, not a plain one: the window is a local, and yielding from inside the fixture
    is what keeps it alive for the test -- returning only its descendant would let Python collect the
    window, taking the document down with it.

    :param qtbot: pytest-qt fixture.
    :returns: the document stand-in, shown.
    """
    window = QMainWindow()
    central = QWidget()
    layout = QVBoxLayout(central)
    document = QWidget()
    layout.addWidget(document)
    window.setCentralWidget(central)
    qtbot.addWidget(window)
    window.resize(800, 600)
    window.show()
    qtbot.waitExposed(window)
    yield document
