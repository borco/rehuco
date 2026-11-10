"""Hashing one content file in a single read, through any rename that happens meanwhile (#203, #241, #339).

What a checksum run ([[data-model#checksums]]) and a verified copy ([[mounts-and-storage#safe-move-rename]]) both do
to a file: read it once through :func:`~rehuco_core.read_content_chunks`, feed every digest asked for from the same
bytes, and stop between chunks when told to. Spelled once, so the two cannot disagree on what a file's hash is.
"""

from collections.abc import Callable

from .checksum_algorithms import CHECKSUM_ALGORITHMS, ChecksumDigest
from .content_reading import read_content_chunks
from .rename_coordination import RenameCoordinator, ResourceLocation


def digest_content(
    location: ResourceLocation,
    algorithms: tuple[str, ...],
    coordinator: RenameCoordinator,
    *,
    on_chunk: Callable[[int], None] | None = None,
    checkpoint: Callable[[], None] | None = None,
) -> list[str]:
    """Read one file whole, feeding every named digest from the same pass.

    However many algorithms are asked for, the bytes move once -- the single-read guarantee a checksum migration rests
    on (#203). The checkpoint runs before the first chunk and after every one, and whatever it raises leaves through
    here uncaught.

    :param location: the file, tracked across renames.
    :param algorithms: the algorithm names to feed; each one this build ships (:data:`CHECKSUM_ALGORITHMS`).
    :param coordinator: the rename barrier to read through.
    :param on_chunk: told how many bytes each chunk held, after the digests have taken it -- how a caller counts its
        progress.
    :param checkpoint: the caller's place to stop, never caught here.
    :returns: the hex digests, in ``algorithms``' order.
    :raises KeyError: an algorithm this build does not ship.
    :raises OSError: the file could not be opened or read.
    """
    digests: list[ChecksumDigest] = [CHECKSUM_ALGORITHMS[name].new_digest() for name in algorithms]
    if checkpoint is not None:
        checkpoint()
    chunks = read_content_chunks(location, coordinator)
    try:
        for chunk in chunks:
            for digest in digests:
                digest.update(chunk)
            if on_chunk is not None:
                on_chunk(len(chunk))
            if checkpoint is not None:
                checkpoint()
    finally:
        chunks.close()
    return [digest.hexdigest() for digest in digests]
