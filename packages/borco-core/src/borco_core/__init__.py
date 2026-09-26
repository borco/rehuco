"""borco-core: generic reusable classes with no GUI dependencies."""

from .atomic_write import atomic_write_bytes, atomic_write_text
from .file_holder import FileHolder
from .file_holders import file_holders
from .shared_read import shared_read_open

__version__ = "0.1.0"

__all__ = ["FileHolder", "__version__", "atomic_write_bytes", "atomic_write_text", "file_holders", "shared_read_open"]
