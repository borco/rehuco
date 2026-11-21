"""What a document restored before its storage answered is waiting for (#698)."""

from enum import StrEnum


class StorageWait(StrEnum):
    """Why a document the session restored is not read yet: its file is on storage that has to be asked first -- a
    share, a removable drive -- and reading it unasked would hold a thread for as long as a switched-off server takes
    to time out ([[mounts-and-storage#offline-mounts]])."""

    ASKING = "asking"
    """The storage was asked and has not answered yet."""

    OFFLINE = "offline"
    """The storage did not answer. It is asked again each time the document's tab is shown."""
