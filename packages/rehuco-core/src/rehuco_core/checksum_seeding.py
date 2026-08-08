"""Seed a ``.checksum`` from the legacy ``.sfv``/``.md5``/``.sha*`` manifest beside it
([[data-model#checksums]], #243).

The existing catalog carries manifests written years ago by a predecessor and by external checkers.
#203 recognizes their suffixes as bookkeeping so they never count as content
(:data:`~rehuco_core.constants.CHECKSUM_MANIFEST_EXTENSIONS`) and writes none of them -- but until this
module nothing *read* one either, so a resource checksummed for years read to this app as a resource
with no checksums at all, and its first verify would have baselined whatever sat on disk today and
called it matched. **The old file is a claim, made when the files were known good**, and this is the
one-way step that turns it into entries the first verify can actually check.

**Seeding produces entries, not verdicts.** Each line becomes a ``{name, <algorithm>: <digest>}`` entry
with no date and no status, which is exactly the shape :meth:`~rehuco_core.rehu_checksums.ChecksumRun.verify`
already knows how to check: present files are hashed and compared under the algorithm the *suffix*
named, an absent one is ``missing`` and **keeps its recorded hash**, and content the old manifest never
listed is adopted the way any unlisted file is. ``only``, ``stale_after``, the progress denominator and
``migrate_to`` therefore compose for free -- there is no second code path for a seeded run.

**Two ways in, and they establish the same thing.** A verify seeds on its way past
(:meth:`~rehuco_core.rehu_checksums.ChecksumRun.verify`) and then hashes everything; :func:`seed_checksum_record`
seeds and stops (#256), writing the record and reading no bytes at all. The second is what a bulk import
runs, once per converted resource: a catalog-wide migration cannot afford to read the library to carry a
claim forward, and it does not have to -- the entries land dateless, a dateless entry is never fresh, and
the next sweep verifies every one of them with nobody tracking which.

**Nothing here writes a legacy manifest, and nothing deletes one.** It is somebody else's data, it
costs nothing, and it stays out of the content set either way; deleting it would also make this step
unrepeatable if the new record were lost. The record's own suffix stays the only one written (#203).

The reading is the mechanical half. The half worth the module is **name normalization**: these files
mix ``\\`` and ``/`` freely, and a name that cannot be normalized into a name *inside* the resource is
reported and dropped, never guessed at.
"""

import logging
import os
import re
from collections.abc import Collection, Iterable
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Any, Final

from .checksum_algorithms import CHECKSUM_ALGORITHMS
from .checksum_record import (
    CHECKSUM_FILES_KEY,
    CHECKSUM_NAME_KEY,
    HEX_DIGEST_PATTERN,
    checksum_entry_name,
    checksum_record_path,
    new_checksum_record,
    save_checksum_record,
)
from .constants import EXCLUDED_FILE_PATTERNS
from .rehu_content_files import enumerate_content_files

LOG: Final = logging.getLogger(__name__)

LEGACY_MANIFEST_ALGORITHMS: Final[dict[str, str]] = {
    ".sha512": "sha512",
    ".sha384": "sha384",
    ".sha256": "sha256",
    ".sha224": "sha224",
    ".sha1": "sha1",
    ".md5": "md5",
    ".sfv": "crc32",
}
"""What each legacy manifest suffix's hashes are, **in precedence order** -- strongest first.

One manifest is read and the rest are reported ignored: merging several is not worth the ambiguity
about which one wins per file, and a silent pick would be worse than a stated one.

Wider than :data:`~rehuco_core.CHECKSUM_ALGORITHMS` on purpose, for the same reason
:data:`~rehuco_core.constants.CHECKSUM_MANIFEST_EXTENSIONS` is: this map is about files that exist on a
disk. A suffix whose algorithm this build does not ship names a file that cannot be seeded from, so it
is skipped over rather than chosen and then failed -- and if the algorithm is ever added back, its
manifests become readable again with no change here."""

SFV_COMMENT: Final = ";"
"""What starts a comment in a ``.sfv``."""

COREUTILS_COMMENT: Final = "#"
"""What starts a comment in an ``md5sum``-shaped manifest."""


