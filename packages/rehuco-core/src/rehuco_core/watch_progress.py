"""Per-user watch progress on a tutorial's videos ([[field-schema#watch-progress]], #410).

Qt-free and host-neutral: the agent binds it (#316), the node serves it to the web player (#441), and every one of
them records progress through :func:`record_progress`, the one write path. Two maps live in the tutorial block, both
keyed by :func:`~rehuco_core.content_keys.content_key`: the shared ``videos`` lengths a Measure writes
(:func:`set_videos`), and each user's ``users.<username>.progress`` (:class:`ProgressEntry`). Totals are derived,
never stored (:func:`watch_totals`), and so is a file being *missing* (:func:`missing_progress_keys`): its entry
stays until :func:`forget_progress` removes it by hand, or follows the file when it was renamed
(:mod:`rehuco_core.progress_renames`, #411).
"""

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from .constants import EXCLUDED_FILE_PATTERNS, VIDEO_EXTENSIONS
from .content_keys import content_key, content_path, is_valid_content_key
from .plugins import DEFAULT_CURRENT_USERNAME, DEFAULT_PLUGIN_REGISTRY, TUTORIAL_PLUGIN, PluginRegistry
from .record_merge import merge_write
from .rehu_content_duration import DURATION_KEY, VideoFacts, content_video_files, finite_seconds
from .rehu_content_files import ContentUnreachableError
from .rehu_document import RehuDocument

LOG: Final = logging.getLogger(__name__)

VIDEOS_KEY: Final = "videos"
"""The tutorial block's shared map of measured lengths, by content key."""

PROGRESS_KEY: Final = "progress"
"""A user's submap key holding their progress entries, by content key."""

POSITION_KEY: Final = "position"
"""A progress entry's resume point key."""

VIEWED_KEY: Final = "viewed"
"""*Watched to the end at least once* -- a progress entry's flag, and the tutorial's own per-user flag."""

SIZE_KEY: Final = "size"
"""A progress entry's key holding the file's size in bytes when it was last played -- what tells its renamed self
apart once the file is gone (#411)."""

END_TOLERANCE_SECONDS: Final = 1.0
"""How close to its length a position counts as *the end*: a player stopping on the last frame reports a position a
frame or two short of the container's duration."""


@dataclass(frozen=True)
class ProgressEntry:
    """One user's progress on one file: two independent facts, the resume point and whether the file was watched to
    the end at least once ([[field-schema#watch-progress]]).
    """

    position: float
    """Where playback last stopped, in seconds."""

    duration: float | None = None
    """The length the player saw -- the fallback when ``videos`` has none for this file."""

    viewed: bool = False
    """Whether the file was watched to the end at least once."""

    size: int | None = None
    """The file's size in bytes when it was last played, or ``None`` when unknown -- the rename detection's
    evidence once the file is gone (:func:`~rehuco_core.progress_renames.reattach_renamed_progress`)."""

    @classmethod
    def from_stored(cls, raw: dict[str, Any]) -> ProgressEntry:
        """Read one stored entry, a malformed value reading as its default.

        :param raw: the stored entry.
        :returns: the entry.
        """
        size = raw.get(SIZE_KEY)
        return cls(
            finite_seconds(raw.get(POSITION_KEY), allow_zero=True) or 0.0,
            finite_seconds(raw.get(DURATION_KEY)),
            raw.get(VIEWED_KEY) is True,
            size if isinstance(size, int) and not isinstance(size, bool) and size >= 0 else None,
        )

    def to_stored(self) -> dict[str, Any]:
        """Shape this entry for the file, an unknown duration or size left out rather than written ``null``.

        :returns: the stored entry.
        """
        stored: dict[str, Any] = {POSITION_KEY: self.position}
        if self.duration is not None:
            stored[DURATION_KEY] = self.duration
        if self.size is not None:
            stored[SIZE_KEY] = self.size
        stored[VIEWED_KEY] = self.viewed
        return stored


@dataclass(frozen=True)
class WatchRules:
    """The two auto-viewed settings ([[field-schema#watch-progress]]), passed in by the host that reads them."""

    mark_file_viewed_at_end: bool = True
    """Reaching the end of a file sets its ``viewed``."""

    mark_tutorial_viewed_on_last_file: bool = True
    """A file becoming ``viewed`` sets the tutorial's ``viewed`` when every file now is -- on that change only."""


