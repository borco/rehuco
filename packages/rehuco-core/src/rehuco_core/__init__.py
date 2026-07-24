"""rehuco-core: shared library for models, .rehu I/O, and sync primitives."""

from .constants import IMAGE_EXTENSIONS
from .lock_reasons import LockReason, LockReasonKind
from .migrations import (
    CURRENT_FORMAT_VERSION,
    current_block_version,
    migrate_block_data,
    migrate_rehu_data,
)
from .plugins import (
    BUILTIN_PLUGINS,
    COLLECTION_PLUGIN,
    CORE_PLUGIN,
    DEFAULT_CURRENT_USERNAME,
    DEFAULT_PLUGIN_REGISTRY,
    DEFAULT_UNKNOWN_USERNAME,
    REFERENCE_IMAGES_PLUGIN,
    TUTORIAL_PLUGIN,
    USERS_KEY,
    PluginRegistry,
    PluginSpec,
)
from .rehu_document import (
    AuthorEntry,
    PluginBlock,
    RehuDocument,
    RehuFormatError,
    author_name,
    authors_comma_editable,
)
from .rehu_format import CORE_BLOCK_KEY, FORMAT_VERSION_KEY, RESERVED_KEYS
from .rehu_screenshots import scan_rehu_screenshot_files
from .tc_conversion import TcConverter, convert_tc
from .tc_description import TcDescriptionRewriter, rewrite_description_images
from .tc_document import TcDocument, load_tc, tc_to_rehu_data
from .tc_screenshots import ScreenshotRename, TcScreenshotScanner, scan_tc_screenshot_files, scan_tc_screenshots

__version__ = "0.0.1"

__all__ = [
    "BUILTIN_PLUGINS",
    "AuthorEntry",
    "COLLECTION_PLUGIN",
    "CORE_BLOCK_KEY",
    "CORE_PLUGIN",
    "CURRENT_FORMAT_VERSION",
    "DEFAULT_CURRENT_USERNAME",
    "DEFAULT_PLUGIN_REGISTRY",
    "DEFAULT_UNKNOWN_USERNAME",
    "FORMAT_VERSION_KEY",
    "IMAGE_EXTENSIONS",
    "LockReason",
    "LockReasonKind",
    "REFERENCE_IMAGES_PLUGIN",
    "RESERVED_KEYS",
    "TUTORIAL_PLUGIN",
    "USERS_KEY",
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
    "current_block_version",
    "load_tc",
    "migrate_block_data",
    "migrate_rehu_data",
    "rewrite_description_images",
    "scan_rehu_screenshot_files",
    "scan_tc_screenshot_files",
    "scan_tc_screenshots",
    "tc_to_rehu_data",
]
