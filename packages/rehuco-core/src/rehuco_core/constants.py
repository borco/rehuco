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

CONTENT_IMAGE_EXTENSIONS: Final = (".jpg", ".jpeg", ".png", ".webp", ".avif")
"""Default image extensions to recognize inside a reference-images resource's archive(s), case-insensitively
([[data-model#image-meanings]]) -- distinct from :data:`IMAGE_EXTENSIONS`, since a content image is a
monolithic, checksummed archive member, never a screenshot. What
:func:`~rehuco_core.rehu_content_images.enumerate_content_images` falls back to when no set is given; the
settings page (#222) is what actually makes the set configurable."""
