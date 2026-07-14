"""pytest fixtures for borco_pyside.theming tests."""

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Final

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QAction, QFontDatabase
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot

REPO_ROOT_FONT: Final = Path(__file__).resolve().parents[4] / "design" / "fonts" / "Phosphor-Fill.ttf"
"""A real font file the repo already ships, used to test glyph rendering -- the offscreen test
platform has no real system fonts to look up by name (only a tofu-box fallback), but genuinely
renders a font explicitly loaded this way, same as the app does at startup (``app.py``). The
``-Fill`` (solid) weight specifically, not the outline default -- a test asserting a glyph's fill
color needs a genuinely solid shape, not an outline whose interior stays transparent."""


@fixture
def real_font_family(qtbot: QtBot) -> str:
    """Load :data:`REPO_ROOT_FONT` into the application font database, once per test.

    :param qtbot: pytest-qt bot, ensuring a QApplication exists.
    :returns: the loaded font's family name, ready to pass to :func:`~borco_pyside.theming.glyph_icon`.
    """
    del qtbot
    font_id = QFontDatabase.addApplicationFont(str(REPO_ROOT_FONT))
    families = QFontDatabase.applicationFontFamilies(font_id)
    assert families, f"failed to load test font from {REPO_ROOT_FONT}"
    return families[0]


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
def make_companion_action(qtbot: QtBot) -> Iterator[QAction]:
    """A second, independently torn-down `QAction`, for tests pairing two actions via
    `ActionIconThemeHandler`'s `companion` -- same reasoning as `make_action`.

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
