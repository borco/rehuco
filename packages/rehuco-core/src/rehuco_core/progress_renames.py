"""A renamed video takes its watch progress, notes and favorite with it ([[field-schema#watch-progress]], #411,
[[field-schema#video-notes]], #571).

What a user keeps about a video -- the *data* of :func:`~rehuco_core.watch_progress.video_data_keys` -- is keyed by
its file's path, so renaming the file -- or the folder holding it -- leaves the data *missing* and the file under its
new name bare. When a keyed file is missing and one with no data at all is on disk anywhere in the resource, the
strongest evidence available decides whether the data moves:

1. **A hash recorded for the missing file** in its ``.checksum`` ([[data-model#checksums]]): each candidate is
   hashed, and only an equal hash moves the entry. No setting is involved, and equal sizes are told apart here.
2. **No usable hash** -- the record is absent, broken, or never covered that file: **exactly one** candidate with
   the same size, and the same duration when both are known, moves the entry, when the host's setting *match
   renamed files by size when no checksum is recorded* is on.
3. Anything else moves nothing; the entry stays missing for the user to reattach or forget.

Choosing wrongly moves one file's viewing history onto another, so every rung is exact: the size recorded when its
file was played (:attr:`~rehuco_core.ProgressEntry.size`) or noted or starred
(:data:`~rehuco_core.watch_progress.VIDEO_SIZES_KEY`) narrows the candidates on both rungs -- which is also what keeps
the hash rung from reading every unwatched video at each listing -- data without one never moves, a candidate that
could not be read leaves its rung undecided, and two missing files claiming one candidate move neither.
:func:`plan_progress_renames` is the ladder, pure; :func:`reattach_renamed_progress` gathers its
evidence off disk and writes the moves.
"""

import logging
from collections import Counter
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from borco_core import shared_read_open

from .checksum_algorithms import CHECKSUM_ALGORITHMS, CHECKSUM_READ_CHUNK_SIZE
from .checksum_record import (
    CHECKSUM_FILES_KEY,
    ChecksumEntry,
    ChecksumRecordError,
    checksum_record_path,
    load_checksum_record,
    parse_checksum_entry,
)
from .constants import EXCLUDED_FILE_PATTERNS, VIDEO_EXTENSIONS
from .content_keys import content_key, content_path, is_valid_content_key
from .plugins import DEFAULT_CURRENT_USERNAME, DEFAULT_PLUGIN_REGISTRY, TUTORIAL_PLUGIN, PluginRegistry
from .record_merge import merge_write
from .rehu_content_duration import VideoFacts, content_video_files
from .rehu_document import RehuDocument
from .watch_progress import (
    END_TOLERANCE_SECONDS,
    ProgressEntry,
    file_size,
    read_progress,
    read_video_sizes,
    read_videos,
    rekey_video_data,
    video_data_keys,
)

LOG: Final = logging.getLogger(__name__)


@dataclass(frozen=True)
class MissingFile:
    """What is known of a file that has data of the user's and is not on disk."""

    size: int | None
    """Its size in bytes when it was last played, noted or starred, or ``None`` when unknown."""

    duration: float | None = None
    """The length the player saw, or ``None`` when it never played."""

    facts: VideoFacts | None = None
    """Its ``videos`` entry, still there from a Measure before it went, or ``None``."""

    checksum: ChecksumEntry | None = None
    """Its ``.checksum`` entry when one records a hash, else ``None``."""


@dataclass(frozen=True)
class RenameCandidate:
    """A video on disk with no data of the user's -- possibly a missing file under its new name."""

    size: int
    """Its size in bytes."""

    facts: VideoFacts | None = None
    """Its ``videos`` entry, or ``None`` when it was never measured under this name."""


