"""How fast each checksum algorithm folds bytes (#203), which is the measurement
[[data-model#checksums]] left open.

The spec said CRC-32 was *"subject to change pending benchmarking"* and named no one to do it: the only
benchmarking job it specifies ([[mounts-and-storage#node-benchmark]]) grades a **node's** cold-read
throughput to drive dispatch, and never compares algorithms. This file is that comparison, kept in the
repository rather than run once and thrown away, so the numbers recorded in the spec can be rechecked on
any machine and by anyone who doubts them.

**Nothing here touches a disk, and that is the point.** The read loop moves the same bytes whichever
digest consumes them, so I/O is a constant across every candidate and the only variable worth isolating
is the fold itself. Hashing one fixed in-memory block measures exactly that -- and it makes the result
reproducible, which a run over whatever files happened to be on a share is not.

Measures what the app ships (:data:`~rehuco_core.CHECKSUM_ALGORITHMS`) rather than a private list, so
what is measured and what runs cannot drift apart -- and so a candidate that is *not* shipped is measured
by editing the registry, which is the same decision seen from the other side. Marked
``checksum_benchmark``, which ``pytest-explicit`` keeps out of ``make tests`` and ``make cov`` --
``make checksum-bench`` runs it.
"""

from random import Random
from typing import Final

from pytest import fixture, mark, param
from rehuco_core import CHECKSUM_ALGORITHMS, CHECKSUM_READ_CHUNK_SIZE, ChecksumAlgorithm

BLOCK_SIZE: Final = 64 << 20
"""How many bytes each round folds -- large enough that per-call overhead and timer granularity
disappear against the fold, small enough to stay resident on any machine that can run the app."""

BLOCK_SEED: Final = 20260803
"""Fixed, so every run on every machine hashes the same bytes. Incompressible input matters for nothing
here -- no candidate is data-dependent -- but a constant block removes the question."""

CHUNK_SIZES: Final = (64 << 10, 256 << 10, 1 << 20, 4 << 20, 16 << 20)
"""The sweep that picks :data:`~rehuco_core.CHECKSUM_READ_CHUNK_SIZE`. Only per-``update`` call overhead
varies across it; the fold does identical work, so the knee is visible without reading a file."""

SWEEP_ALGORITHMS: Final = ("crc32", "sha256")
"""Swept rather than the whole registry: the cheapest fold, where call overhead is the largest share of
the time, and a mid-cost one to confirm the knee is not an artifact of the cheap case."""


@fixture(scope="module", name="block")
def fixture_block() -> bytes:
    """The one block every measurement folds.

    Module-scoped: generating 64 MiB per test would dwarf what is being measured.

    :returns: :data:`BLOCK_SIZE` deterministic pseudo-random bytes.
    """
    return Random(BLOCK_SEED).randbytes(BLOCK_SIZE)  # nosec B311  # a fixed test block, not a secret


def fold(algorithm: ChecksumAlgorithm, block: bytes, chunk_size: int) -> str:
    """Hash ``block`` the way a file is hashed -- one chunk at a time.

    Chunks are taken through a ``memoryview`` so that no measurement pays for a copy the real read loop
    never makes: there, each chunk arrives as its own ``bytes`` straight from the file.

    :param algorithm: the algorithm under measurement.
    :param block: the bytes to fold.
    :param chunk_size: how much to hand to ``update`` at a time.
    :returns: the hex digest, so nothing in the loop can be optimized away.
    """
    digest = algorithm.new_digest()
    view = memoryview(block)
    for start in range(0, len(view), chunk_size):
        digest.update(view[start : start + chunk_size])
    return digest.hexdigest()


@mark.checksum_benchmark
@mark.parametrize("name", [param(name, id=name) for name in CHECKSUM_ALGORITHMS])
def test_algorithm_throughput(benchmark, block: bytes, name: str) -> None:
    """Measure one algorithm's fold over the shared block, at the shipped chunk size.

    Comparable across the row because every candidate reads the same bytes through the same loop, so the
    times differ in the digest and nothing else. Throughput is the block size over the reported time --
    64 MiB in 100 ms is 640 MB/s.

    **Test steps:**

    * fold :data:`BLOCK_SIZE` bytes at :data:`~rehuco_core.CHECKSUM_READ_CHUNK_SIZE` per ``update``;
    * record the block size beside the timing, so a report read later carries its own units.
    """
    algorithm = CHECKSUM_ALGORITHMS[name]
    benchmark.extra_info["block_bytes"] = BLOCK_SIZE
    benchmark.extra_info["chunk_bytes"] = CHECKSUM_READ_CHUNK_SIZE
    benchmark(fold, algorithm, block, CHECKSUM_READ_CHUNK_SIZE)


@mark.checksum_benchmark
@mark.parametrize("name", [param(name, id=name) for name in SWEEP_ALGORITHMS])
@mark.parametrize("chunk_size", [param(size, id=f"{size >> 10}KiB") for size in CHUNK_SIZES])
def test_chunk_size_sweep(benchmark, block: bytes, name: str, chunk_size: int) -> None:
    """Measure the same fold at each candidate chunk size, to place the knee.

    The read loop's chunk size is a real choice -- too small and the per-``update`` call dominates a
    cheap fold, too large and a gigabyte-scale file holds a buffer nobody needed -- and it is decidable
    without I/O, because only the call count changes.

    **Test steps:**

    * fold the shared block at ``chunk_size`` per ``update``;
    * compare the row: the knee is the smallest size past which the time stops falling.
    """
    algorithm = CHECKSUM_ALGORITHMS[name]
    benchmark.extra_info["block_bytes"] = BLOCK_SIZE
    benchmark.extra_info["chunk_bytes"] = chunk_size
    benchmark(fold, algorithm, block, chunk_size)
