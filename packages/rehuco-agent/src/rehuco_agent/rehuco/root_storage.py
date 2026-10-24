"""What a root's folder lives on, as the Roots view says it: the words and the glyphs (#378,
[[mounts-and-storage#rehuco-scope]]).

The storage is detected when a root is mapped on this machine, never chosen. The root card shows it and the Roots view
draws a root by it, so the mapping lives here once.
"""

from typing import Final

from rehuco_core import RootStorage

ROOT_STORAGE_ICONS: Final[dict[RootStorage, str]] = {
    RootStorage.LOCAL: ":/icons/file_browser_folder.svg",
    RootStorage.NETWORK: ":/icons/network.svg",
    RootStorage.REMOVABLE: ":/icons/removable.svg",
    RootStorage.COMPACT_DISK: ":/icons/compact_disk.svg",
}
"""One glyph per storage; all four are present. An unreachable root keeps its glyph and is drawn greyed out -- or,
for a local folder, struck through -- rather than getting a glyph of its own."""

ROOT_STORAGE_LABELS: Final[dict[RootStorage, str]] = {
    RootStorage.LOCAL: "Local folder",
    RootStorage.NETWORK: "Network share",
    RootStorage.REMOVABLE: "Removable drive (USB stick, external disk)",
    RootStorage.COMPACT_DISK: "CD or DVD",
}
"""What the root card calls each storage."""

ROOT_STORAGE_OFFLINE_ROWS: Final[dict[RootStorage, str]] = {
    RootStorage.LOCAL: "Folder not found",
    RootStorage.NETWORK: "Share not connected",
    RootStorage.REMOVABLE: "Drive not connected",
    RootStorage.COMPACT_DISK: "Disc not inserted",
}
"""The one row an unreachable root's column shows, so an away root never reads as an empty one (#245)."""

ROOT_STORAGE_OFFLINE_TOOLTIPS: Final[dict[RootStorage, str]] = {
    RootStorage.LOCAL: "This folder was not found, so it could not be listed. Its resources are kept as they were.",
    RootStorage.NETWORK: "This network share is not connected, so it could not be listed. Its resources are kept "
    "as they were.",
    RootStorage.REMOVABLE: "This drive is not connected, so it could not be listed. Its resources are kept as "
    "they were.",
    RootStorage.COMPACT_DISK: "This disc is not inserted, so it could not be listed. Its resources are kept as "
    "they were.",
}
"""What hovering an unreachable root says."""

FOLDER_NOT_FOUND_ROW: Final = "Folder not found"
"""The one row an unlistable folder under a reachable root shows."""

NOT_MAPPED_ROW: Final = "Not mapped on this machine"
"""The one row a root this machine has no folder for shows, and what the root card says of it (#514)."""
