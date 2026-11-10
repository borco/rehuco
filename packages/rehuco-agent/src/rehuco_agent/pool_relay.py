"""Carries a pool job's answer to the GUI thread through an object no window can delete
([[appendices.code-conventions#worker-threads]])."""

from collections.abc import Callable

from PySide6.QtCore import QCoreApplication, QObject, Qt, QThread, Signal, Slot
from shiboken6 import isValid


class PoolRelay(QObject):
    """The one sender every pool job posts its answer through, a child of the application.

    A job that emitted on its owner's own signal raced the GUI thread: deleting the owner -- a document closed while
    its videos were listed -- while the pool thread was inside the emit crashed the process, and the ``RuntimeError``
    guard around the emit caught only an owner deleted *before* it. The relay is never deleted while a job can still
    post: it is the application's child, and ``~QCoreApplication`` waits for the global pool before it deletes its
    children. Its single connection is made when it is built and never changes, so a pool thread's emit never meets a
    connect or a destroy on it ([[appendices.code-conventions#worker-threads]], #529).

    What is posted is called on the GUI thread, the thread that deletes the owner, and only while the owner is there:
    one gone by then is seen gone, with no race, and its answer goes to nobody -- what a queued connection to it would
    have done.

    :param parent: the application.
    """

    relayed = Signal(object, object, object)
    """``(owner, deliver, args)``, emitted on a pool thread and delivered to :meth:`__call` on the GUI thread."""

    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self.relayed.connect(self.__call, Qt.ConnectionType.QueuedConnection)

    @classmethod
    def instance(cls) -> PoolRelay:
        """The application's relay, made on first use.

        Called on the application's thread, where every owner starts its work: the relay lives on the thread that
        builds it, so one built anywhere else would make its calls there, or never.

        :returns: the relay.
        :raises RuntimeError: if there is no application, or this is not its thread.
        """
        app = QCoreApplication.instance()
        if app is None:
            raise RuntimeError("A pool relay needs an application.")
        if QThread.currentThread() != app.thread():
            raise RuntimeError("The pool relay is asked for on the application's thread, before the work is started.")
        relay = app.findChild(PoolRelay, options=Qt.FindChildOption.FindDirectChildrenOnly)
        return relay if relay is not None else PoolRelay(app)

    def post(self, owner: QObject, deliver: Callable[..., None], *args: object) -> None:
        """Call ``deliver(*args)`` on the GUI thread if ``owner`` is still there; called on a pool thread.

        :param owner: the object the answer is for, made in Python on the GUI thread.
        :param deliver: the owner's own delivery.
        :param args: what to hand it.
        """
        self.relayed.emit(owner, deliver, args)

    @Slot(object, object, object)
    def __call(self, owner: QObject, deliver: Callable[..., None], args: tuple[object, ...]) -> None:
        """Make the posted call unless its owner was deleted meanwhile (GUI thread).

        :param owner: the object the answer is for.
        :param deliver: the owner's own delivery.
        :param args: what to hand it.
        """
        if isValid(owner):
            deliver(*args)
