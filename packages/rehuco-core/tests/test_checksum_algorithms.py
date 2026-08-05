"""Tests for the checksum algorithms and the registry a recorded hash's key resolves through (#203).

Correctness is pinned with published test vectors rather than by round-tripping this code against
itself: a recorded hash is a claim about the file that has to hold against every other implementation of
the algorithm, and a round-trip would agree with a wrong one just as happily.
"""

from typing import Final

from pytest import mark, param
from rehuco_core import (
    CHECKSUM_ALGORITHMS,
    CHECKSUM_READ_CHUNK_SIZE,
    DEFAULT_CHECKSUM_ALGORITHM,
)

# published vectors for the empty input and for b"abc" -- GNU coreutils, RFC 1321/3174/6234 and the
# xxHash specification
EMPTY_DIGESTS: Final = {
    "crc32": "00000000",
    "md5": "d41d8cd98f00b204e9800998ecf8427e",
    "sha1": "da39a3ee5e6b4b0d3255bfef95601890afd80709",
    "sha224": "d14a028c2a3a2bc9476102bb288234c415a2b01f828ea62ac5b3e42f",
    "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "sha384": "38b060a751ac96384cd9327eb1b1e36a21fdb71114be07434c0cc7bf63f6e1da274edebfe76f65fbd51ad2f14898b95b",
    "sha512": (
        "cf83e1357eefb8bdf1542850d66d8007d620e4050b5715dc83f4a921d36ce9ce"
        "47d0d13c5d85f2b0ff8318d2877eec2f63b931bd47417a81a538327af927da3e"
    ),
    "xxh3": "2d06800538d394c2",
}

ABC_DIGESTS: Final = {
    "crc32": "352441c2",
    "md5": "900150983cd24fb0d6963f7d28e17f72",
    "sha1": "a9993e364706816aba3e25717850c26c9cd0d89d",
    "sha224": "23097d223405d8228642a477bda255b32aadbce4bda0b3f7e36c9da7",
    "sha256": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    "sha384": "cb00753f45a35e8bb5a03d699ac65007272c32ab0eded1631a8b605a43ff5bed8086072ba1e7cc2358baeca134c825a7",
    "sha512": (
        "ddaf35a193617abacc417349ae20413112e6fa4e89a97ea20a9eeee64b55d39a"
        "2192992a274fc1a836ba3c23a3feebbd454d4423643ce80e2a9ac94fa54ca49f"
    ),
    "xxh3": "78af5f94892f3950",
}


def digest_of(name: str, data: bytes) -> str:
    """Hash ``data`` in one update, the way a test vector is stated.

    :param name: the algorithm's registry name.
    :param data: the bytes to hash.
    :returns: the hex digest.
    """
    digest = CHECKSUM_ALGORITHMS[name].new_digest()
    digest.update(data)
    return digest.hexdigest()


# region Registry tests
def test_registry_is_keyed_by_the_algorithm_name() -> None:
    """A registry entry answers to its own name -- what a stored setting round-trips through.

    **Test steps:**

    * for every entry, check the key equals the algorithm's ``name``.
    """
    assert all(name == algorithm.name for name, algorithm in CHECKSUM_ALGORITHMS.items())


def test_every_registered_algorithm_has_a_vector() -> None:
    """Nothing is registered that no published vector checks (#203).

    The guard on adding one: an algorithm reachable from a setting but never compared against another
    implementation is a hash this app agrees with itself about, and nobody else.

    **Test steps:**

    * compare the registry's names against the two vector tables.
    """
    assert set(CHECKSUM_ALGORITHMS) == set(EMPTY_DIGESTS) == set(ABC_DIGESTS)


def test_crc32_is_always_offered() -> None:
    """CRC-32 is registered ([[data-model#checksums]]).

    Not a speed decision: it is what the existing catalog's `.sfv` files are written in, so an entry
    seeded from one carries a ``crc32`` hash -- and dropping the algorithm would make that entry
    permanently uncheckable.

    **Test steps:**

    * look ``crc32`` up in the registry and check its digest width.
    """
    assert CHECKSUM_ALGORITHMS["crc32"].hex_length == 8


