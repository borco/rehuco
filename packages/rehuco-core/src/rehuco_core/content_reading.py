"""Reading a content file in chunks, through a rename that happens while you are reading it (#241).

**A job iterates chunks and contains no rename logic at all.** That is the whole point of this module:
the letting-go, the waiting, the re-resolving and the seeking back are one loop written once, so a
checksum run ([[data-model#checksums]]) -- or a future scraper saving a download into the resource's
*current* directory -- reads a file the same way it would read any other and survives the folder moving
underneath it.

The loop, once per interruption:

1. take a hold (:meth:`~rehuco_core.RenameCoordinator.holding`), open the file, read chunks;
2. between chunks, check :attr:`~rehuco_core.RenameCoordinator.yield_wanted`;
3. when it is set, close the handle, leave the hold -- which is what lets the rename run -- and come
   straight back to step 1, where the hold blocks until the rename is done;
4. re-open at whatever the :class:`~rehuco_core.ResourceLocation` now says, seek back to the byte we
   had reached, carry on.

Measured at **6.8 to 7.6 ms** per interruption and byte-identical to an uninterrupted pass, which is
what makes "a rename never waits for a job" affordable: the cost is one chunk read, not one file.

**Closing is conditional; taking part is not.** Where
:func:`~rehuco_core.readers_must_yield_for_directory_rename` says the storage does not lock, step 3
skips the close and keeps the handle -- the rename succeeds regardless there, and an open descriptor
goes on reading the file it was opened on. Leaving and re-entering the hold still happens, because that
is the acknowledgement the rename is waiting for; a reader that skipped it would keep every rename
waiting until its ceiling ran out.

**What this does not detect:** a file replaced out of band while the read is in flight. Seeking back to
an offset in a file somebody else has since truncated yields a short read and therefore a wrong answer.
That is not specific to the yield -- it is true of any long read of a file another process may rewrite,
and the window a rename adds to it is milliseconds. Out-of-band change is
[[mounts-and-storage#out-of-band]]'s to notice, not this loop's.
"""

from collections.abc import Generator
from io import BufferedReader
from typing import Final

from borco_core import shared_read_open

from .checksum_algorithms import CHECKSUM_READ_CHUNK_SIZE
from .rename_coordination import RenameCoordinator, ResourceLocation
from .storage_traits import readers_must_yield_for_directory_rename

DEFAULT_CONTENT_CHUNK_SIZE: Final = CHECKSUM_READ_CHUNK_SIZE
"""How much is read at a time unless a caller says otherwise.

The same figure :data:`~rehuco_core.CHECKSUM_READ_CHUNK_SIZE` was measured at, and deliberately the
same object rather than a second constant that could drift from it: what that measurement found is the
size at which per-call overhead has disappeared and the resident buffer has not yet started to matter,
which is a fact about *reading* rather than about hashing. Aliased under a reading-shaped name so a
caller that never hashes anything -- a scraper checking a download -- does not have to import a checksum
constant to say how much to read."""


def read_content_chunks(
    location: ResourceLocation,
    coordinator: RenameCoordinator,
    chunk_size: int = DEFAULT_CONTENT_CHUNK_SIZE,
) -> Generator[bytes]:
    """Yield ``location``'s bytes a chunk at a time, standing aside for any rename that wants through.

    Takes a :class:`~rehuco_core.ResourceLocation` rather than a ``Path`` because the path is exactly
    what a rename changes: re-read at every re-open, it is what makes the read continue at the new
    location instead of failing at the old one.

    **Deliberately not a checkpoint** ([[appendices.task-queue#job-responsibility]]). A job still calls
    its own :meth:`~rehuco_core.tasks.TaskJobBase.checkpoint` between chunks to obey a pause or a
    cancel; this loop only ever pauses and continues, and never raises to stop. Merging the two would
    make a rename look to a job like a cancellation.

    The handle is closed on the way out however the iteration ends -- exhausted, abandoned part-way, or
    unwound by an exception -- so a consumer that stops reading never leaves a rename blocked behind it.

    :param location: the file to read, as a location that follows renames.
    :param coordinator: the barrier to take part in.
    :param chunk_size: how many bytes to read at a time.
    :returns: a generator over the file's chunks, in order; the last may be short, and an empty file
        yields nothing at all.
    :raises OSError: the file could not be opened -- at the first chunk, or at a re-open if the rename
        left it somewhere this location does not name.
    """
    must_close = readers_must_yield_for_directory_rename(location.path)
    handle: BufferedReader | None = None
    offset = 0
    while True:
        with coordinator.holding():
            # every exit below closes *inside* the hold. Leaving the block is what releases a waiting
            # rename, so a close that happened after it would hand the rename a directory with a live
            # handle still under it -- the exact refusal this module exists to avoid. EOF is the
            # common case, not a corner: it is the end of every file. The only handle that ever
            # crosses the block's edge is the one `must_close` says may: on storage that does not
            # lock, it is carried over the gap and back in, and its EOF still closes in a hold.
            try:
                if handle is None:
                    handle = shared_read_open(location.path)
                    handle.seek(offset)
                while not coordinator.yield_wanted:
                    chunk = handle.read(chunk_size)
                    if not chunk:
                        handle.close()
                        return
                    offset += len(chunk)
                    yield chunk
            except BaseException:
                # an abandoned consumer (GeneratorExit lands at the yield), a failed read, or a
                # failed seek. BaseException on purpose, and re-raised: nothing is swallowed, the
                # handle just must not outlive the hold on the way out.
                if handle is not None:
                    handle.close()
                raise
            if must_close:
                handle.close()
                handle = None
        # the hold is released here, and re-taken at the top: this gap is the rename's whole
        # opportunity, and re-entering blocks until it has finished and rewritten `location`.
