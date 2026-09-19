"""The Content Images dock: a justified-row browse over a reference-images resource's archives (#221).

A document's own surface for the images a reference pack *is* -- its archive members, which have no
path on disk and are never edited ([[data-model#image-meanings]]). The pieces, bottom up:

- `ArchiveCache` -- open archive handles, read through a lock each, so a directory-scoped resource's
  many zips are not opened once per thumbnail.
- `banner_rows` / `banner_text` -- the pure rule for which boundaries get a banner row.
- `pack_rows` -- the pure justified-row packing pass, geometry precomputed for the whole sequence.
- `ContentImagesModel` -- the entries, their dimensions read from headers on demand, and the
  `ArchiveImageSource` the lightbox and the thumbnail loader decode through.
- `ContentImagesView` -- paints the packed rows from the table, requesting only what is in view.
"""

from .archive_cache import ArchiveCache
from .banners import ContentDisplayFlags, banner_rows, banner_text
from .content_images_model import ArchiveImageSource, ContentImagesModel
from .content_images_view import ContentImagesView
from .justified_layout import LayoutItem, PackedLayout, Row, pack_rows

__all__ = [
    "ArchiveCache",
    "ArchiveImageSource",
    "ContentDisplayFlags",
    "ContentImagesModel",
    "ContentImagesView",
    "LayoutItem",
    "PackedLayout",
    "Row",
    "banner_rows",
    "banner_text",
    "pack_rows",
]
