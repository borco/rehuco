"""borco-core: generic reusable classes with no GUI dependencies."""

from .atomic_write import atomic_write_bytes, atomic_write_text

__version__ = "0.1.0"

__all__ = ["__version__", "atomic_write_bytes", "atomic_write_text"]