def plan_progress_renames(
    missing: Mapping[str, MissingFile],
    candidates: Mapping[str, RenameCandidate],
    *,
    match_by_size: bool,
    digest: Callable[[str, str], str | None],
) -> dict[str, str]:
    """Decide which missing entries move to which candidates, by the module's evidence ladder.

    :param missing: the missing files, by content key.
    :param candidates: the unkeyed videos on disk, by content key.
    :param match_by_size: the setting *match renamed files by size when no checksum is recorded*.
    :param digest: hashes a candidate -- its key and an algorithm name in, the hex digest out, or ``None`` when it
        could not be read. Asked at most once per candidate and algorithm.
    :returns: the moves, old key to new key; each candidate is the target of one move at most.
    """
    digests: dict[tuple[str, str], str | None] = {}

    def cached_digest(key: str, algorithm: str) -> str | None:
        """Hash one candidate once.

        :param key: the candidate's key.
        :param algorithm: the algorithm name.
        :returns: the digest, or ``None`` when the file could not be read.
        """
        if (key, algorithm) not in digests:
            digests[key, algorithm] = digest(key, algorithm)
        return digests[key, algorithm]

    claims: dict[str, str] = {}
    for key, gone in missing.items():
        target = renamed_to(gone, candidates, match_by_size, cached_digest)
        if target is not None:
            claims[key] = target
    claimed = Counter(claims.values())
    return {key: target for key, target in claims.items() if claimed[target] == 1}


def renamed_to(
    gone: MissingFile,
    candidates: Mapping[str, RenameCandidate],
    match_by_size: bool,
    digest: Callable[[str, str], str | None],
) -> str | None:
    """Find the one candidate a missing file was renamed to, if the evidence names exactly one.

    :param gone: the missing file.
    :param candidates: the unkeyed videos on disk, by content key.
    :param match_by_size: whether the size rung may decide.
    :param digest: hashes a candidate, as :func:`plan_progress_renames` takes it.
    :returns: the candidate's key, or ``None`` when the evidence names none, or more than one.
    """
    if gone.size is None:
        return None
    pool = [key for key, candidate in candidates.items() if candidate.size == gone.size]
    recorded = gone.checksum
    if recorded is not None and recorded.algorithm is not None and recorded.digest is not None:
        hashed = [digest(key, recorded.algorithm) for key in pool]
        if any(value is None for value in hashed):
            return None
        matches = [key for key, value in zip(pool, hashed, strict=True) if value == recorded.digest.lower()]
        return matches[0] if len(matches) == 1 else None
    if not match_by_size:
        return None
    length = gone.facts.duration if gone.facts is not None else gone.duration
    matches = [key for key in pool if same_length(length, candidates[key].facts)]
    return matches[0] if len(matches) == 1 else None


def same_length(length: float | None, facts: VideoFacts | None) -> bool:
    """Whether a missing file's length allows a candidate's -- equal within :data:`END_TOLERANCE_SECONDS`, or
    either unknown.

    :param length: the missing file's length, or ``None``.
    :param facts: the candidate's measured facts, or ``None``.
    :returns: whether the lengths do not tell them apart.
    """
    return length is None or facts is None or abs(facts.duration - length) <= END_TOLERANCE_SECONDS


