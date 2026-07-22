"""Single-instance guard with argv forwarding, built on QLocalServer/QLocalSocket."""

import enum
import getpass
import hashlib
import json
import logging
import struct
import sys
from typing import Final

from PySide6.QtCore import QCoreApplication, QDeadlineTimer, QObject, Signal
from PySide6.QtNetwork import QAbstractSocket, QLocalServer, QLocalSocket

LOG: Final = logging.getLogger(__name__)

CONNECT_TIMEOUT_MS: Final = 1000
"""Milliseconds to wait for a secondary instance to connect to the primary's server."""

WRITE_TIMEOUT_MS: Final = 1000
"""Milliseconds to wait for a secondary instance to flush its argv payload and disconnect."""

STALE_RECOVERY_ATTEMPTS: Final = 3
"""Re-probes for a live primary after ``AddressInUseError`` before treating the socket as stale.

Guards the launch-storm race: with no existing primary, two processes both fail the initial
forward; one wins :meth:`~QLocalServer.listen`, the other gets ``AddressInUseError``. Re-probing
lets the loser discover the freshly-live primary and forward to it, instead of unlinking that
primary's *live* socket via :meth:`~QLocalServer.removeServer`.
"""

LENGTH_PREFIX: Final = ">I"
"""``struct`` format for the 4-byte big-endian unsigned integer that precedes each message body."""

LENGTH_PREFIX_SIZE: Final = 4
"""Byte size of :data:`LENGTH_PREFIX` — the fixed overhead prepended to every framed message."""


