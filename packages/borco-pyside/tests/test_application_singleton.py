"""Tests for the single-instance guard and its argv forwarding."""

import getpass
import json
import logging
import struct
import sys
import uuid
from collections.abc import Callable
from typing import Final

import pytest
from borco_pyside.core import ApplicationSingleton, application_singleton
from PySide6.QtCore import QCoreApplication, QDeadlineTimer
from PySide6.QtNetwork import QAbstractSocket, QLocalSocket
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot

Factory = Callable[..., ApplicationSingleton]

LENGTH_PREFIX: Final = ">I"
LENGTH_PREFIX_SIZE: Final = 4


def unique_app_id() -> str:
    """Build an app id unlikely to clash with a leftover socket from another run.

    :returns: a per-test unique application identifier.
    """
    return f"borco-pyside-test-{uuid.uuid4().hex[:8]}"


def frame(payload: object) -> bytes:
    """Length-prefix a JSON payload the way the guard's wire format expects.

    :param payload: any JSON-serializable value to frame.
    :returns: the length-prefixed UTF-8 JSON bytes.
    """
    body = json.dumps(payload).encode("utf-8")
    return struct.pack(LENGTH_PREFIX, len(body)) + body


def drain(socket: QLocalSocket) -> None:
    """Pump the event loop until the socket's write buffer is flushed to the OS.

    :param socket: the connected client socket to drain.
    """
    deadline = QDeadlineTimer(1000)
    while socket.bytesToWrite() > 0 and not deadline.hasExpired():
        socket.flush()
        QCoreApplication.processEvents()
        socket.waitForBytesWritten(20)


def connect_raw(name: str | None) -> QLocalSocket:
    """Open a raw client connection to a guard's local server.

    :param name: the server name to connect to; must not be ``None``.
    :returns: a connected :class:`QLocalSocket`.
    """
    assert name is not None
    socket = QLocalSocket()
    socket.connectToServer(name)
    assert socket.waitForConnected(1000)
    return socket


def close_raw(socket: QLocalSocket) -> None:
    """Flush and cleanly close a raw client connection.

    :param socket: the client socket to close.
    """
    drain(socket)
    socket.disconnectFromServer()


def test_single_launch_becomes_primary(make_singleton: Factory) -> None:
    """A lone launch claims the primary role and keeps running.

    **Test steps:**

    * launch a single app instance
    * verify it reports itself as the primary (``setup`` returns ``True``)
    """
    singleton = make_singleton()
    assert singleton.setup(unique_app_id()) is True


def test_second_launch_forwards_argv_and_exits(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, make_singleton: Factory
) -> None:
    """A second launch forwards its argv to the primary and reports that it should exit.

    **Test steps:**

    * launch a primary app instance
    * mock the command line so a second launch carries file arguments
    * launch a second instance for the same app id
    * verify the second instance is told to exit (``setup`` returns ``False``)
    * verify the primary receives exactly the second instance's arguments
    """
    app_id = unique_app_id()
    primary = make_singleton()
    assert primary.setup(app_id) is True

    monkeypatch.setattr(sys, "argv", ["rehuco-agent", "tutorial.rehu", "--flag"])
    secondary = make_singleton()

    with qtbot.waitSignal(primary.other_instance_run, timeout=2000) as blocker:
        assert secondary.setup(app_id) is False

    assert blocker.args == [["tutorial.rehu", "--flag"]]  # type: ignore[reportUnknownMemberType]


def test_no_args_launch_still_notifies_primary(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, make_singleton: Factory
) -> None:
    """A bare relaunch (no file args) still emits, so the primary can raise its window.

    **Test steps:**

    * launch a primary app instance
    * mock the command line so a second launch carries no file arguments
    * launch a second instance for the same app id
    * verify the second instance is told to exit (``setup`` returns ``False``)
    * verify the primary is notified with an empty argument list
    """
    app_id = unique_app_id()
    primary = make_singleton()
    assert primary.setup(app_id) is True

    monkeypatch.setattr(sys, "argv", ["rehuco-agent"])
    secondary = make_singleton()

    with qtbot.waitSignal(primary.other_instance_run, timeout=2000) as blocker:
        assert secondary.setup(app_id) is False

    assert blocker.args == [[]]  # type: ignore[reportUnknownMemberType]


