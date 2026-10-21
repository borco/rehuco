"""Unsaved edits kept across a quit, and the documents holding them reopened with them on the next start (#497)."""

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from borco_core import Presence
from PySide6.QtCore import QObject
from rehuco_core import SavePayload, record_differences
from rehuco_core.access import Records, ResourceKey

from ..settings.identity_settings import shared_identity_settings
from ..settings.persistent_settings import config_folder
from ..settings.state_file import decode_bytes, encode_bytes, read_state_file, write_state_file
from ..startup_presence import StartupPresence
from .document_widget import DocumentWidget
from .documents_dock import DocumentsDock

LOG: Final = logging.getLogger(__name__)

UNSAVED_CHANGES_FILENAME: Final = "unsaved-changes.json"
"""What the kept edits are called, in the app's own config folder."""

UNSAVED_CHANGES_VERSION: Final = 1
"""The shape of the file this build reads and writes."""


@dataclass(frozen=True, slots=True)
class UnsavedEntry:
    """One document's kept edits.

    :param payload: the edits, as a save would write them (:meth:`~.rehu_document_model.RehuDocumentModel.snapshot`).
    :param layout: the document's own dock layout, so it comes back laid out as it was.
    """

    payload: SavePayload
    layout: bytes


class UnsavedChanges(QObject):
    """Keeps the open documents' unsaved edits when the app quits, and reopens them on the next start.

    **Nothing is dropped for being gone**: an entry whose file or folder is not there -- its device having answered --
    reopens all the same, with its edits and the document's *gone* banner, and the decision is the user's. One whose
    device does not answer at start is kept for the next, and so is never lost because a server was off.

    :param dock: the Documents dock the documents reopen in.
    :param records: what a reopened document's file is read through.
    :param path: the file; ``unsaved-changes.json`` in the config folder unless a test says otherwise.
    :param parent: optional Qt parent.
    """

    def __init__(
        self, dock: DocumentsDock, records: Records, path: Path | None = None, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self.__dock: Final = dock
        self.__records: Final = records
        self.__path: Final = path if path is not None else config_folder() / UNSAVED_CHANGES_FILENAME
        self.__waiting: Final[dict[Path, UnsavedEntry]] = {}
        """The entries whose folder has not been heard from yet, by folder."""
        self.__presence: StartupPresence | None = None

    def reopen(self) -> None:
        """Reopen every kept document with its edits: at once on a local drive, as its device answers otherwise."""
        entries = self.__read()
        if not entries:
            return
        for entry in entries:
            self.__waiting[entry.payload.path] = entry  # pylint: disable=unsupported-assignment-operation
        presence = StartupPresence((path.parent for path in self.__waiting), self)
        self.__presence = presence
        for folder, verdict in presence.local_paths.items():
            self.__arrived(folder, verdict)
        presence.answered.connect(self.__arrived)
        presence.start()

    def stop(self) -> None:
        """Deliver no more answers, before the window goes."""
        if self.__presence is not None:
            self.__presence.stop()

    def keep(self, widgets: Iterable[DocumentWidget]) -> None:
        """Write down the edits of every dirty document among ``widgets``, with those not reopened yet this run.

        :param widgets: the open documents.
        """
        entries = list(self.__waiting.values())
        kept = {entry.payload.path for entry in entries}
        for widget in widgets:
            model = widget.model
            if not model.dirty or model.path is None or model.path in kept:
                continue
            try:
                payload = model.snapshot()
            except ValueError as error:
                LOG.warning("The unsaved edits of %s cannot be kept: %s", model.path, error)
                continue
            entries.append(UnsavedEntry(payload, widget.save_state()))
            kept.add(model.path)
        self.__write(entries)

    def forget(self) -> None:
        """Keep nothing: quitting asked about the edits instead."""
        self.__write([])

    def __arrived(self, folder: Path, presence: Presence) -> None:
        """Reopen the kept documents in a folder that answered.

        :param folder: the folder.
        :param presence: whether it is there; an offline one keeps its entries for the next start.
        """
        if presence is Presence.OFFLINE:
            return
        for path, entry in list(self.__waiting.items()):
            if path.parent != folder:
                continue
            del self.__waiting[path]  # pylint: disable=unsupported-delete-operation
            self.__open(entry, folder_gone=presence is Presence.GONE)
        if not self.__waiting:
            self.__write([])

    def __open(self, entry: UnsavedEntry, *, folder_gone: bool) -> None:
        """Reopen one kept document with its edits.

        :param entry: the kept edits.
        :param folder_gone: whether the record's folder is gone.
        """
        payload = entry.payload
        key = ResourceKey(payload.path)
        file_there = not folder_gone and payload.path.exists()
        widget = self.__dock.open_document(key, state=entry.layout, new=payload.first_save and not file_there)
        current = None
        if file_there:
            settings = shared_identity_settings()
            record = self.__records.load(
                key, username=settings.current_username, unknown_username=settings.unknown_username
            )
            current = record if record.version is not None else None
        model = widget.model
        if current is not None and not record_differences(
            payload.base_payload or {}, payload.payload, current.document.payload_to_write(), payload.username
        ):
            # the file already holds these edits -- a save of them that was pending landed before this reopen
            LOG.info("%s already holds the edits it was left with", payload.path)
            return
        model.adopt_unsaved(payload, current)
        if folder_gone:
            model.gone = f"The resource's folder is gone: {payload.path.parent}"
        elif payload.base is not None and not file_there:
            model.gone = f"The file is gone: {payload.path}"
        LOG.info("Reopened %s with the edits it was left with", payload.path)

    def __read(self) -> list[UnsavedEntry]:
        """Read the kept edits; an entry this build cannot read is logged and dropped.

        :returns: the entries.
        """
        values = read_state_file(self.__path, UNSAVED_CHANGES_VERSION)
        documents = [] if values is None else values.get("documents")
        entries: list[UnsavedEntry] = []
        for item in documents if isinstance(documents, list) else []:
            try:
                payload = SavePayload.from_json(item.get("payload") if isinstance(item, dict) else None)
            except ValueError as error:
                LOG.warning("Kept unsaved edits could not be read and were dropped: %s", error)
                continue
            entries.append(UnsavedEntry(payload, decode_bytes(item.get("layout"))))
        return entries

    def __write(self, entries: list[UnsavedEntry]) -> None:
        """Write the kept edits whole.

        :param entries: what to keep.
        """
        write_state_file(
            self.__path,
            UNSAVED_CHANGES_VERSION,
            {
                "documents": [
                    {"payload": entry.payload.to_json(), "layout": encode_bytes(entry.layout)} for entry in entries
                ]
            },
        )
