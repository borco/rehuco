"""borco-core: generic reusable classes with no GUI dependencies."""

from .atomic_write import atomic_write_bytes, atomic_write_text
from .file_holder import FileHolder
from .file_holders import file_holders
from .path_presence import Device, Presence, PresenceScan, StorageKind, device_of, presence_of
from .shared_read import shared_read_open

__version__ = "0.2.0"

__all__ = [
    "Device",
    "FileHolder",
    "Presence",
    "PresenceScan",
    "StorageKind",
    "__version__",
    "atomic_write_bytes",
    "atomic_write_text",
    "device_of",
    "file_holders",
    "presence_of",
    "shared_read_open",
]
