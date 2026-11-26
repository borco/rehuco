"""Where every log surface's link clicks arrive, so the window alone decides what a link opens (#700)."""

from PySide6.QtCore import QObject, Signal


class LogLinkRelay(QObject):
    """Carries the target of a link clicked in any log surface -- the window's, a document's, a job's -- to whoever
    opens links.

    One object, because there are many surfaces and one window: they are built deep inside the documents and the Tasks
    dock, which have no other reason to know what a link opens, the same reason the log bridge is shared
    (`~rehuco_agent.app_logging.shared_log_bridge`).

    :param parent: optional Qt parent.
    """

    activated = Signal(object)
    """Emitted with the clicked link's target, typed as plain ``object`` so that whatever a record put there arrives as
    itself."""
