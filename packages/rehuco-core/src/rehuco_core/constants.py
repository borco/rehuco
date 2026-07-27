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
