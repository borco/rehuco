"""rehuco-core: shared library for models, .rehu I/O, and sync primitives."""

from .collection_entries import CollectionEntry, collection_entries
from .constants import IMAGE_EXTENSIONS, INFO_REHU_FILENAME
from .learning_path_entries import LearningPathEntry, visible_learning_paths
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
    PUBLIC_USERNAME,
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
from .rehu_rename import PartialRenameError, RehuRenamer, rehu_rename_conflict, rename_rehu_resource
from .rehu_screenshots import scan_rehu_screenshot_files
from .tc_conversion import TcConverter, convert_tc
from .tc_description import TcDescriptionRewriter, rewrite_description_images
from .tc_document import TcDocument, load_tc, tc_to_rehu_data
from .tc_screenshots import ScreenshotRename, TcScreenshotScanner, scan_tc_screenshot_files, scan_tc_screenshots

__version__ = "0.1.0"

# plain `sorted()` order -- uppercase names, then `__version__`, then the lowercase ones -- so a new
# export has exactly one correct place and no convention to remember (`borco_core.__init__` is the same)
__all__ = [
    "AuthorEntry",
    "BUILTIN_PLUGINS",
    "COLLECTION_PLUGIN",
    "CORE_BLOCK_KEY",
    "CORE_PLUGIN",
    "CURRENT_FORMAT_VERSION",
    "CollectionEntry",
    "DEFAULT_CURRENT_USERNAME",
    "DEFAULT_PLUGIN_REGISTRY",
    "DEFAULT_UNKNOWN_USERNAME",
    "FORMAT_VERSION_KEY",
    "IMAGE_EXTENSIONS",
    "INFO_REHU_FILENAME",
    "LearningPathEntry",
    "LockReason",
    "LockReasonKind",
    "PUBLIC_USERNAME",
    "PartialRenameError",
    "PluginBlock",
    "PluginRegistry",
    "PluginSpec",
    "REFERENCE_IMAGES_PLUGIN",
    "RESERVED_KEYS",
    "RehuDocument",
    "RehuFormatError",
    "RehuRenamer",
    "ScreenshotRename",
    "TUTORIAL_PLUGIN",
    "TcConverter",
    "TcDescriptionRewriter",
    "TcDocument",
    "TcScreenshotScanner",
    "USERS_KEY",
    "__version__",
    "author_name",
    "authors_comma_editable",
    "collection_entries",
    "convert_tc",
    "current_block_version",
    "load_tc",
    "migrate_block_data",
    "migrate_rehu_data",
    "rehu_rename_conflict",
    "rename_rehu_resource",
    "rewrite_description_images",
    "scan_rehu_screenshot_files",
    "scan_tc_screenshot_files",
    "scan_tc_screenshots",
    "tc_to_rehu_data",
    "visible_learning_paths",
]