def test_shutdown_releases_the_name(make_singleton: Factory) -> None:
    """After shutdown the name is free, so a later process claims the primary role again.

    **Test steps:**

    * launch a primary app instance and then shut it down
    * launch another instance for the same app id
    * verify the later instance becomes primary itself (``setup`` returns ``True``),
      proving the released name was not left bound
    """
    app_id = unique_app_id()
    first = make_singleton()
    assert first.setup(app_id) is True
    first.shutdown()

    second = make_singleton()
    assert second.setup(app_id) is True


def test_runtime_rebind_to_new_app_id(make_singleton: Factory) -> None:
    """Calling setup again rebinds to a new app id, releasing the previous server.

    **Test steps:**

    * launch a primary instance and note its server name
    * call ``setup`` again with a different app id
    * verify it stays primary and is now serving a different name
    """
    singleton = make_singleton()
    assert singleton.setup(unique_app_id()) is True
    first_name = singleton.server_name

    assert singleton.setup(unique_app_id()) is True
    assert singleton.server_name not in (None, first_name)


def test_partial_frame_is_reassembled(qtbot: QtBot, make_singleton: Factory) -> None:
    """A message split across reads is buffered and delivered once complete.

    **Test steps:**

    * launch a primary instance
    * open a raw client and send a framed message in two separate chunks
    * verify the primary still receives the whole argument list intact
    """
    primary = make_singleton()
    assert primary.setup(unique_app_id()) is True
    framed = frame(["a.rehu"])
    socket = connect_raw(primary.server_name)

    with qtbot.waitSignal(primary.other_instance_run, timeout=2000) as blocker:
        socket.write(framed[:3])
        drain(socket)
        qtbot.wait(20)
        socket.write(framed[3:])
        close_raw(socket)

    assert blocker.args == [["a.rehu"]]  # type: ignore[reportUnknownMemberType]


def test_malformed_message_is_ignored(qtbot: QtBot, make_singleton: Factory, caplog: pytest.LogCaptureFixture) -> None:
    """A framed payload that is not valid JSON is dropped without notifying the app.

    **Test steps:**

    * launch a primary instance
    * send a length-prefixed body that is not valid JSON
    * verify the primary emits nothing
    * verify a warning is logged so the drop is diagnosable
    """
    primary = make_singleton()
    assert primary.setup(unique_app_id()) is True
    body = b"{not valid json"
    payload = struct.pack(LENGTH_PREFIX, len(body)) + body

    with caplog.at_level(logging.WARNING, logger="borco_pyside.core.application_singleton"):
        with qtbot.assertNotEmitted(primary.other_instance_run, wait=200):
            socket = connect_raw(primary.server_name)
            socket.write(payload)
            close_raw(socket)

    assert any("malformed" in r.message for r in caplog.records)


def test_non_list_message_is_ignored(qtbot: QtBot, make_singleton: Factory, caplog: pytest.LogCaptureFixture) -> None:
    """A valid-JSON payload that is not a list is dropped without notifying the app.

    **Test steps:**

    * launch a primary instance
    * send a framed JSON value that is not a list
    * verify the primary emits nothing
    * verify a warning is logged so the drop is diagnosable
    """
    primary = make_singleton()
    assert primary.setup(unique_app_id()) is True

    with caplog.at_level(logging.WARNING, logger="borco_pyside.core.application_singleton"):
        with qtbot.assertNotEmitted(primary.other_instance_run, wait=200):
            socket = connect_raw(primary.server_name)
            socket.write(frame({"not": "a list"}))
            close_raw(socket)

    assert any("unexpected shape" in r.message for r in caplog.records)