@dataclass(frozen=True, slots=True)
class LegacyDrop:
    """One line of a legacy manifest that did not become an entry (#243).

    **A line this build cannot use costs itself**, the way a malformed record entry does (#203): it is
    reported, and the rest of the file still seeds. Both members are for a reader -- a log line, and
    the dock that shows a run's findings -- so the line is carried as read.

    :param line: the line, as it was read.
    :param reason: why it was dropped, as a sentence fragment.
    """

    line: str
    reason: str


@dataclass(frozen=True, slots=True)
class LegacySeed:
    """What one legacy manifest contributed to a record (#243).

    Carried on the run's :class:`~rehuco_core.ChecksumReport`, because a seed is something the run
    *established* about the resource and it happens exactly once in that resource's life: the next
    verify reads the ``.checksum`` this run wrote and never opens the manifest again.

    :param manifest: the file that was read.
    :param entries: the record entries it produced, in the manifest's own order -- each a name and a
        hash under the suffix's algorithm, with no date and no status, which is what makes a seeded run
        a verify rather than a generate.
    :param dropped: the lines that did not become entries.
    :param ignored: the other legacy manifests sitting beside the record, which were **not** read.
    """

    manifest: Path
    entries: tuple[dict[str, Any], ...] = ()
    dropped: tuple[LegacyDrop, ...] = ()
    ignored: tuple[Path, ...] = ()


