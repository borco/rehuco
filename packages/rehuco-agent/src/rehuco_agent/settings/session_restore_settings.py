"""Whether a restart restores the previously open documents and root catalog (#65, #408)."""

from dataclasses import dataclass, field
from typing import Final, cast

from PySide6.QtCore import QSettings

GROUP: Final = "session_restore"
RESTORE_DOCUMENTS_KEY: Final = "restore_documents"
RESTORE_ROOT_CATALOG_KEY: Final = "restore_root_catalog"
LEGACY_RESTORE_ON_STARTUP_KEY: Final = "restore_on_startup"
"""The single toggle (#65) the two keys above replaced (#408); read as their fallback, never written."""


@dataclass
class SessionRestoreSettings:
    """Two restart-time choices: whether to reopen the previous session's documents, and its root catalog.

    Read once at startup, before :class:`~rehuco_agent.settings.document_session_settings.
    DocumentSessionSettings` is applied, and never again this session -- the same plain-dataclass
    shape as :class:`~rehuco_agent.settings.tasks_settings.TasksSettings`, for the same reason:
    nothing already open has to react to this changing.

    Turning documents off only skips *applying* the saved session on the next start; the session
    itself keeps being recorded on every close, so what re-enabling it restores is whatever the most
    recent close left open -- not the session from before the toggle was turned off, whose
    documents survive only as closed entries under the LRU cap.
    """

    restore_documents: bool = field(default=True)
    """Reopen the previous session's documents on startup. On by default, matching the
    long-standing behaviour from #21."""

    restore_root_catalog: bool = field(default=True)
    """Reopen the ``.rehuco`` the previous session left open (#377). On by default."""

    def load(self, settings: QSettings) -> None:
        """Replace the current choices with what's in persistent storage.

        A key not written yet falls back to the legacy single toggle (#408), so a user who had
        restoring off keeps both halves off until they choose otherwise.

        :param settings: the ``QSettings`` to read from.
        """
        settings.beginGroup(GROUP)
        legacy = cast(bool, settings.value(LEGACY_RESTORE_ON_STARTUP_KEY, True, type=bool))
        self.restore_documents = cast(bool, settings.value(RESTORE_DOCUMENTS_KEY, legacy, type=bool))
        self.restore_root_catalog = cast(bool, settings.value(RESTORE_ROOT_CATALOG_KEY, legacy, type=bool))
        settings.endGroup()

    def save(self, settings: QSettings) -> None:
        """Save the current choices to persistent storage.

        :param settings: the ``QSettings`` to write to.
        """
        settings.beginGroup(GROUP)
        settings.setValue(RESTORE_DOCUMENTS_KEY, self.restore_documents)
        settings.setValue(RESTORE_ROOT_CATALOG_KEY, self.restore_root_catalog)
        settings.endGroup()
