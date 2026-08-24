"""Whether a restart restores the previously open documents (#65)."""

from dataclasses import dataclass, field
from typing import Final, cast

from PySide6.QtCore import QSettings

GROUP: Final = "session_restore"
RESTORE_ON_STARTUP_KEY: Final = "restore_on_startup"


@dataclass
class SessionRestoreSettings:
    """One restart-time choice: whether to reopen the previous session's documents at all.

    Read once at startup, before :class:`~rehuco_agent.settings.document_session_settings.
    DocumentSessionSettings` is applied, and never again this session -- the same plain-dataclass
    shape as :class:`~rehuco_agent.settings.tasks_settings.TasksSettings`, for the same reason:
    nothing already open has to react to this changing.

    Turning this off only skips *applying* the saved session on the next start; the session itself
    keeps being recorded on every close, so what re-enabling it restores is whatever the most
    recent close left open -- not the session from before the toggle was turned off, whose
    documents survive only as closed entries under the LRU cap.
    """

    restore_on_startup: bool = field(default=True)
    """Reopen the previous session's documents on startup. On by default, matching the
    long-standing behaviour from #21."""

    def load(self, settings: QSettings) -> None:
        """Replace the current choice with what's in persistent storage.

        :param settings: the ``QSettings`` to read from.
        """
        settings.beginGroup(GROUP)
        self.restore_on_startup = cast(bool, settings.value(RESTORE_ON_STARTUP_KEY, True, type=bool))
        settings.endGroup()

    def save(self, settings: QSettings) -> None:
        """Save the current choice to persistent storage.

        :param settings: the ``QSettings`` to write to.
        """
        settings.beginGroup(GROUP)
        settings.setValue(RESTORE_ON_STARTUP_KEY, self.restore_on_startup)
        settings.endGroup()
