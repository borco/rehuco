"""Tests for QApplication wiring: single-instance guard and open-path routing."""

import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Final
from unittest.mock import MagicMock

from PySide6.QtGui import QFileOpenEvent, QGuiApplication
from pytest import LogCaptureFixture, fixture, raises
from pytest_mock import MockerFixture
from rehuco_agent.app import APP_ID, Application, leave_launch_directory, run
from rehuco_agent.linux_registration import DESKTOP_FILE_NAME
from rehuco_agent.settings.persistent_settings import STAGED_IMAGES_MAX_AGE, staging_folder

FAKE_PATH: Final = "/fake/tutorials/sculpting/info.rehu"
FAKE_HOME: Final = Path("/fake/home")


@fixture(autouse=True)
def chdir(mocker: MockerFixture) -> MagicMock:
    """Stand in for ``os.chdir``, so ``run`` leaving its launch directory (#355) never moves the test
    process itself -- path-resolving fixtures elsewhere depend on the suite's working directory.

    :returns: the stand-in.
    """
    return mocker.patch("rehuco_agent.app.os.chdir")


@fixture(autouse=True)
def run_log(mocker: MockerFixture) -> MagicMock:
    """Stand in for the shared `~rehuco_agent.run_log.RunLog`, so ``run`` never installs real
    excepthooks/a Qt message handler or writes under the fake config folder these tests otherwise
    only ever *read* from (#362) -- exactly what ``test_run_log.py`` exercises for real.

    :returns: the stand-in.
    """
    return mocker.patch("rehuco_agent.app.shared_run_log").return_value


def test_leaving_the_launch_directory_goes_home(chdir: MagicMock, mocker: MockerFixture) -> None:
    """The app steps out of the folder Explorer started it in, which it would otherwise hold against a
    rename for its whole life (#355).

    **Test steps:**

    * point the home directory at a fake path
    * leave the launch directory
    * verify the working directory was changed to home
    """
    mocker.patch.object(Path, "home", return_value=FAKE_HOME)

    leave_launch_directory()

    chdir.assert_called_once_with(FAKE_HOME)


def test_failing_to_leave_the_launch_directory_is_logged_not_raised(
    chdir: MagicMock, mocker: MockerFixture, caplog: LogCaptureFixture
) -> None:
    """Staying put costs a rename later, which then says why -- no reason not to start (#355).

    **Test steps:**

    * make changing directory fail, then make resolving home fail
    * leave the launch directory each time
    * verify neither raised, and each logged a warning
    """
    chdir.side_effect = OSError("gone")
    with caplog.at_level(logging.WARNING, logger="rehuco_agent.app"):
        leave_launch_directory()
        mocker.patch.object(Path, "home", side_effect=RuntimeError("no home"))
        leave_launch_directory()

    assert len(caplog.records) == 2


def test_run_leaves_the_launch_directory(chdir: MagicMock, mocker: MockerFixture) -> None:
    """Every launch leaves the directory it was started in (#355), and a relative argv path is still
    handed on resolved against that directory (#297).

    **Test steps:**

    * mock ``Application``/``ApplicationSingleton``
    * call ``run`` with a relative path
    * verify the directory changed once, and ``setup`` got the path resolved against the launch directory
    """
    mocker.patch("rehuco_agent.app.Application")
    singleton_cls = mocker.patch("rehuco_agent.app.ApplicationSingleton")
    singleton_cls.return_value.setup.return_value = True
    resolved = str(Path("sub/a.rehu").resolve())

    run(["rehuco-agent", "sub/a.rehu"])

    chdir.assert_called_once()
    singleton_cls.return_value.setup.assert_called_once_with(APP_ID, [resolved])


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
    """``open_path`` hands the path to the (single) main window's ``open_path``, which does the
    file-vs-folder dispatch (#43).

    Called as an unbound method against a lightweight stand-in for ``self``: Qt permits only one
    ``QApplication`` per process, and the test session's shared one may already be a plain
    ``QApplication`` built by another package's tests (collection order-dependent), so
    constructing a second real :class:`Application` here isn't reliable. ``open_path`` only calls
    ``self.show_main_window()``, so a stand-in with just that method is enough.

    **Test steps:**

    * build a stand-in ``self`` whose ``show_main_window`` returns a mocked main window
    * call ``Application.open_path`` with it
    * verify ``show_main_window`` was used to reach the window and ``open_path`` was called with it
    """
    fake_main_window = mocker.MagicMock()
    fake_self = SimpleNamespace(show_main_window=mocker.MagicMock(return_value=fake_main_window))

    Application.open_path(fake_self, FAKE_PATH)  # type: ignore[arg-type]

    fake_main_window.open_path.assert_called_once_with(FAKE_PATH)


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
    """When another instance already owns the single-instance role, ``run`` returns immediately --
    and what it forwarded is its own ``argv`` parameter's paths, resolved against *this* process's
    cwd (#297), not the process's real command line, which ``setup``'s ``sys.argv[1:]`` default
    would silently substitute.

    **Test steps:**

    * mock ``Application`` and ``ApplicationSingleton`` so no real Qt objects are involved
    * make ``setup`` report this process is not primary
    * call ``run`` with one path and verify it returns ``0`` without ever calling ``exec``
    * verify ``setup`` was handed that path's resolved (absolute) form
    """
    app_cls = mocker.patch("rehuco_agent.app.Application")
    singleton_cls = mocker.patch("rehuco_agent.app.ApplicationSingleton")
    singleton = singleton_cls.return_value
    singleton.setup.return_value = False

    result = run(["rehuco-agent", "a.rehu"])

    assert result == 0
    app_cls.return_value.exec.assert_not_called()
    singleton.setup.assert_called_once_with(APP_ID, [str(Path("a.rehu").resolve())])


