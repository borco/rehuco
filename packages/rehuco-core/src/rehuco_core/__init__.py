"""rehuco-core: shared library for models, .rehu I/O, and sync primitives."""

from rehuco_core.rehu_document import RehuDocument, RehuFormatError

__version__ = "0.0.1"

__all__ = ["__version__", "RehuDocument", "RehuFormatError"]