def reattach_renamed_progress(  # pylint: disable=too-many-arguments
    path: Path,
    username: str,
    *,
    match_by_size: bool = True,
    current_username: str = DEFAULT_CURRENT_USERNAME,
    plugins: PluginRegistry = DEFAULT_PLUGIN_REGISTRY,
    video_extensions: tuple[str, ...] = VIDEO_EXTENSIONS,
    excluded_patterns: tuple[str, ...] = EXCLUDED_FILE_PATTERNS,
) -> dict[str, str]:
    """Move ``username``'s data -- progress, notes, favorites -- whose files were renamed onto the files' new names.

    What a host runs when it lists a tutorial's files, and when a video is first played or noted. The evidence is
    read with no lock held -- hashing a candidate can take a while -- and the moves are written in one
    :func:`~rehuco_core.record_merge.merge_write` without stamping ``updated``, each applied only while the fresh
    record still has data under the old key and none under the new. Another user's data and the shared ``videos``
    are left alone. Nothing is hashed, and nothing written, when no data is missing.

    :param path: the tutorial's record.
    :param username: whose progress.
    :param match_by_size: the setting *match renamed files by size when no checksum is recorded*.
    :param current_username: the identity the record is opened as
        (:func:`~rehuco_core.watch_progress.record_progress`'s).
    :param plugins: the plugin registry to load with.
    :param video_extensions: what counts as a video.
    :param excluded_patterns: filename globs the walk leaves out.
    :returns: the moves written, old key to new key.
    :raises ValueError: the record is not a tutorial, or is locked against saving.
    :raises OSError: the record could not be read or written.
    :raises RehuFormatError: the record is not readable.
    :raises ContentUnreachableError: some directory under the resource would not list.
    """
    document = RehuDocument.load(path, plugins=plugins, username=current_username)
    if document.active_block_key != TUTORIAL_PLUGIN.key:
        raise ValueError(f"Watch progress is kept on tutorials only, not on {path}.")
    evidence = rename_evidence(path, document, username, video_extensions, excluded_patterns)
    if evidence is None:
        return {}
    missing, candidates, on_disk = evidence
    plan = plan_progress_renames(
        missing,
        candidates,
        match_by_size=match_by_size,
        digest=lambda key, algorithm: file_digest(on_disk[key], algorithm),
    )
    if not plan:
        return {}
    return move_progress_entries(path, username, plan, current_username=current_username, plugins=plugins)


def rename_evidence(
    path: Path,
    document: RehuDocument,
    username: str,
    video_extensions: tuple[str, ...],
    excluded_patterns: tuple[str, ...],
) -> tuple[dict[str, MissingFile], dict[str, RenameCandidate], dict[str, Path]] | None:
    """Gather what :func:`plan_progress_renames` decides on, reading the ``.checksum`` only when an entry is missing.

    :param path: the tutorial's record.
    :param document: the record, as loaded.
    :param username: whose data.
    :param video_extensions: what counts as a video.
    :param excluded_patterns: filename globs the walk leaves out.
    :returns: the missing files and the candidates by key, and every video on disk by key; ``None`` when no data is
        missing.
    :raises ContentUnreachableError: some directory under the resource would not list.
    """
    known = video_data_keys(document, username)
    if not known:
        return None
    on_disk = {
        content_key(path, file): file
        for file in content_video_files(path, video_extensions=video_extensions, excluded_patterns=excluded_patterns)
    }
    # a key another build or a hand edit wrote that names no file inside the resource stays missing: it
    # resolves to nothing, so there is no file it could have been renamed from
    missing_keys = [key for key in sorted(known.difference(on_disk)) if is_valid_content_key(path, key)]
    if not missing_keys:
        return None
    entries = read_progress(document, username)
    noted_sizes = read_video_sizes(document, username)
    measured = read_videos(document)
    recorded = recorded_hashes(path)
    missing = {key: missing_file(key, entries.get(key), noted_sizes, measured, recorded, path) for key in missing_keys}
    return missing, rename_candidates(on_disk, known, measured), on_disk


def rename_candidates(
    on_disk: Mapping[str, Path], known: Collection[str], measured: Mapping[str, VideoFacts]
) -> dict[str, RenameCandidate]:
    """The videos on disk a missing file's data could have moved to: those with no data of the user's.

    :param on_disk: every video on disk, by content key.
    :param known: the keys the user keeps data about.
    :param measured: the ``videos`` map.
    :returns: each candidate that could be read, by key.
    """
    candidates: dict[str, RenameCandidate] = {}
    for key, file in on_disk.items():
        size = file_size(file) if key not in known else None
        if size is not None:
            candidates[key] = RenameCandidate(size, measured.get(key))
    return candidates