def test_run_starts_the_run_log_before_building_the_application(mocker: MockerFixture, run_log: MagicMock) -> None:
    """The run log starts before anything worth keeping happens, including building the
    `QApplication` itself -- a failure that early is still in the file (#362).

    **Test steps:**

    * mock ``Application``/``ApplicationSingleton``
    * call ``run``
    * verify ``start`` ran, and before ``Application`` was ever constructed
    """
    app_cls = mocker.patch("rehuco_agent.app.Application")
    singleton_cls = mocker.patch("rehuco_agent.app.ApplicationSingleton")
    singleton_cls.return_value.setup.return_value = False
    order: list[str] = []
    run_log.start.side_effect = lambda argv: order.append("start")  # noqa: ARG005
    app_cls.side_effect = lambda argv: order.append("Application") or mocker.MagicMock()  # noqa: ARG005

    run(["rehuco-agent"])

    assert order == ["start", "Application"]


def test_run_marks_a_forwarder_and_never_becomes_primary(mocker: MockerFixture, run_log: MagicMock) -> None:
    """A process that forwards its argv to an existing primary is a forwarder for its whole (short)
    life, and never rotates the file or touches the sentinel.

    **Test steps:**

    * make ``setup`` report this process is not primary
    * call ``run``
    * verify ``become_forwarder`` ran and ``become_primary``/``watch`` never did
    """
    mocker.patch("rehuco_agent.app.Application")
    singleton_cls = mocker.patch("rehuco_agent.app.ApplicationSingleton")
    singleton_cls.return_value.setup.return_value = False

    run(["rehuco-agent"])

    run_log.become_forwarder.assert_called_once_with()
    run_log.become_primary.assert_not_called()
    run_log.watch.assert_not_called()


def test_only_the_primary_prunes_the_staged_images(mocker: MockerFixture, run_log: MagicMock) -> None:
    """The images staged for other apps are pruned once per start, by the process that stays (#395): a forwarding
    launch must not delete what the running one has just staged.

    **Test steps:**

    * run as a forwarder, then as the primary, with the prune watched
    * verify it ran once, over the staging folder with the seven-day age
    """
    del run_log
    mocker.patch("rehuco_agent.app.Application")
    singleton_cls = mocker.patch("rehuco_agent.app.ApplicationSingleton")
    prune = mocker.patch("rehuco_agent.app.prune_staged")

    singleton_cls.return_value.setup.return_value = False
    run(["rehuco-agent"])
    prune.assert_not_called()
    singleton_cls.return_value.setup.return_value = True
    run(["rehuco-agent"])

    prune.assert_called_once()
    folder, age, _now = prune.call_args.args
    assert folder == staging_folder()
    assert age == STAGED_IMAGES_MAX_AGE


def test_run_marks_the_primary_and_watches_the_application(mocker: MockerFixture, run_log: MagicMock) -> None:
    """The process that wins the single-instance role becomes the run log's primary, and is watched
    for how its `QGuiApplication` shuts down.

    **Test steps:**

    * make ``setup`` report this process is primary
    * call ``run``
    * verify ``become_primary`` ran, and ``watch`` was handed the built ``Application``
    """
    app_cls = mocker.patch("rehuco_agent.app.Application")
    singleton_cls = mocker.patch("rehuco_agent.app.ApplicationSingleton")
    singleton_cls.return_value.setup.return_value = True

    run(["rehuco-agent"])

    run_log.become_primary.assert_called_once_with()
    run_log.watch.assert_called_once_with(app_cls.return_value)