def test_rebind_degrades_when_new_and_old_names_both_fail(mocker: MockerFixture, make_singleton: Factory) -> None:
    """If rebinding fails and the previous name is also unavailable, setup degrades gracefully.

    The previous name can become unavailable if another process grabs it in the brief
    window between its release (inside ``__listen``) and the restore attempt — both
    cases are indistinguishable at the socket level, so we simulate the combined failure
    by making ``__listen`` return ``False`` for both names.

    **Test steps:**

    * claim a first app id so a previous server name is recorded
    * patch ``__listen`` to return ``False`` for both the new name and the restore
      (simulating: new name unavailable, previous name snatched between release and restore)
    * call ``setup`` with a second app id
    * verify ``setup`` returns ``True`` (running degraded, not crashing)
    * verify ``server_name`` is ``None`` (neither name is held)
    """
    singleton = make_singleton()
    mocker.patch.object(ApplicationSingleton, "_ApplicationSingleton__forward_to_primary", return_value=False)
    assert singleton.setup(unique_app_id()) is True  # real server claimed on first name

    # patch QLocalServer so listen() fails for all subsequent calls;
    # __listen() still runs its shutdown() first, which clears server_name
    mock_cls = mocker.patch("borco_pyside.core.application_singleton.QLocalServer")
    instance = mock_cls.return_value
    instance.listen.return_value = False
    instance.isListening.return_value = False

    result = singleton.setup(unique_app_id())

    assert result is True  # degraded: running without single-instance protection
    assert singleton.server_name is None


def test_rebind_failure_attempts_to_restore_previous_server(mocker: MockerFixture, make_singleton: Factory) -> None:
    """When rebinding to a new app id fails, the guard tries to restore the previous server.

    **Test steps:**

    * bypass the forwarding attempt so there is no connection timeout
    * let the first ``setup`` succeed and record the server name
    * patch ``__claim_role`` on the instance to always report ``Claim.FAILED``
    * call ``setup`` with a new app id and verify ``__claim_role`` was called twice: once
      for the new name and once to attempt restoration of the previous name
    """
    mocker.patch.object(ApplicationSingleton, "_ApplicationSingleton__forward_to_primary", return_value=False)
    singleton = make_singleton()
    assert singleton.setup("first-id") is True
    previous_name = singleton.server_name

    claim_mock = mocker.patch.object(
        singleton, "_ApplicationSingleton__claim_role", return_value=ApplicationSingleton.Claim.FAILED
    )
    result = singleton.setup("second-id")

    assert result is True  # degraded: neither name could be claimed
    assert claim_mock.call_count == 2
    restore_name = claim_mock.call_args_list[1].args[0]
    assert restore_name == previous_name


def test_shutdown_with_connection_in_flight(qtbot: QtBot, make_singleton: Factory) -> None:
    """Shutdown is clean when a client connection is still mid-message.

    **Test steps:**

    * launch a primary instance
    * open a raw client and send only a partial frame (never completed)
    * let the primary accept and buffer the connection
    * shut the primary down and verify the name is released
    """
    primary = make_singleton()
    assert primary.setup(unique_app_id()) is True
    name = primary.server_name
    socket = connect_raw(name)
    socket.write(b"\x00")  # one byte: shorter than the length prefix, so never completes
    drain(socket)
    qtbot.wait(20)

    primary.shutdown()
    assert primary.server_name is None
    close_raw(socket)


def test_server_name_falls_back_when_user_unavailable(monkeypatch: pytest.MonkeyPatch, make_singleton: Factory) -> None:
    """The server name is still derived when the OS user cannot be determined.

    **Test steps:**

    * force ``getpass.getuser`` to raise ``OSError``
    * launch an instance and claim the primary role
    * verify a server name was still assigned
    """

    def boom() -> str:
        raise OSError("no user-identifying environment")

    monkeypatch.setattr(getpass, "getuser", boom)
    singleton = make_singleton()
    assert singleton.setup(unique_app_id()) is True
    assert singleton.server_name is not None


