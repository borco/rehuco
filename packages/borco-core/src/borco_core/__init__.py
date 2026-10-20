"""borco-core: generic reusable classes with no GUI dependencies."""

from .absolute_path import absolute_path
from .atomic_write import atomic_write_bytes, atomic_write_text
from .file_holder import FileHolder
from .file_holders import file_holders
from .path_presence import Device, Presence, PresenceScan, StorageKind, device_of, presence_of
from .retry_refused import retry_refused
from .shared_read import shared_read_open
from .text_search import TextMatcher, fold, read_value, search_terms

__version__ = "0.3.0"

__all__ = [
    "Device",
    "FileHolder",
    "Presence",
    "PresenceScan",
    "StorageKind",
    "TextMatcher",
    "__version__",
    "absolute_path",
    "atomic_write_bytes",
    "atomic_write_text",
    "device_of",
    "file_holders",
    "fold",
    "presence_of",
    "read_value",
    "retry_refused",
    "search_terms",
    "shared_read_open",
]