class LegacyManifestReader:  # pylint: disable=too-few-public-methods
    """Turns one legacy manifest into record entries ([[data-model#checksums]], #243).

    Two line shapes cover everything the catalog holds, and they differ in which end the hash sits at:

    - ``.sfv`` -- ``<filename> <crc32>``, hash **last**. Filenames contain spaces, so a line is split
      from the **right**, never with :meth:`str.split`.
    - ``.md5``/``.sha*`` -- the ``coreutils`` shape, ``<hash> [*]<filename>``, hash **first**, one or
      two spaces, and an optional ``*`` binary marker to strip.

    Nothing new has to be able to hash: every algorithm these suffixes name that this build offers is
    already in :data:`~rehuco_core.CHECKSUM_ALGORITHMS` (#203), and a recorded hash is already compared
    case-insensitively, which is what a ``.sfv``'s uppercase hex needs.

    :param path: the manifest to read; its suffix decides the algorithm and the comment character.
    :param directory: the resource's directory, which a seeded name is resolved against.
    :param content_names: the resource's content file names as the enumeration answers them today
        (#226), record-relative and POSIX-separated.
    """

    __COREUTILS_LINE: Final = re.compile(r"(?P<digest>[0-9a-fA-F]+)[ \t]{1,2}\*?(?P<name>.+)")
    """The ``coreutils`` shape, anchored by :meth:`~re.Pattern.fullmatch`.

    One or two separator characters, then an optional binary marker -- deliberately not
    :meth:`str.split`, which would eat a filename's own leading spaces along with the separator."""

    def __init__(self, path: Path, directory: Path, content_names: Collection[str]) -> None:
        self.__path: Final = path
        self.__directory: Final = directory
        self.__algorithm: Final = LEGACY_MANIFEST_ALGORITHMS[path.suffix.lower()]
        self.__is_sfv: Final = path.suffix.lower() == ".sfv"
        self.__comment: Final = SFV_COMMENT if self.__is_sfv else COREUTILS_COMMENT
        self.__content_names: Final = frozenset(content_names)

    def read(self) -> LegacySeed:
        """Read the manifest whole and turn it into entries.

        :returns: the entries, and every line that did not become one.
        :raises OSError: the manifest could not be read.
        """
        entries: list[dict[str, Any]] = []
        dropped: list[LegacyDrop] = []
        seen: set[str] = set()
        for raw in self.__path.read_bytes().splitlines():
            line = self.__decoded(raw)
            if line is None:
                dropped.append(LegacyDrop(raw.decode("utf-8", errors="replace"), "neither UTF-8 nor cp1252"))
                continue
            line = line.strip()
            if not line or line.startswith(self.__comment):
                continue
            reason = self.__seeded(line, entries, seen)
            if reason is not None:
                dropped.append(LegacyDrop(line, reason))
        return LegacySeed(self.__path, tuple(entries), tuple(dropped))

    def __seeded(self, line: str, entries: list[dict[str, Any]], seen: set[str]) -> str | None:
        """Turn one line into an entry, appending it, or say why it could not be.

        :param line: the line, decoded and stripped, known not to be blank or a comment.
        :param entries: the entries so far, appended to in place.
        :param seen: the names already seeded, added to in place.
        :returns: ``None`` once the entry is appended, else why the line was dropped.
        """
        parsed = self.__parsed(line)
        if parsed is None:
            return "not this manifest's line shape"
        raw_name, digest = parsed
        specification = CHECKSUM_ALGORITHMS[self.__algorithm]
        if len(digest) != specification.hex_length or HEX_DIGEST_PATTERN.fullmatch(digest) is None:
            return f"not a {specification.label} hash"
        name = self.__normalized(raw_name)
        if name is None:
            return "the name does not sit inside the resource"
        if name not in self.__content_names and self.__excluded(name):
            return "a file this resource's content excludes"
        if name in seen:
            return "the name is listed more than once"
        seen.add(name)
        entries.append({CHECKSUM_NAME_KEY: name, self.__algorithm: digest})
        return None

    def __excluded(self, name: str) -> bool:
        """Whether a name the enumeration does not list is one it deliberately left out.

        The distinction the seed turns on, and the reason this is not a plain membership test. A
        predecessor was free to checksum files this app does not -- a screenshot, a ``Thumbs.db``,
        another record's bookkeeping ([[data-model#checksums]]) -- and carrying such an entry would
        make every screenshot edit a permanent ``mismatched`` in a record that can never come clean. A
        name that is simply **not there** is the opposite case: it is the claim about a file that has
        gone, which the run records as ``missing`` with its hash intact so it survives the file's
        return. Both are absent from the enumeration; only the first is excluded by it.

        A file that cannot even be stat-ed answers *not excluded*, which carries the claim -- the same
        direction #245 settled for a branch that would not list.

        :param name: a normalized record-relative name, known not to be content.
        :returns: whether something is there under that name, and the enumeration left it out.
        """
        try:
            return (self.__directory / PurePosixPath(name)).exists()
        except OSError:
            return False

    def __parsed(self, line: str) -> tuple[str, str] | None:
        """Split one line into its name and its hash, whichever end the hash sits at.

        :param line: the line, decoded and stripped.
        :returns: the name as the manifest spells it and the hash, or ``None`` when the line is not
            this manifest's shape at all.
        """
        if self.__is_sfv:
            parts = line.rsplit(None, 1)
            return (parts[0], parts[1]) if len(parts) == 2 else None
        match = self.__COREUTILS_LINE.fullmatch(line)
        return (match["name"], match["digest"]) if match is not None else None

    @staticmethod
    def __decoded(raw: bytes) -> str | None:
        """Read one line's bytes as text, UTF-8 first and cp1252 after.

        These files were written by Windows tools years ago, so a non-ASCII filename in one is a cp1252
        byte sequence rather than invalid UTF-8 to give up on -- and a line that survives neither codec
        is one dropped entry, not a failed seed.

        :param raw: the line's bytes.
        :returns: the decoded line, or ``None`` when neither codec reads it.
        """
        for encoding in ("utf-8", "cp1252"):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
        return None

    @staticmethod
    def __normalized(raw_name: str) -> str | None:
        """Turn a manifest's spelling of a name into the record's, or refuse it.

        The old files mix ``\\`` and ``/`` in the same file, so every separator becomes ``/`` and the
        ``.\\``/``./`` prefixes and ``.`` segments those tools emit are dropped. What comes out must
        satisfy :func:`~rehuco_core.checksum_entry_name`, which refuses an absolute name, a drive
        letter, and a ``..`` that escapes the resource -- so nothing outside the resource is ever
        hashed on the strength of a line in a file this app did not write.

        **A ``\\`` here is always a separator, never part of a filename**: the catalog's names are
        cross-platform by construction (the agent's rename suggestions go through ``pathvalidate``,
        which refuses a backslash outright), so there is no ambiguous case to resolve on POSIX. That
        knowledge lives here rather than in :func:`~rehuco_core.checksum_entry_name`, which stays
        strict: a ``.checksum`` holding a backslash is out of spec whoever wrote it, and a record
        reader that normalized would make one record mean different things to an agent and a node.

        :param raw_name: the name as the manifest spells it.
        :returns: the record-relative POSIX name, or ``None`` when it does not sit inside the resource.
        """
        parts = [part for part in raw_name.strip().replace("\\", "/").split("/") if part != "."]
        return checksum_entry_name({CHECKSUM_NAME_KEY: "/".join(parts)})


