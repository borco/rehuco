"""pytest fixtures for borco_pyside.theming tests."""

from collections.abc import Callable, Iterator
from typing import Any

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QAction
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot


@fixture
def make_action(qtbot: QtBot) -> Iterator[QAction]:
    """Provide a `QAction` that is explicitly torn down, rather than left for cyclic GC.

    `ActionIconThemeHandler`/`ThemeManager` connect a bound method to the action's own signals,
    forming a reference cycle (action -> connection -> handler -> action) that only Python's
    cyclic garbage collector would otherwise break -- and PySide6/shiboken objects are not safe to
    collect that way (confirmed: an explicit `gc.collect()` segfaulted while finalizing one).
    Deleting the action directly and draining its `DeferredDelete` event breaks the cycle
    deterministically instead, the same way `conftest.py`'s `make_singleton` does at the repo root.

    :param qtbot: pytest-qt bot, ensuring a QApplication exists and draining events on teardown.
    :returns: a fresh `QAction`.
    """
    action = QAction()
    yield action
    action.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    qtbot.wait(10)


@fixture
def mock_qfile(mocker: MockerFixture) -> Callable[..., Any]:
    """Provide a factory that patches `QFile` in `action_icon_theme_handler`, avoiding disk I/O.

    :param mocker: pytest-mock fixture.
    :returns: a factory ``(data: bytes, *, open_ok: bool = True) -> MagicMock`` -- each call
        patches `QFile` to construct a mock that reads `data` (or fails to open, if `open_ok` is
        ``False``), and returns that mock.
    """

    def factory(data: bytes, *, open_ok: bool = True) -> Any:
        file_mock = mocker.MagicMock()
        file_mock.open.return_value = open_ok
        file_mock.readAll.return_value.data.return_value = data
        mocker.patch("borco_pyside.theming.action_icon_theme_handler.QFile", return_value=file_mock)
        return file_mock

    return factory
