"""borco-core: generic reusable classes with no GUI dependencies."""

from .atomic_write import atomic_write_bytes, atomic_write_text
from .file_holder import FileHolder
from .file_holders import file_holders
from .path_presence import Device, Presence, PresenceScan, StorageKind, device_of, presence_of
from .shared_read import shared_read_open
from .text_search import TextMatcher, fold, read_value, search_terms

__version__ = "0.2.0"

__all__ = [
    "Device",
    "FileHolder",
    "Presence",
    "PresenceScan",
    "StorageKind",
    "TextMatcher",
    "__version__",
    "atomic_write_bytes",
    "atomic_write_text",
    "device_of",
    "file_holders",
    "fold",
    "presence_of",
    "read_value",
    "search_terms",
    "shared_read_open",
]