def test_the_default_is_registered() -> None:
    """The default names an algorithm this build actually has (#203).

    Pinned because the default is otherwise a bare string: a typo, or a rename of the entry it points
    at, would fail at the first hash rather than at import.

    **Test steps:**

    * look the default up in the registry.
    """
    assert CHECKSUM_ALGORITHMS[DEFAULT_CHECKSUM_ALGORITHM].name == DEFAULT_CHECKSUM_ALGORITHM


def test_the_read_chunk_is_a_whole_number_of_kibibytes() -> None:
    """The streaming chunk is a sane block size, not an accident.

    **Test steps:**

    * check it is positive and a multiple of 4 KiB.
    """
    assert CHECKSUM_READ_CHUNK_SIZE > 0
    assert CHECKSUM_READ_CHUNK_SIZE % 4096 == 0


# endregion


# region Digest tests
@mark.parametrize("name", [param(name, id=name) for name in EMPTY_DIGESTS])
def test_empty_input_matches_the_published_vector(name: str) -> None:
    """Hashing nothing gives the digest every other implementation gives.

    **Test steps:**

    * hash ``b""``;
    * compare against the published vector.
    """
    assert digest_of(name, b"") == EMPTY_DIGESTS[name]


@mark.parametrize("name", [param(name, id=name) for name in ABC_DIGESTS])
def test_abc_matches_the_published_vector(name: str) -> None:
    """Hashing ``abc`` gives the digest every other implementation gives.

    **Test steps:**

    * hash ``b"abc"``;
    * compare against the published vector.
    """
    assert digest_of(name, b"abc") == ABC_DIGESTS[name]


@mark.parametrize("name", [param(name, id=name) for name in CHECKSUM_ALGORITHMS])
def test_a_digest_is_the_declared_width(name: str) -> None:
    """A digest occupies exactly ``hex_length`` hex digits.

    That width is what tells a well-formed recorded hash from a corrupted or hand-edited one, so a
    declaration disagreeing with the backend would reject every entry the same backend wrote.

    **Test steps:**

    * hash a short input;
    * check the hex length and that every character is a hex digit.
    """
    checksum = digest_of(name, b"rehuco")
    assert len(checksum) == CHECKSUM_ALGORITHMS[name].hex_length
    assert all(character in "0123456789abcdef" for character in checksum)


@mark.parametrize("name", [param(name, id=name) for name in CHECKSUM_ALGORITHMS])
def test_chunked_and_whole_agree(name: str) -> None:
    """Folding a file in chunks gives what folding it whole would give.

    The property streaming rests on: content files are gigabytes and are never read whole
    ([[data-model#checksums]]), so a digest that depended on how the reads happened to split would make
    every verify a coin toss.

    **Test steps:**

    * hash a block in one update, and again in three uneven ones;
    * compare.
    """
    block = bytes(range(256)) * 7
    chunked = CHECKSUM_ALGORITHMS[name].new_digest()
    for piece in (block[:5], block[5:1000], block[1000:]):
        chunked.update(piece)
    assert chunked.hexdigest() == digest_of(name, block)


@mark.parametrize("name", [param(name, id=name) for name in CHECKSUM_ALGORITHMS])
def test_each_call_starts_a_fresh_digest(name: str) -> None:
    """``new_digest`` hands back a new object, never one carrying the last file's bytes.

    The failure this would cause is silent and total: every file after the first would hash as the
    concatenation of everything before it, and a verify would report the whole resource mismatched.

    **Test steps:**

    * take two digests, feed one of them;
    * check the untouched one still answers the empty vector.
    """
    algorithm = CHECKSUM_ALGORITHMS[name]
    first = algorithm.new_digest()
    first.update(b"some content")
    assert algorithm.new_digest().hexdigest() == EMPTY_DIGESTS[name]


# endregion