@dataclass(frozen=True)
class WatchTotals:
    """How much of a folder, or of the whole resource, one user has watched."""

    watched: float = 0.0
    """Seconds watched: a viewed file's full length, otherwise its position capped at its length."""

    length: float = 0.0
    """Seconds of video whose length is known."""

    unknown_length: int = 0
    """Files counted in neither sum, because neither ``videos`` nor a progress entry knows their length."""

    files: int = 0
    """Every file counted, missing ones included, known length or not."""

    @property
    def remaining(self) -> float:
        """Seconds left to watch of the known length."""
        return max(self.length - self.watched, 0.0)


def read_videos(document: RehuDocument) -> dict[str, VideoFacts]:
    """Read the active block's ``videos`` map.

    :param document: the record.
    :returns: each well-formed entry by key; a malformed one is skipped and left on disk as it is.
    """
    raw = document.active_field(VIDEOS_KEY)
    if not isinstance(raw, dict):
        return {}
    read = {key: VideoFacts.from_stored(value) for key, value in raw.items()}
    return {key: facts for key, facts in read.items() if facts is not None}


def set_videos(document: RehuDocument, measured: Mapping[str, VideoFacts]) -> None:
    """Replace the ``videos`` map with a Measure's result, keys sorted; an empty result removes the key.

    :param document: the record.
    :param measured: the facts by key, as :func:`~rehuco_core.rehu_content_duration.content_videos` returns them.
    """
    if not measured:
        document.remove_active_field(VIDEOS_KEY)
        return
    document.set_active_field(VIDEOS_KEY, {key: measured[key].to_stored() for key in sorted(measured)})


def read_progress(document: RehuDocument, username: str) -> dict[str, ProgressEntry]:
    """Read ``username``'s progress entries.

    :param document: the record.
    :param username: whose progress.
    :returns: each entry by key; one that is not an object is skipped and left on disk as it is.
    """
    raw = document.user_field(username, PROGRESS_KEY)
    if not isinstance(raw, dict):
        return {}
    return {key: ProgressEntry.from_stored(value) for key, value in raw.items() if isinstance(value, dict)}


def set_progress_entry(document: RehuDocument, username: str, key: str, entry: ProgressEntry | None) -> None:
    """Replace one of ``username``'s progress entries, leaving the others as stored.

    :param document: the record.
    :param username: whose progress.
    :param key: the file's content key.
    :param entry: the new entry, or ``None`` to forget it; forgetting the last removes ``progress`` itself.
    """
    raw = document.user_field(username, PROGRESS_KEY)
    entries: dict[str, Any] = dict(raw) if isinstance(raw, dict) else {}
    if entry is None:
        entries.pop(key, None)
    else:
        entries[key] = entry.to_stored()
    document.set_user_field(username, PROGRESS_KEY, {name: entries[name] for name in sorted(entries)} or None)


def reached_end(position: float, length: float | None) -> bool:
    """Whether ``position`` is at the end of a file ``length`` long, within :data:`END_TOLERANCE_SECONDS`.

    :param position: the playback position, in seconds.
    :param length: the file's length, or ``None`` when unknown -- then no position is the end.
    :returns: whether the position counts as the end.
    """
    return length is not None and position >= length - END_TOLERANCE_SECONDS