def legacy_manifest_candidates(rehu_path: Path) -> list[Path]:
    """Every legacy manifest sitting beside ``rehu_path`` under its own stem, strongest suffix first.

    **Same-stem is what makes it this record's manifest** ([[data-model#resource-scoping]]):
    ``info.sfv`` beside ``info.rehu``, ``foo.md5`` beside ``foo.rehu``. A ``random.sfv`` with no
    ``random.rehu`` is an ordinary file and stays one -- which is the same rule
    :mod:`rehuco_core.rehu_content_files` applies when it decides what is bookkeeping.

    One listing rather than a ``stat`` per suffix, and matched case-insensitively for the reason the
    content walk gives: SMB and macOS both hand back casings Windows never wrote.

    :param rehu_path: the resource's ``.rehu`` file.
    :returns: the manifests, in :data:`LEGACY_MANIFEST_ALGORITHMS`' order; empty when the directory
        holds none or will not list -- an unreadable directory is the caller's business, and by the
        time this is asked a run has already refused over it (#245).
    """
    try:
        with os.scandir(rehu_path.parent) as entries:
            names = [entry.name for entry in entries if entry.is_file()]
    except OSError:
        return []
    return legacy_manifests_among(rehu_path.parent, rehu_path.stem, names)


def legacy_manifests_among(directory: Path, stem: str, names: Iterable[str]) -> list[Path]:
    """Pick ``stem``'s legacy manifests out of a directory listing somebody else already read.

    The same rule :func:`legacy_manifest_candidates` applies, over names rather than over a fresh
    ``scandir``: the bulk import's planner (#191) reads every directory in the tree anyway, so asking it
    what a conversion would carry forward (#256) costs nothing, while a second listing per resource would
    cost a catalog-sized walk over an SMB mount. One rule in one place, two ways of being handed the
    names.

    :param directory: the directory the names were read from, which the answers are built against.
    :param stem: the record's stem -- ``info`` for ``info.rehu``, matched case-insensitively for the
        reason the content walk gives: SMB and macOS both hand back casings Windows never wrote.
    :param names: the directory's file names, as read.
    :returns: the manifests, in :data:`LEGACY_MANIFEST_ALGORITHMS`' order.
    """
    wanted = stem.lower()
    found: dict[str, Path] = {}
    for name in names:
        name_stem, suffix = os.path.splitext(name)
        suffix = suffix.lower()
        if name_stem.lower() == wanted and suffix in LEGACY_MANIFEST_ALGORITHMS:
            found.setdefault(suffix, directory / name)
    return [found[suffix] for suffix in LEGACY_MANIFEST_ALGORITHMS if suffix in found]


def legacy_manifest_for(rehu_path: Path) -> Path | None:
    """The one legacy manifest a seed would read, if there is one.

    Asked by a surface that has to decide whether a verify can start at all: a resource with no
    ``.checksum`` but with a manifest beside it has something to verify against
    (:class:`~rehuco_core.VerifyChecksumsJob`), and refusing it as *no record yet* would send the user
    at a Generate that throws the old claim away.

    :param rehu_path: the resource's ``.rehu`` file.
    :returns: the strongest manifest this build can read, or ``None``.
    """
    return readable_legacy_manifest(legacy_manifest_candidates(rehu_path))


def readable_legacy_manifest(candidates: list[Path]) -> Path | None:
    """Pick the manifest to read out of what sits beside a record.

    The precedence is fixed (:data:`LEGACY_MANIFEST_ALGORITHMS`), and a suffix naming an algorithm this
    build does not ship is passed over rather than chosen and then failed: choosing it would leave a
    resource with a perfectly readable ``.md5`` beside it unseeded because a ``.sha1`` outranks it.

    :param candidates: the manifests, in precedence order, from :func:`legacy_manifest_candidates`.
    :returns: the strongest one this build can read, or ``None``.
    """
    for path in candidates:
        if LEGACY_MANIFEST_ALGORITHMS[path.suffix.lower()] in CHECKSUM_ALGORITHMS:
            return path
    return None


