"""rehuco-core: shared library for models, .rehu I/O, and sync primitives."""

from rehuco_core.constants import IMAGE_EXTENSIONS
from rehuco_core.lock_reasons import LockReason, LockReasonKind
from rehuco_core.migrations import CURRENT_FORMAT_VERSION, migrate_block_data, migrate_rehu_data
from rehuco_core.plugins import (
    BUILTIN_PLUGINS,
    COLLECTION_PLUGIN,
    CORE_BLOCK_KEY,
    CORE_PLUGIN,
    DEFAULT_PLUGIN_REGISTRY,
    FORMAT_VERSION_KEY,
    REFERENCE_IMAGES_PLUGIN,
    RESERVED_KEYS,
    TUTORIAL_PLUGIN,
    PluginRegistry,
    PluginSpec,
)
from rehuco_core.rehu_document import (
    AuthorEntry,
    PluginBlock,
    RehuDocument,
    RehuFormatError,
    author_name,
    authors_comma_editable,
)
from rehuco_core.tc_conversion import TcConverter, convert_tc
from rehuco_core.tc_description import TcDescriptionRewriter, rewrite_description_images
from rehuco_core.tc_document import TcDocument, load_tc, tc_to_rehu_data
from rehuco_core.tc_screenshots import ScreenshotRename, TcScreenshotScanner, scan_tc_screenshots

__version__ = "0.0.1"

__all__ = [
    "BUILTIN_PLUGINS",
    "AuthorEntry",
    "COLLECTION_PLUGIN",
    "CORE_BLOCK_KEY",
    "CORE_PLUGIN",
    "CURRENT_FORMAT_VERSION",
    "DEFAULT_PLUGIN_REGISTRY",
    "FORMAT_VERSION_KEY",
    "IMAGE_EXTENSIONS",
    "LockReason",
    "LockReasonKind",
    "REFERENCE_IMAGES_PLUGIN",
    "RESERVED_KEYS",
    "TUTORIAL_PLUGIN",
    "__version__",
    "PluginBlock",
    "PluginRegistry",
    "PluginSpec",
    "RehuDocument",
    "RehuFormatError",
    "ScreenshotRename",
    "author_name",
    "authors_comma_editable",
    "TcConverter",
    "TcDescriptionRewriter",
    "TcDocument",
    "TcScreenshotScanner",
    "convert_tc",
    "load_tc",
    "migrate_block_data",
    "migrate_rehu_data",
    "rewrite_description_images",
    "scan_tc_screenshots",
    "tc_to_rehu_data",
]
