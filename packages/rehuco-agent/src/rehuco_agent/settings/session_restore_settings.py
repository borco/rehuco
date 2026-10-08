"""Whether a restart restores the previously open documents and root catalog (#65, #408)."""

from dataclasses import dataclass, field
from typing import Final, cast

from PySide6.QtCore import QSettings

GROUP: Final = "session_restore"
RESTORE_LOCAL_DOCUMENTS_KEY: Final = "restore_local_documents"
RESTORE_REMOTE_DOCUMENTS_KEY: Final = "restore_remote_documents"
RESTORE_ROOT_CATALOG_KEY: Final = "restore_root_catalog"
RESTORE_DOCUMENTS_KEY: Final = "restore_documents"
"""The one documents toggle (#408) the two above split (#464); read as their fallback, never written."""
LEGACY_RESTORE_ON_STARTUP_KEY: Final = "restore_on_startup"
"""The single toggle (#65) the documents and root-catalog keys replaced (#408); read as their fallback, never
written."""


@dataclass
class SessionRestoreSettings:
    """The restart-time choices: whether to reopen the previous session's documents -- those on local storage and
    those on remote or removable storage separately (#464) -- and its root catalog.

    Read once at startup, before :class:`~rehuco_agent.settings.document_session_settings.
    DocumentSessionSettings` is applied, and never again this session -- the same plain-dataclass
    shape as :class:`~rehuco_agent.settings.tasks_settings.TasksSettings`, for the same reason:
    nothing already open has to react to this changing.

    Turning documents off only skips *applying* the saved session on the next start; the session
    itself keeps being recorded on every close, so what re-enabling it restores is whatever the most
    recent close left open -- not the session from before the toggle was turned off, whose
    documents survive only as closed entries under the LRU cap.
    """

    restore_local_documents: bool = field(default=True)
    """Reopen the previous session's documents that live on **local storage** -- a fixed drive of this machine -- on
    startup. On by default, matching the long-standing behaviour from #21. They come back at once: their drive is
    there or it is not, and nothing has to be waited for (#464)."""

    restore_remote_documents: bool = field(default=True)
    """Reopen the previous session's documents on **remote or removable storage** -- a share, a USB drive, a disc --
    once their storage is known to be reachable (#464). On by default. One whose storage does not answer is not
    opened this run and stays remembered as open, so it comes back with the storage."""

    restore_root_catalog: bool = field(default=True)
    """Reopen the ``.rehuco`` the previous session left open (#377). On by default."""

    def restores(self, *, local: bool) -> bool:
        """Whether a document on local (``local``) or on remote/removable storage is restored.

        :param local: the kind of storage the document is on.
        """
        return self.restore_local_documents if local else self.restore_remote_documents

    def load(self, settings: QSettings) -> None:
        """Replace the current choices with what's in persistent storage.

        A key not written yet falls back to the one it replaced, so no one's choice changes: the two document
        toggles (#464) to the single one (#408) they split, and that to the legacy ``restore_on_startup`` (#65).
        A user who had restoring off keeps every half off until they choose otherwise.

        :param settings: the ``QSettings`` to read from.
        """
        settings.beginGroup(GROUP)
        legacy = cast(bool, settings.value(LEGACY_RESTORE_ON_STARTUP_KEY, True, type=bool))
        documents = cast(bool, settings.value(RESTORE_DOCUMENTS_KEY, legacy, type=bool))
        self.restore_local_documents = cast(bool, settings.value(RESTORE_LOCAL_DOCUMENTS_KEY, documents, type=bool))
        self.restore_remote_documents = cast(bool, settings.value(RESTORE_REMOTE_DOCUMENTS_KEY, documents, type=bool))
        self.restore_root_catalog = cast(bool, settings.value(RESTORE_ROOT_CATALOG_KEY, legacy, type=bool))
        settings.endGroup()

    def save(self, settings: QSettings) -> None:
        """Save the current choices to persistent storage.

        :param settings: the ``QSettings`` to write to.
        """
        settings.beginGroup(GROUP)
        settings.setValue(RESTORE_LOCAL_DOCUMENTS_KEY, self.restore_local_documents)
        settings.setValue(RESTORE_REMOTE_DOCUMENTS_KEY, self.restore_remote_documents)
        settings.setValue(RESTORE_ROOT_CATALOG_KEY, self.restore_root_catalog)
        settings.endGroup()
