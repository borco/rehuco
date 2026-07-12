"""Shared constants with no single owning module ([[data-model#image-meanings]])."""

from typing import Final

IMAGE_EXTENSIONS: Final = (".jpg", ".jpeg", ".png", ".gif", ".webp")
"""Screenshot file extensions to recognize, case-insensitively -- shared by both the legacy ``.tc``
scanner (:mod:`rehuco_core.tc_screenshots`) and the live ``.rehu`` scanner
(``rehuco_agent.documents.image_scanner``), since a screenshot is a ``.rehu``-level concept (a
numbered sibling of the document itself), not specific to either side of the conversion."""
