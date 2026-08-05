"""The checksum algorithms a ``.checksum`` entry can be hashed with ([[data-model#checksums]], #203).

[[data-model#checksums]] asks the record to say **which algorithm was used** per entry, so that a future
switch neither invalidates nor migrates what is already checksummed. The record does that literally: an
entry's hash sits under a key named for its algorithm, and this module is what those names mean. Two
resources, or two files in one resource, may legitimately carry different ones.

**Every backend is a hard dependency, imported at the top like any other.** The set is closed -- an
algorithm is added by editing this file, never by dropping a package into an install -- so there is
nothing for a plugin mechanism to buy. What a record written by some *other* build names, and this one
has no entry for, is a question for whoever reads the record; it is not answered by keeping an entry here
that cannot hash anything.
"""

import hashlib
import zlib
from collections.abc import Buffer, Callable
from dataclasses import dataclass
from functools import partial
from typing import Final, Protocol

import xxhash


class ChecksumDigest(Protocol):
    """The part of a ``hashlib`` object this module needs -- accumulate bytes, then read the hex.

    Written as a protocol rather than taking ``hashlib._Hash`` so that :class:`Crc32Digest` and
    ``xxhash``'s objects are the same kind of thing to every caller.
    """

    def update(self, data: Buffer, /) -> None:
        """Fold one more chunk of the file into the digest."""

    def hexdigest(self) -> str:  # pyright: ignore[reportReturnType]
        """The digest so far, as lowercase hex -- what a record entry stores, and compares."""


class Crc32Digest:
    """``zlib.crc32`` behind :class:`ChecksumDigest` ([[data-model#checksums]]).

    CRC-32 is a checksum rather than a hash and ``zlib`` exposes it as a fold over an integer, not as an
    object; this is the dozen lines that let the algorithm the legacy catalog's ``.sfv`` files are
    written in travel the same path as every other.
    """

    def __init__(self) -> None:
        self.__value = 0

    def update(self, data: Buffer, /) -> None:
        """Fold ``data`` into the running value."""
        self.__value = zlib.crc32(data, self.__value)

    def hexdigest(self) -> str:
        """The running value as 8 lowercase hex digits, zero-padded -- the shape every other digest
        here answers in, so a record entry never has to know which algorithm wrote it to compare it."""
        return f"{self.__value:08x}"


@dataclass(frozen=True, slots=True)
class ChecksumAlgorithm:
    """One way to compute a content checksum.

    A record of four facts rather than a class hierarchy: the algorithms differ only in which callable
    starts a digest, and three subclasses to express that was three subclasses too many.

    :param name: the stable identifier -- the key an entry's hash is stored under, and what a setting
        stores. **Written into files the user already has**, so renaming one orphans every hash recorded
        under the old spelling.
    :param label: how the algorithm is named to a user, in the settings page that chooses one (#242).
    :param hex_length: how many hex digits a digest occupies -- what tells a well-formed recorded hash
        from a corrupted or hand-edited one.
    :param new_digest: starts a fresh digest for one file.
    """

    name: str
    label: str
    hex_length: int
    new_digest: Callable[[], ChecksumDigest]


CHECKSUM_ALGORITHMS: Final[dict[str, ChecksumAlgorithm]] = {
    algorithm.name: algorithm
    for algorithm in (
        ChecksumAlgorithm("crc32", "CRC-32", 8, Crc32Digest),
        # usedforsecurity=False on all of them: these detect a corrupted download or a bad disk, and
        # never authenticate anything. It is also what lets MD5 build at all on a FIPS-enforcing build.
        ChecksumAlgorithm("md5", "MD5", 32, partial(hashlib.md5, usedforsecurity=False)),
        ChecksumAlgorithm("sha1", "SHA-1", 40, partial(hashlib.sha1, usedforsecurity=False)),
        ChecksumAlgorithm("sha224", "SHA-224", 56, partial(hashlib.sha224, usedforsecurity=False)),
        ChecksumAlgorithm("sha256", "SHA-256", 64, partial(hashlib.sha256, usedforsecurity=False)),
        ChecksumAlgorithm("sha384", "SHA-384", 96, partial(hashlib.sha384, usedforsecurity=False)),
        ChecksumAlgorithm("sha512", "SHA-512", 128, partial(hashlib.sha512, usedforsecurity=False)),
        ChecksumAlgorithm("xxh3", "XXH3 (64-bit)", 16, xxhash.xxh3_64),
    )
}
"""Every algorithm this build can hash with, by :attr:`ChecksumAlgorithm.name`.

What a recorded hash's key resolves through, and what the settings page (#242) offers. The SHA-2 family
and MD5 are here for nothing but the cost of naming them: they are what a legacy ``.md5``/``.sha256``
manifest holds, so an entry seeded from one stays checkable."""

DEFAULT_CHECKSUM_ALGORITHM: Final = "xxh3"
"""The algorithm used when a caller names none, and what a migrating verify moves entries onto.

Measured rather than assumed ([[data-model#checksums]] left this open and named nobody to settle it;
``test_checksum_algorithms_benchmark`` is the comparison and the spec records the table): **XXH3 folds
22.9 GB/s**, against CRC-32's 9.4, SHA-256's 2.1 and MD5's 0.95. Nothing outside this app reads a
``.checksum``, so there is no interop left to trade the speed against -- which is exactly why the earlier
answer to this question was CRC-32 and is no longer.

Every candidate is far above any disk this reads from, so a sweep is I/O-bound either way; what the choice
actually buys is headroom on the day the storage is not the bottleneck."""

CHECKSUM_READ_CHUNK_SIZE: Final = 1 << 20
"""How many bytes are read and folded in at a time.

Content files run to gigabytes, so they are streamed rather than read whole. Measured over a 64 KiB-to-16
MiB sweep: below 256 KiB the per-``update`` call is visible on the cheapest fold (CRC-32 costs 4% more at
64 KiB), and above it nothing changes but the resident buffer. 1 MiB sits inside that flat region with
room on either side."""