def missing_file(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    key: str,
    entry: ProgressEntry | None,
    noted_sizes: Mapping[str, int],
    measured: Mapping[str, VideoFacts],
    recorded: Mapping[str, ChecksumEntry],
    path: Path,
) -> MissingFile:
    """Gather what is known of one missing file.

    :param key: its content key.
    :param entry: the user's progress entry on it, or ``None``.
    :param noted_sizes: the sizes recorded with notes and favorites, by key.
    :param measured: the ``videos`` map.
    :param recorded: the hashes the ``.checksum`` records, by entry name.
    :param path: the resource's record.
    :returns: the file's size -- the progress entry's, else the noted one -- and what else is known.
    """
    size = entry.size if entry is not None and entry.size is not None else noted_sizes.get(key)
    return MissingFile(
        size,
        entry.duration if entry is not None else None,
        measured.get(key),
        recorded.get(checksum_name(path, key)),
    )


def move_progress_entries(
    path: Path,
    username: str,
    plan: Mapping[str, str],
    *,
    current_username: str,
    plugins: PluginRegistry,
) -> dict[str, str]:
    """Write a rename plan: each key's progress entry, note, favorite and size move to its new key as stored.

    :param path: the tutorial's record.
    :param username: whose progress.
    :param plan: the moves, old key to new key.
    :param current_username: the identity the record is opened as.
    :param plugins: the plugin registry to load with.
    :returns: the moves applied -- those whose old key the fresh record still holds data under, with none under the
        new key.
    """
    applied: dict[str, str] = {}

    def mutate(document: RehuDocument) -> None:
        """Move the entries in the freshly read record.

        :param document: the record as it is on disk now.
        """
        keys = video_data_keys(document, username)
        for old, new in plan.items():
            if old in keys and new not in keys and rekey_video_data(document, username, old, new):
                keys.discard(old)
                keys.add(new)
                applied[old] = new

    merge_write(path, mutate, username=current_username, plugins=plugins, touch_updated=False)
    if applied:
        LOG.info("Moved watch progress and notes in %s to renamed files: %s", path, applied)
    return applied


def recorded_hashes(path: Path) -> dict[str, ChecksumEntry]:
    """Read the hashes ``path``'s ``.checksum`` records, by entry name.

    :param path: the resource's record.
    :returns: each entry holding a hash; empty when the record is absent or unreadable. A name listed twice is
        left out -- the record does not say which of its hashes is the file's.
    """
    try:
        record = load_checksum_record(checksum_record_path(path))
    except (OSError, ChecksumRecordError) as error:
        LOG.debug("No recorded hashes for %s: %s", path, error)
        return {}
    parsed = [parse_checksum_entry(raw) for raw in record[CHECKSUM_FILES_KEY]]
    hashed = [entry for entry in parsed if entry is not None and entry.algorithm is not None]
    listed = Counter(entry.name for entry in hashed)
    return {entry.name: entry for entry in hashed if listed[entry.name] == 1}


def checksum_name(path: Path, key: str) -> str:
    """The name a ``.checksum`` entry gives the file a content key names.

    :param path: the resource's record.
    :param key: a content key.
    :returns: the file's POSIX path under the record's directory -- for a standalone record, its whole name, stem
        included.
    """
    return content_path(path, key).relative_to(path.parent).as_posix()


def file_digest(path: Path, algorithm: str) -> str | None:
    """Hash one file whole.

    :param path: the file.
    :param algorithm: a :data:`~rehuco_core.CHECKSUM_ALGORITHMS` name.
    :returns: the lowercase hex digest, or ``None`` when the file could not be read.
    """
    digest = CHECKSUM_ALGORITHMS[algorithm].new_digest()
    try:
        with shared_read_open(path) as handle:
            while chunk := handle.read(CHECKSUM_READ_CHUNK_SIZE):
                digest.update(chunk)
    except OSError as error:
        LOG.info("Could not hash %s as a renamed file: %s", path, error)
        return None
    return digest.hexdigest()
