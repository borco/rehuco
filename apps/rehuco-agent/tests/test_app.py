"""Tests for QApplication wiring: single-instance guard and open-path routing."""

from types import SimpleNamespace
from typing import Final

from PySide6.QtGui import QFileOpenEvent
from pytest_mock import MockerFixture
from rehuco_agent.app import Application, run

FAKE_PATH: Final = "/fake/tutorials/sculpting/info.rehu"


def test_show_main_window_builds_it_once_and_reuses_it(mocker: MockerFixture) -> None:
    """``show_main_window`` builds the ``MainWindow`` on first call, then reuses that instance.

    Called as an unbound method against a lightweight stand-in for ``self`` for the same reason as
    the other tests in this file (see ``test_file_open_event_opens_a_path``'s docstring). Deferring
    construction past ``Application.__init__`` matters because a forwarding (non-primary) process
    must never build the real ``QMainWindow``-based dock shell -- see the class docstring.

    **Test steps:**

    * mock ``MainWindow`` and build a stand-in ``self`` with no main window yet
    * call ``show_main_window`` twice
    * verify ``MainWindow`` was constructed exactly once, both calls returned that same instance,
      and each call brought it to the foreground
    """
    window_cls = mocker.patch("rehuco_agent.app.MainWindow")
    fake_self = SimpleNamespace(_Application__main_window=None)

    first = Application.show_main_window(fake_self)  # type: ignore[arg-type]
    fake_self._Application__main_window = first  # pylint: disable=protected-access
    second = Application.show_main_window(fake_self)  # type: ignore[arg-type]

    window_cls.assert_called_once_with()
    assert first is second is window_cls.return_value
    assert window_cls.return_value.raise_and_activate.call_count == 2


def test_open_path_delegates_to_the_main_window(mocker: MockerFixture) -> None:
    """``open_path`` hands the path to the (single) main window's ``open_file``.

    Called as an unbound method against a lightweight stand-in for ``self``: Qt permits only one
    ``QApplication`` per process, and the test session's shared one may already be a plain
    ``QApplication`` built by another package's tests (collection order-dependent), so
    constructing a second real :class:`Application` here isn't reliable. ``open_path`` only calls
    ``self.show_main_window()``, so a stand-in with just that method is enough.

    **Test steps:**

    * build a stand-in ``self`` whose ``show_main_window`` returns a mocked main window
    * call ``Application.open_path`` with it
    * verify ``show_main_window`` was used to reach the window and ``open_file`` was called with the path
    """
    fake_main_window = mocker.MagicMock()
    fake_self = SimpleNamespace(show_main_window=mocker.MagicMock(return_value=fake_main_window))

    Application.open_path(fake_self, FAKE_PATH)  # type: ignore[arg-type]

    fake_main_window.open_file.assert_called_once_with(FAKE_PATH)


def test_file_open_event_opens_a_path(mocker: MockerFixture) -> None:
    """A ``QFileOpenEvent`` (macOS double-click delivery, [[nodes#single-instance]]) opens its path
    like a forwarded argv.

    Called as an unbound method against a stand-in ``self`` for the same reason as
    ``test_open_path_delegates_to_the_main_window`` above -- the ``isinstance(event, QFileOpenEvent)``
    branch never touches real ``QApplication`` state, so it doesn't need one.

    **Test steps:**

    * build a stand-in ``self`` with a mocked ``open_path``
    * dispatch a ``QFileOpenEvent`` for a path directly to ``Application.event``
    * verify the event was consumed (returns ``True``) and the path was opened
    """
    fake_self = SimpleNamespace(open_path=mocker.MagicMock())
    event = QFileOpenEvent(FAKE_PATH)

    assert Application.event(fake_self, event) is True  # type: ignore[arg-type]
    fake_self.open_path.assert_called_once_with(FAKE_PATH)


def test_run_forwards_when_not_primary(mocker: MockerFixture) -> None:
    """When another instance already owns the single-instance role, ``run`` returns immediately.

    **Test steps:**

    * mock ``Application`` and ``ApplicationSingleton`` so no real Qt objects are involved
    * make ``setup`` report this process is not primary
    * call ``run`` and verify it returns ``0`` without ever calling ``exec``
    """
    app_cls = mocker.patch("rehuco_agent.app.Application")
    singleton_cls = mocker.patch("rehuco_agent.app.ApplicationSingleton")
    singleton_cls.return_value.setup.return_value = False

    result = run(["rehuco-agent"])

    assert result == 0
    app_cls.return_value.exec.assert_not_called()


def test_run_opens_initial_paths_and_execs(mocker: MockerFixture) -> None:
    """When primary, ``run`` opens every argv path up front and starts the event loop.

    **Test steps:**

    * mock ``Application``/``ApplicationSingleton`` so no real Qt objects are involved
    * make ``setup`` report this process is primary
    * call ``run`` with two paths on argv
    * verify the main window was shown, both paths were opened, and ``exec``'s return value is propagated
    """
    app_cls = mocker.patch("rehuco_agent.app.Application")
    app_instance = app_cls.return_value
    app_instance.exec.return_value = 42
    singleton_cls = mocker.patch("rehuco_agent.app.ApplicationSingleton")
    singleton_cls.return_value.setup.return_value = True

    result = run(["rehuco-agent", "a.rehu", "b.rehu"])

    app_instance.show_main_window.assert_called_once_with()
    app_instance.open_path.assert_any_call("a.rehu")
    app_instance.open_path.assert_any_call("b.rehu")
    assert result == 42


def test_run_wires_forwarded_opens(mocker: MockerFixture) -> None:
    """A forwarded argv from a second instance opens each of its paths.

    **Test steps:**

    * mock ``Application``/``ApplicationSingleton``
    * capture the callback connected to ``other_instance_run``
    * invoke it directly with a forwarded path list
    * verify each path was opened
    """
    app_cls = mocker.patch("rehuco_agent.app.Application")
    app_instance = app_cls.return_value
    singleton_cls = mocker.patch("rehuco_agent.app.ApplicationSingleton")
    singleton = singleton_cls.return_value
    singleton.setup.return_value = True

    run(["rehuco-agent"])

    callback = singleton.other_instance_run.connect.call_args[0][0]
    callback(["c.rehu", "d.rehu"])  # pylint: disable=not-callable

    app_instance.open_path.assert_any_call("c.rehu")
    app_instance.open_path.assert_any_call("d.rehu")
