"""Shared constants with no single owning module ([[data-model#image-meanings]])."""

from typing import Final

REHU_SUFFIX: Final = ".rehu"
"""A resource record's file extension ([[data-model#rehu-format]]) -- what makes a file *a resource*
rather than one of the files a resource is named after, which is the distinction a stem-wide sweep
(:mod:`rehuco_core.rehu_rename`) turns on."""

INFO_REHU_FILENAME: Final = "info.rehu"
"""A directory-scoped resource's filename ([[data-model#resource-scoping]]) -- the one name that says a
``.rehu`` describes the directory it sits in rather than a file beside it. Shared by whatever must tell
the two scopes apart: the agent's display label and rename-target name, and the rename plan
(:mod:`rehuco_core.rehu_rename`), which renames a parent directory for this name and a sibling set for
any other."""

IMAGE_EXTENSIONS: Final = (".jpg", ".jpeg", ".png", ".gif", ".webp")
"""Screenshot file extensions to recognize, case-insensitively -- shared by both the legacy ``.tc``
scanner (:mod:`rehuco_core.tc_screenshots`) and the live ``.rehu`` scanner
(:mod:`rehuco_core.rehu_screenshots`), since a screenshot is a ``.rehu``-level concept (a
numbered sibling of the document itself), not specific to either side of the conversion."""

ARCHIVE_EXTENSIONS: Final = (".zip", ".cbz")
"""Archive file extensions to recognize, case-insensitively, as a reference-images resource's content
([[data-model#resource-scoping]]) -- a ``.cbz`` is the same zip container under another name, so it is
registered and opened everywhere a ``.zip`` is: the shell verb and ``RegistryPage`` entry
(:mod:`rehuco_agent.archives`, #43) and the content-image enumeration
(:mod:`rehuco_core.rehu_content_images`). One constant serves both uses deliberately."""

CHECKSUM_RECORD_SUFFIX: Final = ".checksum"
"""A checksum record's file extension ([[data-model#checksums]], #203) -- the ``<record>.checksum``
sibling holding each content file's hash, when it was last verified and what the answer was
(:mod:`rehuco_core.checksum_record`). The **only** one of
:data:`CHECKSUM_MANIFEST_EXTENSIONS` this build ever writes, which is why it is named on its own."""

CHECKSUM_MANIFEST_EXTENSIONS: Final = (
    CHECKSUM_RECORD_SUFFIX,
    ".md5",
    ".sfv",
    ".sha1",
    ".sha224",
    ".sha256",
    ".sha384",
    ".sha512",
)
"""A checksum record's file extensions, case-insensitively ([[data-model#resource-scoping]]) -- the
``<record>.<extension>`` sibling that records a resource's content hashes, so
:mod:`rehuco_core.rehu_content_files` can keep one out of the content it describes.

**Only ``.checksum`` is written** ([[data-model#checksums]], #203): one JSON record per resource, holding
each file's hash, when it was last verified and what the answer was -- which no single-algorithm manifest
format can express. The rest are what a predecessor or an external checker such as ``cfv`` leaves beside
a resource, listed here so a catalog that already carries them never counts one as content. Recognizing
more than is written is the safe direction; the reverse would make a size scan and a verify disagree
about the same directory.

**Deliberately wider than :data:`~rehuco_core.CHECKSUM_ALGORITHMS`**, and not to be trimmed to match it:
this list is about files that exist on a disk, that one is about hashes this build can compute. A
``foo.sha1`` sitting beside ``foo.rehu`` is bookkeeping whether or not anything here can still verify
SHA-1, and dropping it from here would silently turn it into content the size scan counts."""

CONTENT_IMAGE_EXTENSIONS: Final = (".jpg", ".jpeg", ".png", ".webp", ".avif")
"""Default image extensions to recognize inside a reference-images resource's archive(s), case-insensitively
([[data-model#image-meanings]]) -- distinct from :data:`IMAGE_EXTENSIONS`, since a content image is a
monolithic, checksummed archive member, never a screenshot. What
:func:`~rehuco_core.rehu_content_images.enumerate_content_images` falls back to when no set is given; the
agent's ``ReferenceImagesSettings`` (#222) is what makes the set the user's to change."""

VIDEO_EXTENSIONS: Final = (
    ".asf",
    ".avi",
    ".flv",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".ts",
    ".vob",
)
"""Default video file extensions to recognize inside a tutorial's content, case-insensitively
([[field-schema#duration-size]], #224) -- the set tc4 measured durations over, carried across unchanged.
What :func:`~rehuco_core.rehu_content_duration.content_duration` falls back to when no set is given; the
agent's ``VideosSettings`` (#225) is what makes the set the user's to change. A container this omits is
skipped by the sum rather than probed and reported as zero, so adding one is a preference change rather
than a rebuild."""

EXCLUDED_FILE_PATTERNS: Final = ("Thumbs.db", "ehthumbs.db", "desktop.ini", ".DS_Store", "._*")
"""Default filename globs to leave out of a directory-scoped resource's content, matched
case-insensitively against the *file name* ([[data-model#checksums]], #226) -- what the OS and other
tools leave behind, none of it content, all of it changing a size and a checksum without anyone touching
the resource. ``Thumbs.db`` earns its place because Windows still writes per-folder thumbnail caches on
network shares, and this catalog lives on one ([[packaging-deployment#ts230-as-nas]]); ``._*`` is the
macOS AppleDouble residue that appears for the same reason.

What :func:`~rehuco_core.rehu_content_files.enumerate_content_files` falls back to when no set is given;
the agent's ``ExcludedFilesSettings`` (#226) is what makes the set the user's to change. The *structural*
exclusions -- the record, its screenshots, its checksum manifest -- are not listed here and are not the
user's: :mod:`rehuco_core.rehu_content_files` derives them from *every* record it finds while scanning --
the resource's own and any nested or neighboring one's -- and applies them whatever this set says."""
