"""Counting what is still connected, shared across the agent's tests (#380, #39)."""

from PySide6.QtCore import QCoreApplication, QEvent, QMetaMethod, QObject


def receivers(obj: QObject) -> dict[str, int]:
    """How many connections each of ``obj``'s signals has, ``QObject``'s own included.

    :param obj: the object to count on.
    :returns: the receiver count per signal signature.
    """
    meta = obj.metaObject()
    counts: dict[str, int] = {}
    for index in range(meta.methodCount()):
        method = meta.method(index)
        if method.methodType() == QMetaMethod.MethodType.Signal:
            signature = bytes(method.methodSignature().data()).decode()
            counts[signature] = obj.receivers(f"2{signature}")
    return counts


def flush_deferred_deletes() -> None:
    """Run every pending ``deleteLater``, so what a teardown scheduled is really gone."""
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