def test_listen_failure_runs_degraded(mocker: MockerFixture, make_singleton: Factory) -> None:
    """When the server cannot listen (non-AddressInUseError), setup returns True in degraded mode.

    **Test steps:**

    * bypass the forwarding attempt so there is no connection timeout
    * mock ``QLocalServer`` so ``listen`` fails and ``isListening`` returns ``False``
    * call ``setup``; verify it returns ``True`` but ``server_name`` stays ``None``
    """
    singleton = make_singleton()
    mocker.patch.object(ApplicationSingleton, "_ApplicationSingleton__forward_to_primary", return_value=False)
    mock_cls = mocker.patch("borco_pyside.core.application_singleton.QLocalServer")
    instance = mock_cls.return_value
    instance.listen.return_value = False
    instance.isListening.return_value = False

    assert singleton.setup("any-id") is True
    assert singleton.server_name is None


def test_listen_failure_raises_in_strict_mode(mocker: MockerFixture, make_singleton: Factory) -> None:
    """With ``strict=True``, a listen failure raises ``RuntimeError`` instead of degrading.

    **Test steps:**

    * bypass the forwarding attempt so there is no connection timeout
    * mock ``QLocalServer`` so ``listen`` always fails
    * call ``setup`` and verify a ``RuntimeError`` is raised
    """
    singleton = make_singleton(strict=True)
    mocker.patch.object(ApplicationSingleton, "_ApplicationSingleton__forward_to_primary", return_value=False)
    mock_cls = mocker.patch("borco_pyside.core.application_singleton.QLocalServer")
    instance = mock_cls.return_value
    instance.listen.return_value = False
    instance.isListening.return_value = False

    with pytest.raises(RuntimeError, match="could not claim single-instance role"):
        singleton.setup("any-id")


def test_stale_socket_is_removed_after_reprobe_finds_no_primary(mocker: MockerFixture, make_singleton: Factory) -> None:
    """An ``AddressInUseError`` with no primary answering the re-probe triggers ``removeServer`` then a retry.

    **Test steps:**

    * make every forwarding probe miss (initial probe and every stale-recovery re-probe)
    * mock ``QLocalServer.listen`` to fail on the first call with ``AddressInUseError``
      and succeed on the second call
    * call ``setup`` and verify it becomes primary, ``removeServer`` was called exactly once,
      ``listen`` was called twice, and the socket was re-probed the bounded number of times
    """
    singleton = make_singleton()
    forward_mock = mocker.patch.object(
        ApplicationSingleton, "_ApplicationSingleton__forward_to_primary", return_value=False
    )
    mock_cls = mocker.patch("borco_pyside.core.application_singleton.QLocalServer")
    instance = mock_cls.return_value
    instance.listen.side_effect = [False, True]
    instance.serverError.return_value = QAbstractSocket.SocketError.AddressInUseError
    instance.isListening.return_value = True

    assert singleton.setup("any-id") is True
    assert instance.listen.call_count == 2
    mock_cls.removeServer.assert_called_once()
    # one initial probe in setup(), then the bounded stale-recovery re-probes
    assert forward_mock.call_count == 1 + application_singleton.STALE_RECOVERY_ATTEMPTS


def test_address_in_use_reprobe_forwards_to_raced_primary(mocker: MockerFixture, make_singleton: Factory) -> None:
    """A primary that races us to ``listen`` is found by the re-probe and never reaped.

    Two processes start with no existing primary: both miss the initial forward, one wins
    ``listen`` and the other gets ``AddressInUseError``. The loser must re-probe, discover the
    freshly-live primary, and forward to it — rather than ``removeServer``-ing its live socket.

    **Test steps:**

    * make the initial forward miss (no primary yet) but the first stale-recovery re-probe hit
      (the racer is now listening)
    * mock ``QLocalServer.listen`` to fail with ``AddressInUseError``
    * call ``setup`` and verify it reports secondary (returns ``False``) and that
      ``removeServer`` was never called (the live primary was not reaped)
    """
    singleton = make_singleton()
    # initial probe misses; the first re-probe finds the racer that just claimed the name
    mocker.patch.object(ApplicationSingleton, "_ApplicationSingleton__forward_to_primary", side_effect=[False, True])
    mock_cls = mocker.patch("borco_pyside.core.application_singleton.QLocalServer")
    instance = mock_cls.return_value
    instance.listen.return_value = False
    instance.serverError.return_value = QAbstractSocket.SocketError.AddressInUseError
    instance.isListening.return_value = False

    assert singleton.setup("any-id") is False  # forwarded to the raced primary; this process exits
    mock_cls.removeServer.assert_not_called()