def record_progress(  # pylint: disable=too-many-arguments
    path: Path,
    username: str,
    relative: str,
    position: float,
    duration: float | None,
    *,
    viewed: bool | None = None,
    rules: WatchRules = WatchRules(),
    current_username: str = DEFAULT_CURRENT_USERNAME,
    plugins: PluginRegistry = DEFAULT_PLUGIN_REGISTRY,
    video_extensions: tuple[str, ...] = VIDEO_EXTENSIONS,
    excluded_patterns: tuple[str, ...] = EXCLUDED_FILE_PATTERNS,
) -> ProgressEntry:
    """Record where ``username`` stopped in one file -- the one write path for every player
    ([[field-schema#watch-progress]]).

    A :func:`~rehuco_core.record_merge.merge_write` replacing ``users.<username>.progress.<relative>`` only, plus
    the tutorial's own ``viewed`` when the second rule fires, without stamping ``updated``. An explicit ``viewed``
    (the checkbox) is stored as given; otherwise the stored flag stands, and is set when ``rules`` say so and the
    position reached the end of the ``videos`` length, else of ``duration``. When the file's flag turns on and
    ``rules`` say so, the tutorial's is set if every video on disk and every missing file with an entry is viewed.
    The file's size is read off disk into the entry, the stored one kept when the file cannot be read.

    :param path: the tutorial's record.
    :param username: whose progress.
    :param relative: the file's content key.
    :param position: where playback stopped, in seconds.
    :param duration: the length the player saw, or ``None`` to keep the stored one.
    :param viewed: the file's flag set by hand, or ``None`` to let ``rules`` decide.
    :param rules: the auto-viewed settings.
    :param current_username: the identity the record is opened as -- the host's own, the same one the agent opens
        every record with -- and so the user a block migration files legacy per-user fields under
        ([[field-schema#per-user-shared]]). Deliberately not ``username``: a node recording Bob's progress on a
        record no build has migrated yet must not hand him the owner's flags.
    :param plugins: the plugin registry to load with.
    :param video_extensions: what counts as a video for the tutorial rule's walk.
    :param excluded_patterns: filename globs the walk leaves out.
    :returns: the entry as written.
    :raises ValueError: ``relative`` is not a content key, ``position`` or ``duration`` is out of range, the record
        is not a tutorial, or it is locked against saving.
    :raises OSError: the record could not be read or written.
    :raises RehuFormatError: the record is not readable.
    """
    if not is_valid_content_key(path, relative):
        raise ValueError(f"Not a content key of {path}: {relative!r}")
    if finite_seconds(position, allow_zero=True) is None or (duration is not None and finite_seconds(duration) is None):
        raise ValueError(f"Not a playback position and length: {position!r}, {duration!r}")
    written: list[ProgressEntry] = []

    def mutate(document: RehuDocument) -> None:
        """Apply the write to the freshly read record.

        :param document: the record as it is on disk now.
        :raises ValueError: the record is not a tutorial.
        """
        if document.active_block_key != TUTORIAL_PLUGIN.key:
            raise ValueError(f"Watch progress is recorded on tutorials only, not on {path}.")
        old = read_progress(document, username).get(relative)
        was_viewed = old is not None and old.viewed
        measured = read_videos(document).get(relative)
        length = measured.duration if measured is not None else duration
        if viewed is not None:
            now_viewed = viewed
        else:
            now_viewed = was_viewed or (rules.mark_file_viewed_at_end and reached_end(position, length))
        kept_duration = duration if duration is not None else (old.duration if old is not None else None)
        size = file_size(content_path(path, relative))
        kept_size = size if size is not None else (old.size if old is not None else None)
        entry = ProgressEntry(float(position), kept_duration, now_viewed, kept_size)
        set_progress_entry(document, username, relative, entry)
        written.append(entry)
        if now_viewed and not was_viewed and rules.mark_tutorial_viewed_on_last_file:
            if every_file_viewed(document, path, username, video_extensions, excluded_patterns):
                document.set_user_field(username, VIEWED_KEY, True)

    merge_write(path, mutate, username=current_username, plugins=plugins, touch_updated=False)
    return written[0]


def forget_progress(
    path: Path,
    username: str,
    relative: str,
    *,
    current_username: str = DEFAULT_CURRENT_USERNAME,
    plugins: PluginRegistry = DEFAULT_PLUGIN_REGISTRY,
) -> bool:
    """Remove one of ``username``'s progress entries by hand -- the only way one is ever removed: a file that is
    gone keeps its entry until the user forgets it ([[field-schema#watch-progress]], #411).

    A :func:`~rehuco_core.record_merge.merge_write` like :func:`record_progress`, without stamping ``updated``.

    :param path: the tutorial's record.
    :param username: whose progress.
    :param relative: the entry's key as stored. Whether the file is on disk is not asked, and the key is not held
        to :func:`~rehuco_core.content_keys.is_valid_content_key`: forgetting resolves no path, and a key another
        build or a hand edit wrote wrong is exactly one the user needs to be able to remove.
    :param current_username: the identity the record is opened as (:func:`record_progress`'s).
    :param plugins: the plugin registry to load with.
    :returns: whether there was an entry to remove; when there was none, the record is written back unchanged.
    :raises ValueError: the record is locked against saving.
    :raises OSError: the record could not be read or written.
    :raises RehuFormatError: the record is not readable.
    """
    removed: list[bool] = []

    def mutate(document: RehuDocument) -> None:
        """Remove the entry from the freshly read record.

        :param document: the record as it is on disk now.
        """
        removed.append(relative in read_progress(document, username))
        if removed[0]:
            set_progress_entry(document, username, relative, None)

    merge_write(path, mutate, username=current_username, plugins=plugins, touch_updated=False)
    return removed[0]