class ApplicationSingleton(QObject):
    """Single-instance guard: the first process serves; later ones forward argv and exit.

    Detection and forwarding share one mechanism — a ``QLocalServer`` keyed on a per-user,
    per-app name. The first process to ``listen`` becomes the primary; a later process that
    can ``connectToServer`` instead writes its argv down the socket and exits, letting the
    primary react via :attr:`other_instance_run`. Construction claims no role yet — call
    :meth:`setup`.

    :param parent: optional Qt parent.
    :param strict: raise instead of running degraded if the primary role cannot be claimed.
    """

    class Claim(enum.Enum):
        """Outcome of attempting to claim the primary role on a server name."""

        PRIMARY = enum.auto()
        """This process is now the listening primary."""

        FORWARDED = enum.auto()
        """A live primary was found during stale-socket recovery; argv was forwarded and this process should exit."""

        FAILED = enum.auto()
        """The role could not be claimed (listen failed for a reason other than a recoverable stale socket)."""

    other_instance_run = Signal(list)
    """Emitted on the primary when a secondary instance forwards its argv and exits.

    The argument is a ``list[str]`` of the secondary's command-line arguments (``sys.argv[1:]``),
    which typically contains the file paths the user asked the OS to open.
    """

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        strict: bool = False,
    ) -> None:
        super().__init__(parent)

        self.__strict: Final = strict
        """Raise instead of degrading when the primary role cannot be claimed."""

        self.__server: QLocalServer | None = None
        """Listening server while this process is the primary; ``None`` otherwise."""

        self.__server_name: str | None = None
        """Name this instance serves on; ``None`` when not the primary (e.g. ``"my-app-0beec7b5ea3f"``)."""

        self.__buffers: dict[QLocalSocket, bytearray] = {}
        """Per-connection accumulation buffers, keyed by socket, until a full framed message arrives."""

    def setup(self, app_id: str, args: list[str] | None = None) -> bool:
        """Become the single primary for ``app_id``, or forward ``args`` to the existing one.

        Safe to call again at runtime to rebind to a different ``app_id`` (e.g. from a
        settings dialog); if the new binding fails, the previous one is restored.

        :param app_id: stable per-application identifier; combined with the current OS user
            to form the server name so different users never collide.
        :param args: payload to forward if a primary already owns ``app_id``; defaults to this
            process's ``sys.argv[1:]``. Emitted verbatim through :attr:`other_instance_run`.
        :returns: ``True`` if this process is the primary and should keep running; ``False``
            if a primary already owns ``app_id`` (this process forwarded ``args`` and should exit).
        :raises RuntimeError: if ``strict`` and the primary role cannot be claimed.
        """
        name = self.__server_name_for(app_id)
        message = self.__encode([str(arg) for arg in (sys.argv[1:] if args is None else args)])
        if self.__forward_to_primary(name, message):
            LOG.info("primary already running for %r; forwarded argv and exiting", app_id)
            return False
        previous_name = self.__server_name
        outcome = self.__claim_role(name, message)
        if outcome is self.Claim.PRIMARY:
            LOG.info("running as primary for %r", app_id)
            return True
        if outcome is self.Claim.FORWARDED:
            # a primary raced us to the name after our initial probe missed it; argv was forwarded
            LOG.info("primary raced to %r during stale-socket recovery; forwarded argv and exiting", app_id)
            return False
        # could not claim the role; restore the previous binding if this was a runtime rebind
        if previous_name is not None and previous_name != name:
            self.__claim_role(previous_name, message)
        detail = f"could not claim single-instance role for {name!r}"
        if self.__strict:
            raise RuntimeError(detail)
        LOG.warning("%s; running without single-instance protection", detail)
        return True

    @property
    def server_name(self) -> str | None:
        """The local-server name this instance serves on, or ``None`` if not the primary."""
        return self.__server_name

    def shutdown(self) -> None:
        """Stop serving, drain pending buffers, and release the local-server name."""
        for socket in self.__buffers:
            # stop self-capturing slots from firing after teardown
            socket.blockSignals(True)
        self.__buffers.clear()
        if self.__server is not None:
            self.__server.close()
            self.__server.deleteLater()
            self.__server = None
            self.__server_name = None

    def __claim_role(self, name: str, message: bytes) -> ApplicationSingleton.Claim:
        """Start serving on ``name``, recovering from a stale socket left by a crash.

        On ``AddressInUseError`` the name may be held by either a crashed primary's stale
        socket or a primary that raced us to ``listen`` after our initial forward probe missed
        it. To tell them apart, re-probe with a bounded forward (:data:`STALE_RECOVERY_ATTEMPTS`)
        before unlinking anything: if a primary answers, ``message`` is forwarded to it and
        :attr:`Claim.FORWARDED` is returned; only if none answers is the socket treated as stale
        and reclaimed via :meth:`~QLocalServer.removeServer`.

        :param name: local-server name to listen on.
        :param message: framed payload to forward if the re-probe finds a live primary.
        :returns: which role was claimed (see :class:`Claim`).
        """
        self.shutdown()
        server = QLocalServer(self)
        if not server.listen(name) and server.serverError() == QAbstractSocket.SocketError.AddressInUseError:
            server.deleteLater()
            for _ in range(STALE_RECOVERY_ATTEMPTS):
                if self.__forward_to_primary(name, message):
                    return self.Claim.FORWARDED
            # no primary answered across the bounded re-probes: the socket is stale, so reclaim it
            QLocalServer.removeServer(name)
            server = QLocalServer(self)
            server.listen(name)
        if not server.isListening():
            LOG.warning("listen failed for %r: %s", name, server.errorString())
            server.deleteLater()
            return self.Claim.FAILED
        server.newConnection.connect(self.__on_new_connection)
        self.__server = server
        self.__server_name = name
        return self.Claim.PRIMARY

    def __forward_to_primary(self, name: str, message: bytes) -> bool:
        """Try to hand ``message`` to an already-running primary listening on ``name``.

        :param name: local-server name the primary would be listening on.
        :param message: framed payload to write (see :meth:`__encode`).
        :returns: ``True`` if a primary answered and the payload was forwarded.
        """
        socket = QLocalSocket()
        socket.connectToServer(name)
        if not socket.waitForConnected(CONNECT_TIMEOUT_MS):
            return False
        socket.write(message)
        self.__flush(socket)
        socket.disconnectFromServer()
        if socket.state() != QLocalSocket.LocalSocketState.UnconnectedState:
            socket.waitForDisconnected(WRITE_TIMEOUT_MS)
        return True

    @staticmethod
    def __flush(socket: QLocalSocket) -> None:
        """Push all pending bytes to the OS before this short-lived client is destroyed.

        QLocalSocket only transmits while an event loop runs; without pumping events the
        payload would be discarded when the forwarding process exits (notably on Windows,
        where ``waitForBytesWritten`` alone does not drain the write buffer).

        :param socket: the connected client socket whose write buffer must be drained.
        """
        deadline = QDeadlineTimer(WRITE_TIMEOUT_MS)
        while socket.bytesToWrite() > 0 and not deadline.hasExpired():
            socket.flush()
            QCoreApplication.processEvents()
            socket.waitForBytesWritten(20)

    def __on_new_connection(self) -> None:
        """Accept pending connections and wire each to incremental message reading."""
        if self.__server is None:
            return
        while self.__server.hasPendingConnections():
            socket = self.__server.nextPendingConnection()
            # pylint-qt mis-infers dict attributes on QObject subclasses (false positive)
            self.__buffers[socket] = bytearray()  # pylint: disable=unsupported-assignment-operation
            socket.readyRead.connect(lambda s=socket: self.__on_ready_read(s))
            socket.disconnected.connect(lambda s=socket: self.__on_ready_read(s))
            socket.disconnected.connect(lambda s=socket: self.__buffers.pop(s, None))
            # the client may have written and disconnected before this accept ran, so its
            # bytes are already buffered and readyRead will not fire again — drain them now
            self.__on_ready_read(socket)

    def __on_ready_read(self, socket: QLocalSocket) -> None:
        """Accumulate bytes from ``socket`` and emit once a full framed message arrives.

        A framed message is a 4-byte big-endian length followed by that many bytes of JSON
        body; see :meth:`__encode` for the format. Bytes are buffered across ``readyRead``
        calls until the complete message is available, then decoded and emitted.

        :param socket: the client connection delivering a forwarded argv.
        """
        buffer = self.__buffers.get(socket)
        if buffer is None:
            # no buffer: either already delivered (trailing disconnected after readyRead drained the socket),
            # or shutdown() cleared __buffers before this signal fired
            return
        buffer.extend(bytes(socket.readAll().data()))
        if len(buffer) < LENGTH_PREFIX_SIZE:
            return
        (length,) = struct.unpack(LENGTH_PREFIX, bytes(buffer[:LENGTH_PREFIX_SIZE]))
        if len(buffer) < LENGTH_PREFIX_SIZE + length:
            return
        body = bytes(buffer[LENGTH_PREFIX_SIZE : LENGTH_PREFIX_SIZE + length])
        # drop the buffer and schedule socket cleanup; deleteLater() defers until the event
        # loop unwinds — safe to call from within a signal handler, unlike a direct delete
        self.__buffers.pop(socket, None)
        socket.deleteLater()
        self.__deliver(body)

    def __deliver(self, body: bytes) -> None:
        """Decode a framed argv and emit :attr:`other_instance_run` on the GUI thread.

        :param body: the JSON payload without the length prefix.
        """
        try:
            data: object = json.loads(body.decode("utf-8"))
        except UnicodeDecodeError, json.JSONDecodeError:
            LOG.warning("ignoring malformed forwarded message")
            return
        if not isinstance(data, list):
            LOG.warning("ignoring forwarded message of unexpected shape")
            return
        args = [str(arg) for arg in data]
        LOG.info("second instance forwarded: %r", args)
        self.other_instance_run.emit(args)

    @staticmethod
    def __server_name_for(app_id: str) -> str:
        """Derive a per-user, per-app server name that is stable across launches.

        Appends a 12-hex-char SHA-1 fingerprint of the OS username to ``app_id``,
        producing the same name on every run for the same user while keeping names
        from different users distinct (e.g. user ``"foo"`` → fingerprint ``"0beec7b5ea3f"``).

        :param app_id: stable application identifier (e.g. ``"my-app"``).
        :returns: a server name unique to the current OS user, so users never collide
            (e.g. ``"my-app-0beec7b5ea3f"`` for user ``"foo"``).
        """
        try:
            user = getpass.getuser()
        except OSError:  # getuser raises when no user-identifying env var is set
            user = "unknown"
        # not security-sensitive: just a stable, collision-resistant per-user discriminator
        digest = hashlib.sha1(user.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]
        return f"{app_id}-{digest}"

    @staticmethod
    def __encode(args: list[str]) -> bytes:
        """Frame argv as a length-prefixed UTF-8 JSON payload for one socket write.

        Framing prepends a fixed-size length header so the receiver can extract exactly one
        message from the raw byte stream, even if multiple messages arrive back-to-back::

            [ 4 bytes: length of body ] [ body bytes (JSON) ]

        :param args: argument list to send.
        :returns: the framed bytes: a 4-byte big-endian length followed by the JSON body.
        """
        body = json.dumps(args).encode("utf-8")
        return struct.pack(LENGTH_PREFIX, len(body)) + body