def test_setup_forwards_explicit_args_over_argv(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, make_singleton: Factory
) -> None:
    """An explicit ``args`` payload is forwarded verbatim, independent of ``sys.argv``.

    **Test steps:**

    * launch a primary app instance
    * mock the command line so ``sys.argv`` carries a different, decoy file argument
    * launch a second instance passing an explicit ``args`` list
    * verify the primary receives the explicit args, not the argv decoy
    """
    app_id = unique_app_id()
    primary = make_singleton()
    assert primary.setup(app_id) is True

    monkeypatch.setattr(sys, "argv", ["rehuco-agent", "from-argv.rehu"])
    secondary = make_singleton()

    with qtbot.waitSignal(primary.other_instance_run, timeout=2000) as blocker:
        assert secondary.setup(app_id, ["explicit.rehu", "--x"]) is False

    assert blocker.args == [["explicit.rehu", "--x"]]  # type: ignore[reportUnknownMemberType]


def test_forwarding_waits_for_disconnect_when_socket_lingers(mocker: MockerFixture, make_singleton: Factory) -> None:
    """The forwarding path calls ``waitForDisconnected`` if the socket does not disconnect at once.

    **Test steps:**

    * mock ``QLocalSocket`` so the connection appears to succeed immediately and
      ``state()`` returns a non-``UnconnectedState`` value after ``disconnectFromServer``
    * call ``setup`` and verify the secondary path returns ``False`` (primary exists)
      and ``waitForDisconnected`` was invoked
    """
    mock_socket = mocker.MagicMock()
    mock_socket.waitForConnected.return_value = True
    mock_socket.bytesToWrite.return_value = 0  # flush loop exits immediately
    mocker.patch("borco_pyside.core.application_singleton.QLocalSocket", return_value=mock_socket)

    singleton = make_singleton()
    assert singleton.setup("any-id") is False  # primary "exists"
    mock_socket.waitForDisconnected.assert_called_once()


def test_new_connection_signal_after_shutdown_is_a_noop(make_singleton: Factory) -> None:
    """A ``newConnection`` signal that fires after shutdown does not crash or modify state.

    **Test steps:**

    * launch a primary and then shut it down (``server`` becomes ``None``)
    * invoke the connection handler directly to simulate a queued signal firing post-shutdown
    * verify the server name is still ``None``
    """
    singleton = make_singleton()
    assert singleton.setup(unique_app_id()) is True
    singleton.shutdown()
    singleton._ApplicationSingleton__on_new_connection()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    assert singleton.server_name is None


def test_body_received_separately_from_prefix_is_reassembled(qtbot: QtBot, make_singleton: Factory) -> None:
    """A message split exactly between the length prefix and the body is buffered and delivered.

    **Test steps:**

    * launch a primary instance
    * open a raw client and send exactly the 4-byte length prefix in one write
    * after a brief pause, send the remaining body bytes
    * verify the primary receives the complete argument list
    """
    primary = make_singleton()
    assert primary.setup(unique_app_id()) is True
    framed = frame(["b.rehu"])
    socket = connect_raw(primary.server_name)

    with qtbot.waitSignal(primary.other_instance_run, timeout=2000) as blocker:
        socket.write(framed[:LENGTH_PREFIX_SIZE])  # length prefix only — body not yet sent
        drain(socket)
        qtbot.wait(20)
        socket.write(framed[LENGTH_PREFIX_SIZE:])  # body only
        close_raw(socket)

    assert blocker.args == [["b.rehu"]]  # type: ignore[reportUnknownMemberType]
