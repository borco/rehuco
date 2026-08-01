"""rehuco-core: shared library for models, .rehu I/O, and sync primitives."""

from .collection_entries import CollectionEntry, collection_entries
from .constants import (
    ARCHIVE_EXTENSIONS,
    CHECKSUM_MANIFEST_EXTENSIONS,
    CONTENT_IMAGE_EXTENSIONS,
    EXCLUDED_FILE_PATTERNS,
    IMAGE_EXTENSIONS,
    INFO_REHU_FILENAME,
    REHU_SUFFIX,
)
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
    CORE_FIELD_NAMES,
    CORE_PLUGIN,
    DEFAULT_CURRENT_USERNAME,
    DEFAULT_PLUGIN_REGISTRY,
    DEFAULT_UNKNOWN_USERNAME,
    PUBLIC_USERNAME,
    REFERENCE_IMAGES_FIELD_NAMES,
    REFERENCE_IMAGES_PLUGIN,
    RESOURCE_FIELD_NAMES,
    TUTORIAL_FIELD_NAMES,
    TUTORIAL_PLUGIN,
    USERS_KEY,
    PluginRegistry,
    PluginSpec,
)
from .rehu_content_files import content_size_on_disk, enumerate_content_files
from .rehu_content_images import ContentImageEntry, enumerate_content_images
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
    "ARCHIVE_EXTENSIONS",
    "AuthorEntry",
    "BUILTIN_PLUGINS",
    "CHECKSUM_MANIFEST_EXTENSIONS",
    "COLLECTION_PLUGIN",
    "CONTENT_IMAGE_EXTENSIONS",
    "CORE_BLOCK_KEY",
    "CORE_FIELD_NAMES",
    "CORE_PLUGIN",
    "CURRENT_FORMAT_VERSION",
    "CollectionEntry",
    "ContentImageEntry",
    "DEFAULT_CURRENT_USERNAME",
    "DEFAULT_PLUGIN_REGISTRY",
    "DEFAULT_UNKNOWN_USERNAME",
    "EXCLUDED_FILE_PATTERNS",
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
    "REFERENCE_IMAGES_FIELD_NAMES",
    "REFERENCE_IMAGES_PLUGIN",
    "REHU_SUFFIX",
    "RESERVED_KEYS",
    "RESOURCE_FIELD_NAMES",
    "RehuDocument",
    "RehuFormatError",
    "RehuRenamer",
    "ScreenshotRename",
    "TUTORIAL_FIELD_NAMES",
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
    "content_size_on_disk",
    "convert_tc",
    "current_block_version",
    "enumerate_content_files",
    "enumerate_content_images",
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
