"""Single-instance guard with argv forwarding, built on QLocalServer/QLocalSocket."""

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
        """Name this instance serves on; ``None`` when not the primary (e.g. ``"rehuco-agent-0beec7b5ea3f"``)."""

        self.__buffers: dict[QLocalSocket, bytearray] = {}
        """Per-connection accumulation buffers, keyed by socket, until a full framed message arrives."""

    def setup(self, app_id: str) -> bool:
        """Become the single primary for ``app_id``, or forward argv to the existing one.

        Safe to call again at runtime to rebind to a different ``app_id`` (e.g. from a
        settings dialog); if the new binding fails, the previous one is restored.

        :param app_id: stable per-application identifier; combined with the current OS user
            to form the server name so different users never collide.
        :returns: ``True`` if this process is the primary and should keep running; ``False``
            if a primary already owns ``app_id`` (this process forwarded its argv and should exit).
        :raises RuntimeError: if ``strict`` and the primary role cannot be claimed.
        """
        name = self.__server_name_for(app_id)
        if self.__forward_to_primary(name):
            LOG.info("primary already running for %r; forwarded argv and exiting", app_id)
            return False
        previous_name = self.__server_name
        if self.__listen(name):
            LOG.info("running as primary for %r", app_id)
            return True
        # could not claim the role; restore the previous binding if this was a runtime rebind
        if previous_name is not None and previous_name != name:
            self.__listen(previous_name)
        message = f"could not claim single-instance role for {name!r}"
        if self.__strict:
            raise RuntimeError(message)
        LOG.warning("%s; running without single-instance protection", message)
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

    def __listen(self, name: str) -> bool:
        """Start serving on ``name``, recovering from a stale socket left by a crash.

        Must only be called after :meth:`__forward_to_primary` has confirmed no live server
        is listening on ``name``; otherwise the stale-socket recovery would reap a running primary.

        :param name: local-server name to listen on.
        :returns: ``True`` if the server is now listening.
        """
        self.shutdown()
        server = QLocalServer(self)
        # a crashed primary can leave a socket file that blocks listen() although nothing runs;
        # removeServer is safe here because __forward_to_primary already confirmed no live server answered
        if not server.listen(name) and server.serverError() == QAbstractSocket.SocketError.AddressInUseError:
            QLocalServer.removeServer(name)
            server.listen(name)
        if not server.isListening():
            LOG.warning("listen failed for %r: %s", name, server.errorString())
            server.deleteLater()
            return False
        server.newConnection.connect(self.__on_new_connection)
        self.__server = server
        self.__server_name = name
        return True

    def __forward_to_primary(self, name: str) -> bool:
        """Try to hand this process's argv to an already-running primary.

        :param name: local-server name the primary would be listening on.
        :returns: ``True`` if a primary answered and the argv was forwarded.
        """
        socket = QLocalSocket()
        socket.connectToServer(name)
        if not socket.waitForConnected(CONNECT_TIMEOUT_MS):
            return False
        socket.write(self.__encode(list(sys.argv[1:])))
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

        :param app_id: stable application identifier (e.g. ``"rehuco-agent"``).
        :returns: a server name unique to the current OS user, so users never collide
            (e.g. ``"rehuco-agent-0beec7b5ea3f"`` for user ``"foo"``).
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