def missing_progress_keys(keys_on_disk: Iterable[str], entries: Mapping[str, ProgressEntry]) -> list[str]:
    """The entries whose file is not on disk -- *missing*, derived when listing and never stored
    ([[field-schema#watch-progress]], #411).

    :param keys_on_disk: the content keys of the videos on disk now.
    :param entries: the user's progress (:func:`read_progress`).
    :returns: the missing keys, sorted.
    """
    return sorted(set(entries).difference(keys_on_disk))


def file_size(path: Path) -> int | None:
    """Read a file's size.

    :param path: the file.
    :returns: its size in bytes, or ``None`` when it cannot be read.
    """
    try:
        return path.stat().st_size
    except OSError:
        return None


def watch_totals(
    keys_on_disk: Iterable[str],
    measured: Mapping[str, VideoFacts],
    entries: Mapping[str, ProgressEntry],
) -> dict[str, WatchTotals]:
    """Sum one user's watching per folder and for the whole resource ([[field-schema#watch-progress]]).

    Every file on disk counts, and so does every missing file with an entry. A file's length is its ``measured``
    one, else its entry's; a viewed file counts its full length, otherwise its position.

    :param keys_on_disk: the content keys of the videos on disk now.
    :param measured: the ``videos`` map (:func:`read_videos`).
    :param entries: the user's progress (:func:`read_progress`).
    :returns: totals by folder key -- ``""`` for the whole resource, ``"01 Basics"`` for a folder, each summing its
        subfolders. Always holds ``""``.
    """
    sums: dict[str, WatchTotals] = {"": WatchTotals()}
    for key in dict.fromkeys([*keys_on_disk, *entries]):
        file_totals = file_watch_totals(measured.get(key), entries.get(key))
        for folder in folder_keys(key):
            total = sums.get(folder, WatchTotals())
            sums[folder] = WatchTotals(
                total.watched + file_totals.watched,
                total.length + file_totals.length,
                total.unknown_length + file_totals.unknown_length,
                total.files + 1,
            )
    return sums


def file_watch_totals(facts: VideoFacts | None, entry: ProgressEntry | None) -> WatchTotals:
    """One file's contribution to :func:`watch_totals`.

    :param facts: the file's ``videos`` entry, or ``None``.
    :param entry: the user's progress on it, or ``None``.
    :returns: its totals, ``files`` left for the caller to count.
    """
    length = facts.duration if facts is not None else (entry.duration if entry is not None else None)
    if length is None:
        return WatchTotals(unknown_length=1)
    if entry is None:
        return WatchTotals(length=length)
    return WatchTotals(length if entry.viewed else min(entry.position, length), length)


def folder_keys(key: str) -> list[str]:
    """The folders a content key counts toward.

    :param key: a content key.
    :returns: ``""`` for the resource, then each directory above the file from the outermost in.
    """
    parts = key.split("/")[:-1]
    return ["", *("/".join(parts[: index + 1]) for index in range(len(parts)))]


def every_file_viewed(
    document: RehuDocument,
    path: Path,
    username: str,
    video_extensions: tuple[str, ...],
    excluded_patterns: tuple[str, ...],
) -> bool:
    """Whether ``username`` has viewed every video on disk and every missing file with an entry.

    :param document: the record, as about to be written.
    :param path: the record's path, whose content is walked.
    :param username: whose progress.
    :param video_extensions: what counts as a video.
    :param excluded_patterns: filename globs the walk leaves out.
    :returns: the answer; ``False`` when the content would not list, which skips the rule.
    """
    try:
        on_disk = content_video_files(path, video_extensions=video_extensions, excluded_patterns=excluded_patterns)
    except ContentUnreachableError as error:
        LOG.info("Not checking %s as viewed: its content would not list (%s).", path, error)
        return False
    entries = read_progress(document, username)
    keys = {content_key(path, file) for file in on_disk} | set(entries)
    return all(key in entries and entries[key].viewed for key in keys)