def seed_from_legacy_manifest(rehu_path: Path, content_names: Collection[str]) -> LegacySeed | None:
    """Read ``rehu_path``'s legacy manifest into record entries -- the one-way step (#243).

    :param rehu_path: the resource's ``.rehu`` file, known to have no ``.checksum`` of its own.
    :param content_names: the resource's content file names as the enumeration answers them today
        (#226) -- only content is seeded.
    :returns: what the manifest contributed, or ``None`` when there is none this build can read, or
        when the one there is refused to be read at all: either way the caller is where it was before,
        facing a resource with no record.
    """
    candidates = legacy_manifest_candidates(rehu_path)
    manifest = readable_legacy_manifest(candidates)
    if manifest is None:
        return None
    try:
        seed = LegacyManifestReader(manifest, rehu_path.parent, content_names).read()
    except OSError:
        return None
    return replace(seed, ignored=tuple(path for path in candidates if path != manifest))


def seed_checksum_record(
    rehu_path: Path, *, excluded_patterns: tuple[str, ...] = EXCLUDED_FILE_PATTERNS
) -> LegacySeed | None:
    """Write ``rehu_path``'s ``.checksum`` from the legacy manifest beside it, hashing nothing (#256).

    The seed without the verify: the entries a run would have started from are written straight out, and
    not one byte of content is read. That is what makes it the default step of a bulk import
    ([[acquisition-tooling#tc-to-rehu]]) -- a catalog-wide migration that read every file to carry a
    claim forward would take days, and it does not have to. **The record lands dateless**, which is
    exactly the state a later verify is looking for: a seeded entry carries a hash and no date, a
    dateless entry is never fresh whatever the staleness window, so the next sweep checks every one of
    them with no force asked for and nobody tracking which resources were done.

    **A resource that already has a ``.checksum`` is left alone**, the same one-way rule a verify's
    seeding is under (#243): the record is what supersedes the manifest, and re-seeding over it would
    replace dated verdicts with a years-old claim.

    :param rehu_path: the resource's ``.rehu`` file.
    :param excluded_patterns: filename globs the content walk leaves out (#226), resolved by the caller
        -- only content is seeded, so this decides which of the manifest's lines are dropped as naming
        something this app deliberately does not checksum.
    :returns: what the manifest contributed, or ``None`` when there was nothing to do -- a record is
        already there, or no manifest this build can read yielded an entry. Nothing is written in either
        case.
    :raises ContentUnreachableError: the resource's directory would not list -- refused before the
        manifest is looked for, so an away mount never seeds a record whose every line reads as a claim
        about a file that is gone (#245).
    :raises OSError: the record could not be written.
    """
    record_path = checksum_record_path(rehu_path)
    if record_path.exists():
        return None
    enumeration = enumerate_content_files(rehu_path, excluded_patterns)
    enumeration.require_reachable()
    directory = enumeration.directory
    content_names = [path.relative_to(directory).as_posix() for path in enumeration.files]
    seed = seed_from_legacy_manifest(rehu_path, content_names)
    if seed is None or not seed.entries:
        return None
    record = new_checksum_record()
    record[CHECKSUM_FILES_KEY] = list(seed.entries)
    save_checksum_record(record_path, record)
    return seed


def log_legacy_seed(seed: LegacySeed) -> None:
    """Say line by line what a legacy manifest did not contribute (#243).

    A summary carries the counts; this is where a reader finds out *which* line and *why*, on the
    resource's own log ([[appendices.logging#scopes]]). It runs once in a resource's life -- whether the
    seed came from a verify (#243) or from an import (#256) -- so the detail costs nothing afterwards,
    and both callers say it the same way because it is the same event.

    :param seed: what the manifest contributed.
    """
    for manifest in seed.ignored:
        LOG.info("%s was not read: %s is the manifest this record was seeded from.", manifest, seed.manifest.name)
    for drop in seed.dropped:
        LOG.warning("%s: dropped %r -- %s.", seed.manifest, drop.line, drop.reason)