def test_run_finishes_the_run_log_with_execs_return_value(mocker: MockerFixture, run_log: MagicMock) -> None:
    """The exit code ``run`` itself returns is what ``finish`` is told, whichever role this process
    played.

    **Test steps:**

    * make ``exec`` return a code
    * call ``run``
    * verify ``finish`` was called with that same code
    """
    app_cls = mocker.patch("rehuco_agent.app.Application")
    app_cls.return_value.exec.return_value = 42
    singleton_cls = mocker.patch("rehuco_agent.app.ApplicationSingleton")
    singleton_cls.return_value.setup.return_value = True

    result = run(["rehuco-agent"])

    assert result == 42
    run_log.finish.assert_called_once_with(42)


def test_run_logs_and_reraises_an_exception_from_exec(mocker: MockerFixture, run_log: MagicMock) -> None:
    """An exception that escapes ``app.exec()`` is logged before it propagates, and ``finish`` still
    runs -- with no exit code, since none was ever produced.

    **Test steps:**

    * make ``exec`` raise
    * call ``run``
    * verify the exception was logged, re-raised, and ``finish`` was called with ``None``
    """
    error = RuntimeError("boom")
    app_cls = mocker.patch("rehuco_agent.app.Application")
    app_cls.return_value.exec.side_effect = error
    singleton_cls = mocker.patch("rehuco_agent.app.ApplicationSingleton")
    singleton_cls.return_value.setup.return_value = True

    with raises(RuntimeError):
        run(["rehuco-agent"])

    run_log.log_exception.assert_called_once_with(error, "app.exec()")
    run_log.finish.assert_called_once_with(None)


def test_run_resolves_a_relative_path_against_this_processs_cwd(mocker: MockerFixture) -> None:
    """A relative argv path is resolved to absolute *before* it can cross the process boundary --
    forwarded to a running primary, or opened by this process itself -- so a running primary's own
    cwd never enters into it (#297).

    **Test steps:**

    * mock ``Application``/``ApplicationSingleton`` so no real Qt objects are involved
    * make ``setup`` report this process is primary
    * call ``run`` with one relative path
    * verify both ``setup`` and the initial open were handed the path resolved against this
      process's actual cwd, not the raw relative string
    """
    app_cls = mocker.patch("rehuco_agent.app.Application")
    app_instance = app_cls.return_value
    singleton_cls = mocker.patch("rehuco_agent.app.ApplicationSingleton")
    singleton = singleton_cls.return_value
    singleton.setup.return_value = True

    run(["rehuco-agent", "sub/a.rehu"])

    resolved = str(Path("sub/a.rehu").resolve())
    singleton.setup.assert_called_once_with(APP_ID, [resolved])
    app_instance.open_path.assert_any_call(resolved)


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
    app_instance.open_path.assert_any_call(str(Path("a.rehu").resolve()))
    app_instance.open_path.assert_any_call(str(Path("b.rehu").resolve()))
    assert result == 42


def test_run_declares_the_desktop_file_name(mocker: MockerFixture) -> None:
    """``run`` names this process's desktop entry, which is what gives its windows an identity on
    Linux -- the Wayland ``app_id`` and X11 ``StartupWMClass`` (#209).

    Asserted against Qt's own state rather than a mocked setter: ``QGuiApplication``'s statics are
    C++-backed and not patchable, and the value is process-global and idempotent anyway.

    **Test steps:**

    * mock ``Application``/``ApplicationSingleton`` so no real Qt objects are involved
    * call ``run``
    * verify Qt now reports the desktop file id `linux_registration` registers under
    """
    mocker.patch("rehuco_agent.app.Application")
    singleton_cls = mocker.patch("rehuco_agent.app.ApplicationSingleton")
    singleton_cls.return_value.setup.return_value = False

    run(["rehuco-agent"])

    assert QGuiApplication.desktopFileName() == DESKTOP_FILE_NAME


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


def test_run_shows_the_window_for_a_forward_carrying_no_paths(mocker: MockerFixture) -> None:
    """Starting the app again while it is already running shows it, even when the launch carried no
    path at all -- a plain double-click on the app itself forwards an empty argv, and with tray mode
    on (#205) the window it should come back to may be hidden, so without this the launch looks like
    nothing happened.

    **Test steps:**

    * mock ``Application``/``ApplicationSingleton``
    * capture the callback connected to ``other_instance_run``, then reset the calls ``run``'s own
      startup made through it
    * invoke the callback with an empty path list, as a bare relaunch forwards
    * verify the window was shown and nothing was opened
    """
    app_cls = mocker.patch("rehuco_agent.app.Application")
    app_instance = app_cls.return_value
    singleton_cls = mocker.patch("rehuco_agent.app.ApplicationSingleton")
    singleton = singleton_cls.return_value
    singleton.setup.return_value = True

    run(["rehuco-agent"])

    callback = singleton.other_instance_run.connect.call_args[0][0]
    app_instance.show_main_window.reset_mock()
    callback([])  # pylint: disable=not-callable

    app_instance.show_main_window.assert_called_once_with()
    app_instance.open_path.assert_not_called()
