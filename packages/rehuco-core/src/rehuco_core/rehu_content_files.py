"""Which files on disk make up a resource's content ([[data-model#resource-scoping]], #226).

Two features must agree on this and cannot be allowed to disagree: the size-on-disk scan and checksum
generate/verify. A file summed by one and skipped by the other is a bug waiting to happen -- a verify
reporting an *unexpected new file* the size the user was shown already counted -- so the answer is
computed once, here, and both read it.

**A walk says what it could not see** (#245). An unreadable branch and an empty one are not the same
answer, and a walk that returned only its files made them one -- which is how a size over an offline
mount under-reported silently and a checksum baseline deleted the hashes for a branch it could not list.
The walk still never raises: it reports the directories that would not list
([[mounts-and-storage#offline-mounts]]), and what that costs is each caller's to decide.

**A record counts only what it covers** (#254). Where a nested resource's files used to be its own
record's content *and* every ancestor's, they are now only its own: a subdirectory holding an
``info.rehu`` leaves an ancestor's walk wholesale, and a file-scoped ``foo.rehu`` takes its same-stem
siblings out of the enclosing record's. The overlap made a library's size unanswerable by adding up what
each record already knows, which is the one aggregation the catalog cache exists to do. Records written
under the old rule still list files this walk no longer returns; :func:`excluded_content_names` is how a
verify decides which of those were never any record's content and can simply be dropped.

The counterpart of `rehuco_core.rehu_content_images`, one level out: that module lists the images
*inside* a reference-images resource's archives, this one lists the files the resource *is*. Core-side
and GUI-free; the caller supplies the excluded-name patterns rather than this module reading a setting.
"""

import fnmatch
import os
import re
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from .constants import (
    CHECKSUM_MANIFEST_EXTENSIONS,
    EXCLUDED_FILE_PATTERNS,
    IMAGE_EXTENSIONS,
)
from .resource_scoping import (
    is_directory_scoped,
    is_directory_scoped_name,
    is_legacy_record_name,
    is_record_name,
)
from .tc_conversion_backups import is_conversion_backup
from .tc_screenshots import is_legacy_screenshot

MAX_NAMED_UNREADABLE: Final = 3
"""How many unreadable directories an error names before it counts the rest.

A tree that went away wholesale has one unreadable directory per branch, and a sentence listing forty of
them says less than one listing three."""

ContentExclusionTier = Literal["structural", "junk"]
"""Which of the two exclusion tiers takes a file out of every resource's content
([[data-model#resource-scoping]], #226).

``structural`` -- a record, one of the files a record claims (its ``<record>NN`` screenshots, its
manifest, a legacy record's tc4-schemed screenshots), or a retained ``.orig`` conversion backup. ``junk``
-- a caller's filename glob, the tier the ``Excluded Files`` page edits. Named rather than merely applied
because a ``.checksum`` written under an older rule holds entries for such files, and a verify that drops
one has to be able to say why (:func:`excluded_content_names`, #254).

Neither tier covers a file **another record** now claims: those bytes are still somebody's content, and
what happens to a record's entry for them is a migration rather than a deletion (#257)."""


class ContentUnreachableError(OSError):
    """A resource whose content could not be read in full -- a mount that is away, a branch that refuses
    to list ([[mounts-and-storage#offline-mounts]], #245).

    An :class:`OSError`, because that is what it is, and deliberately **not** a
    :class:`FileNotFoundError`: *the mount is away* and *this resource has nothing/no record* are
    different sentences, and the second one is the lie this exists to stop telling.
    """


@dataclass(frozen=True, slots=True)
class ContentEnumeration:
    """What one content walk found, and what it could not see (#226, #245).

    Reported rather than raised, because the cost differs per caller: a verify carries on over a branch
    it cannot list -- it checks what the record lists, not what a walk finds -- while a size that
    under-reports and a baseline that drops the branch's entries are both wrong. Each caller asks for
    the guarantee it needs, through :meth:`require_reachable` or :meth:`require_complete`.

    :param directory: the resource's directory, which the walk started from.
    :param files: the content file paths, in a stable order.
    :param unreadable: the directories that would not list, :attr:`directory` itself included when the
        walk never started at all.
    """

    directory: Path
    files: list[Path]
    unreadable: tuple[Path, ...] = ()

    @property
    def reachable(self) -> bool:
        """Whether the resource's own directory listed -- the difference between *empty* and *away*."""
        return self.directory not in self.unreadable

    @property
    def complete(self) -> bool:
        """Whether every directory under the resource listed, so :attr:`files` is the whole content."""
        return not self.unreadable

    def require_reachable(self) -> None:
        """Refuse when the resource itself could not be read.

        :raises ContentUnreachableError: the resource's directory would not list.
        """
        if not self.reachable:
            raise ContentUnreachableError(f"The resource's directory could not be read: {self.directory}")

    def require_complete(self) -> None:
        """Refuse when any part of the resource could not be read.

        What a measurement over the whole resource needs: a total summed over the branches that happened
        to answer is not this resource's total, and reporting it as one is indistinguishable from the
        truth ([[mounts-and-storage#offline-mounts]]).

        :raises ContentUnreachableError: some directory under the resource would not list.
        """
        self.require_reachable()
        if self.unreadable:
            raise ContentUnreachableError(f"Part of the resource could not be read: {self.unreadable_text()}")

    def unreadable_text(self) -> str:
        """The unreadable directories, for a sentence a reader can act on.

        :returns: up to :data:`MAX_NAMED_UNREADABLE` of them, and a count of whatever is left.
        """
        named = ", ".join(str(directory) for directory in self.unreadable[:MAX_NAMED_UNREADABLE])
        remaining = len(self.unreadable) - MAX_NAMED_UNREADABLE
        return named if remaining <= 0 else f"{named} (and {remaining} more)"


class ContentFileScanner:
    """Enumerates one resource's content files ([[data-model#resource-scoping]]).

    Which of the two it is comes from :func:`~rehuco_core.resource_scoping.is_directory_scoped` rather
    than from a name compared here (#250): the size scan and the checksums may not disagree with the tab
    title about what a record describes, and a legacy ``info.tc`` is directory-scoped in exactly the sense
    ``info.rehu`` is.

    File-scoped (a named ``foo.rehu``/``foo.tc``): the same-stem siblings and nothing else -- a
    whitelist named by the ``.rehu`` itself, never a directory walk. An unrelated ``info.rehu``,
    ``bar00.jpg`` or ``bar.zip`` in the same directory belongs to another resource or to none, and is out
    of scope *before* any exclusion is consulted; no pattern can reach it, and emptying the pattern list
    cannot change it.

    Directory-scoped (``info.rehu``/``info.tc``): everything under the directory, recursively, minus two
    tiers of exclusion.

    **Structural** -- every **record** the walk finds, at any depth, together with the files that belong
    to it: its ``<record>NN`` screenshots and its ``<record>.checksum`` record -- together with the legacy
    manifest suffixes an external checker may have left beside it ([[data-model#checksums]]). Not just
    the scanning resource's own: a nested ``bar/info.rehu`` and a file-scoped ``baz.rehu`` sitting in the
    tree bring their own bookkeeping. [[data-model#checksums]] and [[data-model#image-meanings]] define
    *every* record and its screenshots as editable at any moment, so a measurement that counted them
    would need recomputing each time anyone edited a description or added a screenshot -- and a checksum
    that covered them would report a mismatch for the same. Excluding them is what makes a size and a
    manifest stay valid until the *content* actually changes.

    **A record counts only what it covers** (#254). A subdirectory holding an ``info.rehu``/``info.tc``
    leaves this walk **wholesale** -- its files, its subdirectories and all -- because that record covers
    its own directory; and a file-scoped ``foo.rehu`` takes its same-stem siblings out of the enclosing
    record's content, because those siblings are the whole of what it describes. Whatever no record
    claims still belongs to the nearest enclosing directory-scoped record, at any depth, and coverage is
    decided by **the records present** rather than by what is on disk
    ([[data-model#resource-scoping]]). Adding up every record's measured size then answers a library's --
    the aggregation the overlap this replaced made impossible, since it counted a nested resource once
    for itself and again for each of its ancestors.

    **A legacy ``.tc`` is a record** (#250), so it is bookkeeping wherever it sits and it claims the
    ``info.sfv``/``info.checksum``/``infoNN`` siblings beside it exactly as the ``info.rehu`` that
    replaces it will. Without that, an unconverted resource's content was *the ``.tc`` file and its own
    manifest* -- and the same directory measured a different set the moment it was converted, for a reason
    that has nothing to do with its content. What makes one is
    :data:`~rehuco_core.resource_scoping.RECORD_SUFFIXES`, the same answer the scope question comes from.

    **And it claims its screenshots by scheme.** tc4 named them ``01.jpg``, ``cover.jpg``,
    ``sample-01.jpg``, ``file(2).jpg``, ``file-01.jpg`` -- never after the record -- so the
    ``<record>NN`` rule cannot reach them and only a directory holding a ``.tc`` can say whose they are.
    :func:`~rehuco_core.tc_screenshots.is_legacy_screenshot` is asked, the same recognition a conversion
    renames by, so what this walk skips is exactly what
    :func:`~rehuco_core.originals_to_back_up` moves aside.

    **A record claims only its own directory.** Screenshots and manifests are a record's siblings by
    definition ([[data-model#resource-scoping]]), so ``baz00.jpg`` is bookkeeping where ``baz.rehu`` sits
    beside it and ordinary content anywhere else -- a root ``info.rehu`` does not reach down and claim a
    ``bar/info00.jpg`` that has no ``bar/info.rehu`` of its own.

    **And the record has to exist.** A name is bookkeeping *because a record claims it*, never because of
    its shape: with no ``xxx.rehu`` beside it, ``xxx00.jpg`` is a normal file, and so is a ``yyy.sfv``
    with no ``yyy.rehu``. Excluding on shape alone would drop a tutorial's own ``lesson01.jpg``, and a
    pack shipping its own checksum file, from the very measurement meant to cover them.

    **A retained ``.orig`` backup is structural too** (#253) -- and the one thing here excluded on its
    name alone, because a backup belongs to the directory it sits in rather than to a stem, so there is
    no record to look it up against. :func:`~rehuco_core.tc_conversion_backups.is_conversion_backup` is
    asked rather than the suffix matched here, which keeps the set this walk skips identical to the set a
    revert would restore ([[acquisition-tooling#convert-mechanics]]). A bulk import retains every backup,
    so counting them would bake each converted resource's own ``info.tc.orig`` into its first checksum
    baseline -- and discarding the backups, which is what the manager exists to offer, would then read as
    a missing file in every resource in the catalog.

    A screenshot is further ``<record>NN`` plus an
    :data:`~rehuco_core.constants.IMAGE_EXTENSIONS` suffix -- the same predicate
    `rehuco_core.rehu_screenshots` matches -- rather than ``<record>NN.*``, so a tutorial's ``info01.mp4``
    stays content instead of vanishing from the measurement and the manifest alike.

    The structural tier is applied whatever ``excluded_patterns`` says, and is not the user's to remove.
    **Junk** -- ``excluded_patterns`` -- is the caller's, and is the tier a user gets to change.

    :param rehu_path: the resource's ``.rehu`` file.
    :param excluded_patterns: filename globs to leave out of the directory-scoped walk, matched
        case-insensitively against the file name.
    """

    __SCREENSHOT_NAME_PATTERN: Final = re.compile(r"^(?P<record>.*)\d{2}$")
    """Splits a candidate screenshot's stem into the record it would belong to and its two-digit index --
    the same ``<record>NN`` shape `rehuco_core.rehu_screenshots` matches, read backwards because the
    record is what has to be looked up. Greedy, so ``info0000`` decomposes to ``info00`` + ``00`` and
    matches only a record actually named ``info00``."""

    def __init__(self, rehu_path: Path, excluded_patterns: tuple[str, ...]) -> None:
        self.__rehu_path: Final = rehu_path
        self.__excluded_patterns: Final = tuple(pattern.lower() for pattern in excluded_patterns)
        self.__slug: Final = rehu_path.stem.lower()

    def scan(self) -> ContentEnumeration:
        """Enumerate :attr:`rehu_path`'s content files, and the directories that would not list.

        :returns: what the walk found; see :func:`enumerate_content_files` for the full order and
            failure-handling contract.
        """
        directory = self.__rehu_path.parent
        unreadable: list[Path] = []
        if is_directory_scoped(self.__rehu_path):
            files = self.__scan_directory(directory, unreadable)
        else:
            files = self.__scan_siblings(directory, unreadable)
        return ContentEnumeration(directory, files, tuple(unreadable))

    def __scan_siblings(self, directory: Path, unreadable: list[Path]) -> list[Path]:
        """List the same-stem siblings a file-scoped resource describes.

        :param directory: the resource's directory.
        :param unreadable: the walk's record of what would not list, appended to in place -- for a
            file-scoped resource that can only ever be ``directory`` itself (e.g. an offline mount,
            [[mounts-and-storage#offline-mounts]]).
        :returns: the matching paths sorted by name, or empty when ``directory`` is missing/unreadable.
        """
        filenames, _ = self.__read_directory(directory, unreadable)
        records = self.__record_names(filenames) | {self.__slug}
        legacy = self.__holds_legacy_record(filenames)
        matches = sorted(
            filename
            for filename in filenames
            if os.path.splitext(filename)[0].lower() == self.__slug
            and not self.__is_bookkeeping(filename, records, legacy)
        )
        return [directory / filename for filename in matches]

    def __scan_directory(self, directory: Path, unreadable: list[Path]) -> list[Path]:
        """List everything under a directory-scoped resource's directory that both tiers let through.

        **A subdirectory holding a record of its own never opens** (#254): that record covers its own
        directory, so the branch is out of this resource's content wholesale -- its files, its own
        subdirectories and everything below them. The listing is still read, since whether it holds a
        record is the question, but nothing in it is collected and nothing under it is
        queued. And a file a **file-scoped** record here claims is left where the same-stem rule puts it.

        One directory at a time, descending: read a directory, take the records *it* holds, keep the
        files none of them claims, then do the same for each subdirectory. Deliberately not a flattened
        ``rglob`` with the records pooled afterwards -- a record's screenshots and manifest are its
        siblings, so the only records that can speak for a file are the ones in its own directory, and a
        pooled set would get that wrong (the root's ``info.rehu`` claiming a ``bar/info00.jpg`` that has
        no record of its own). Reading per directory makes the sibling rule structural rather than a
        filter that has to remember to compare parents, and holds one directory's names at a time
        instead of the whole tree.

        A subdirectory that cannot be read is skipped rather than fatal: an offline branch of a mount
        ([[mounts-and-storage#offline-mounts]]) costs its own contents, not the whole walk -- and it is
        named in ``unreadable``, so a caller for whom that *is* fatal can say so (#245).

        :param directory: the resource's directory.
        :param unreadable: the walk's record of what would not list, appended to in place.
        :returns: the matching paths sorted by path, or empty when ``directory`` is missing/unreadable.
        """
        matches: list[Path] = []
        pending = [directory]
        while pending:
            current = pending.pop()
            filenames, subdirectories = self.__read_directory(current, unreadable)
            if current != self.__rehu_path.parent and self.__holds_directory_scoped_record(filenames):
                continue
            pending.extend(subdirectories)
            claimed = self.__file_scoped_stems(filenames)
            records = self.__record_names(filenames)
            if current == self.__rehu_path.parent:
                records.add(self.__slug)
            legacy = self.__holds_legacy_record(filenames)
            matches.extend(
                current / filename
                for filename in filenames
                if not self.__is_bookkeeping(filename, records, legacy)
                and os.path.splitext(filename)[0].lower() not in claimed
                and not self.__is_excluded(filename)
            )
        return sorted(matches, key=str)

    @staticmethod
    def __read_directory(directory: Path, unreadable: list[Path]) -> tuple[list[str], list[Path]]:
        """Read one directory, separating its files from the subdirectories under it.

        :func:`os.scandir` rather than :meth:`~pathlib.Path.iterdir`: it answers ``is_dir``/``is_file``
        from what reading the directory already returned, where ``iterdir`` would cost a ``stat`` per
        entry to classify -- thousands of round trips on an SMB mount ([[mounts-and-storage#offline-mounts]])
        to learn what the listing knew. Only the filenames are kept, not `Path` objects, since both
        exclusion tiers are filename rules and the survivors are few.

        A symlink to a file counts as that file; a symlink to a directory is skipped entirely rather
        than descended (see the loop-guard comment below), so linked-in trees are never measured.

        A directory that will not list is recorded rather than swallowed, **whatever the reason** --
        including a :class:`FileNotFoundError`, which for the resource's own directory is exactly the
        unmapped drive this distinction exists for, and for a subdirectory means the walk's own listing
        is already out of date. A directory takes its whole subtree with it either way, and there is no
        verdict to reach about files nobody can name (#245).

        Handing the subdirectories back rather than queueing them is what lets the caller decline a whole
        branch after seeing what it holds (#254): a directory carrying a record of its own is another
        resource, and queueing it before that is known would be a decision made too early.

        :param directory: the directory to read.
        :param unreadable: the walk's record of what would not list, appended to in place.
        :returns: its filenames and its subdirectories, both empty when it cannot be read -- an unreadable
            branch costs its own contents, not the whole walk.
        """
        filenames: list[str] = []
        subdirectories: list[Path] = []
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    # never descend through a directory symlink: one pointing at an ancestor would loop
                    # the walk forever, and one into a sibling would count that content twice (the
                    # rglob this walk replaced did not follow them either)
                    if entry.is_dir(follow_symlinks=False):
                        subdirectories.append(directory / entry.name)
                    elif entry.is_file():
                        filenames.append(entry.name)
        except OSError:
            unreadable.append(directory)
            return [], []
        return filenames, subdirectories

    @staticmethod
    def __record_names(filenames: list[str]) -> set[str]:
        """Take the record names out of one directory's listing -- who can claim a screenshot or a
        manifest here.

        :param filenames: one directory's filenames.
        :returns: the stems of the record files among them -- ``.rehu`` and legacy ``.tc`` alike
            ([[data-model#resource-scoping]], #250) -- lower-cased.
        """
        stems = (os.path.splitext(filename)[0] for filename in filenames if is_record_name(filename))
        return {stem.lower() for stem in stems}

    @staticmethod
    def __holds_legacy_record(filenames: list[str]) -> bool:
        """Whether one directory's listing includes a ``.tc`` -- whose tc4-schemed screenshots these are.

        A directory rather than a stem, for the reason :mod:`rehuco_core.tc_conversion_backups` gives
        about the backups it leaves: a legacy screenshot is named ``cover.jpg`` or ``01.jpg`` and carries
        nothing tying it back to the record it belongs to, so the record it belongs to is *whichever one
        this directory holds* (#250).

        :param filenames: one directory's filenames.
        :returns: whether a legacy record sits among them.
        """
        return any(is_legacy_record_name(filename) for filename in filenames)

    @staticmethod
    def __holds_directory_scoped_record(filenames: list[str]) -> bool:
        """Whether one directory's listing includes an ``info.rehu``/``info.tc`` -- whose directory this
        is (#254).

        The directory-level half of *a record counts only what it covers*: a subdirectory that answers
        ``True`` is another resource's, wholesale, and the walk above it neither collects from it nor
        descends into it. Asked of the *name* through
        :func:`~rehuco_core.resource_scoping.is_directory_scoped_name`, the same rule the tab title and
        the rename plan read (#250), so no walk can invent a second answer to what ``info.tc`` is.

        :param filenames: one directory's filenames.
        :returns: whether a directory-scoped record sits among them.
        """
        return any(is_directory_scoped_name(filename) for filename in filenames)

    @staticmethod
    def __file_scoped_stems(filenames: list[str]) -> set[str]:
        """Take the *named* records out of one directory's listing -- who claims same-stem content here
        (#254).

        The file-level half of the same rule: a ``foo.rehu``'s content is its same-stem siblings
        ([[data-model#resource-scoping]]), so ``foo.zip`` is that record's and not the enclosing
        ``info.rehu``'s. Deliberately separate from :meth:`__is_bookkeeping`, which answers *never any
        resource's content*: these bytes are still content, just not this record's, which is what makes
        an existing entry for one a claim to move rather than to drop (#257).

        :param filenames: one directory's filenames.
        :returns: the stems of the file-scoped records among them, lower-cased; a directory-scoped
            ``info.rehu`` claims its directory rather than the ``info.*`` siblings sitting in it, so it
            is not one of these.
        """
        stems = (
            os.path.splitext(filename)[0]
            for filename in filenames
            if is_record_name(filename) and not is_directory_scoped_name(filename)
        )
        return {stem.lower() for stem in stems}

    def __is_bookkeeping(self, filename: str, records: set[str], legacy: bool) -> bool:
        """Whether ``filename`` is a resource record, one of the files that belong to one, or a
        conversion backup held on one's behalf.

        Every record counts, wherever it sits and whichever format it is (#250) -- the scanning
        resource's, a nested one's, a file-scoped neighbour's, and the legacy ``.tc`` a conversion has not
        reached yet. A screenshot or a manifest counts only where a record of that name sits
        beside it, so the same ``info00.jpg`` is bookkeeping next to an ``info.rehu`` and a normal file
        in a directory that has none. A ``.orig`` backup counts wherever it sits and against no record at
        all (#253): what it is a backup *of* is whatever the directory holding it is, which is the rule
        :mod:`rehuco_core.tc_conversion_backups` restores by and the one asked here.

        :param filename: the candidate's file name.
        **A legacy record's screenshots are named by scheme, not by stem** (#250): tc4 wrote ``01.jpg``,
        ``cover.jpg``, ``sample-01.jpg``, ``file(2).jpg``, ``file-01.jpg``, none of which carries the
        record's name, so the ``<record>NN`` rule below cannot see them and they would otherwise be the
        only bookkeeping a conversion renames that this walk still counted. Recognized through
        :func:`~rehuco_core.tc_screenshots.is_legacy_screenshot` and only where a ``.tc`` sits in the same
        directory, which keeps the set skipped here identical to the set
        :func:`~rehuco_core.originals_to_back_up` moves aside -- so converting a resource does not change
        what it is measured to hold. Without the directory condition a live tutorial's own ``01.jpg``
        would vanish from the measurement meant to cover it.

        :param filename: the candidate's file name.
        :param records: the record names found in that file's own directory, from :meth:`__record_names`.
        :param legacy: whether that directory holds a ``.tc``, from :meth:`__holds_legacy_record`.
        :returns: whether it is a record, one of a record's screenshots -- ``<record>NN`` or a legacy
            scheme -- a record's checksum manifest, or a retained conversion backup.
        """
        if is_conversion_backup(filename) or is_record_name(filename):
            return True
        stem, suffix = os.path.splitext(filename)
        suffix = suffix.lower()
        stem = stem.lower()
        if suffix in CHECKSUM_MANIFEST_EXTENSIONS:
            return stem in records
        if suffix in IMAGE_EXTENSIONS:
            if legacy and is_legacy_screenshot(filename):
                return True
            screenshot = self.__SCREENSHOT_NAME_PATTERN.match(stem)
            return screenshot is not None and screenshot["record"] in records
        return False

    def __is_excluded(self, filename: str) -> bool:
        """Whether ``filename`` matches one of the caller's junk globs.

        :func:`fnmatch.fnmatchcase` over both sides lower-cased rather than :func:`fnmatch.fnmatch`,
        whose case-folding follows the *host* platform: SMB and macOS both hand back casings Windows
        never wrote, so ``thumbs.db`` must not survive a Linux node's scan by spelling.

        :param filename: the candidate's file name.
        :returns: whether some pattern matches it.
        """
        lowered = filename.lower()
        return any(fnmatch.fnmatchcase(lowered, pattern) for pattern in self.__excluded_patterns)

    def excluded_names(self, names: Collection[str]) -> dict[str, ContentExclusionTier]:
        """Say which of ``names`` no resource's content could ever include, and under which tier (#254).

        The same two tiers :meth:`scan` applies, asked the other way round: :meth:`scan` starts from a
        disk walk and answers *what is content*, while this starts from names somebody recorded and
        answers *what was never content* -- which is what a record written under an older coverage rule
        needs, since the files it names may no longer be there to walk to. **Absence is deliberately not
        an input**: a deleted file and an excluded one look identical to a walk, so a name is dropped for
        what it *is*, never for not turning up.

        A name the answer omits is not thereby content: it may be a file another record now covers, or
        one no record covers that has simply been deleted. Both keep their entry -- the first until the
        claim can be moved (#257), the second as the ``missing`` it has always been.

        One listing per distinct directory, read once and reused, so a record naming two hundred files in
        five directories costs five listings rather than two hundred. A directory that will not list
        claims nothing, which leaves every name under it to the name-only rules -- a record suffix, an
        ``.orig`` backup, a junk glob -- and keeps the rest.

        :param names: record-relative, POSIX-separated names, already validated as naming a file inside
            the resource (:func:`~rehuco_core.checksum_entry_name`).
        :returns: the excluded ones only, each with the tier that excluded it, in the order given.
        """
        directory_scoped = is_directory_scoped(self.__rehu_path)
        listings: dict[Path, tuple[set[str], bool]] = {}
        excluded: dict[str, ContentExclusionTier] = {}
        for name in names:
            parts = name.split("/")
            directory = self.__rehu_path.parent.joinpath(*parts[:-1])
            if directory not in listings:
                listings[directory] = self.__claims_in(directory)
            records, legacy = listings[directory]
            if self.__is_bookkeeping(parts[-1], records, legacy):
                excluded[name] = "structural"
            elif directory_scoped and self.__is_excluded(parts[-1]):
                # a file-scoped resource's content is a whitelist no pattern can reach, so a junk glob
                # is not a reason to drop one of its entries either
                excluded[name] = "junk"
        return excluded

    def __claims_in(self, directory: Path) -> tuple[set[str], bool]:
        """What the records in one directory claim, for a name-driven read rather than a walk.

        :param directory: the directory to read; need not be under the resource's own, and need not
            exist.
        :returns: the record names it holds and whether one of them is a ``.tc``, the same pair
            :meth:`__scan_directory` computes per listing.
        """
        filenames, _ = self.__read_directory(directory, [])
        records = self.__record_names(filenames)
        if directory == self.__rehu_path.parent:
            records.add(self.__slug)
        return records, self.__holds_legacy_record(filenames)


def enumerate_content_files(
    rehu_path: Path, excluded_patterns: tuple[str, ...] = EXCLUDED_FILE_PATTERNS
) -> ContentEnumeration:
    """Enumerate ``rehu_path``'s content files: what it is a record *of*, never its own bookkeeping.

    :param rehu_path: the resource's ``.rehu`` file.
    :param excluded_patterns: filename globs to leave out of the directory-scoped walk, matched
        case-insensitively against the file name -- injected rather than read from a setting
        (:data:`~rehuco_core.constants.EXCLUDED_FILE_PATTERNS` by default), so the size scan and the
        checksums are handed the same answer instead of each deciding one. Ignored for a file-scoped
        resource, whose content is a whitelist of one.
    :returns: the files, in a stable order (by name for a file-scoped resource, by full path for a
        directory-scoped one), **and the directories that would not list**. A missing or unreadable
        directory contributes nothing rather than raising -- a document-level condition, not a crash --
        but it is named, so no caller has to mistake it for an empty resource (#245).
    """
    return ContentFileScanner(rehu_path, excluded_patterns).scan()


def excluded_content_names(
    rehu_path: Path, names: Collection[str], excluded_patterns: tuple[str, ...] = EXCLUDED_FILE_PATTERNS
) -> dict[str, ContentExclusionTier]:
    """Say which of ``names`` were never ``rehu_path``'s content, and under which tier (#254).

    The reverse of :func:`enumerate_content_files`, for the one caller that starts from names rather than
    from a disk walk: a ``.checksum`` written under an older coverage rule
    (:meth:`~rehuco_core.rehu_checksums.ChecksumRun.verify`). Names, not paths, because a name is what a
    record holds and the file behind it may be long gone -- and it is the *name* that decides, since a
    walk cannot tell a deleted file from an excluded one.

    Silence is not endorsement: a name left out is either content, or a file another record now covers
    whose claim has somewhere to go (#257), or one that is simply missing.

    :param rehu_path: the resource's ``.rehu`` file.
    :param names: record-relative, POSIX-separated names, already validated as naming a file inside the
        resource (:func:`~rehuco_core.checksum_entry_name`).
    :param excluded_patterns: the caller's junk globs, the same set the walk is given -- consulted for a
        directory-scoped resource only, since a file-scoped one's content is a whitelist no pattern
        reaches.
    :returns: the excluded names only, each with the tier that excluded it, in the order given.
    """
    return ContentFileScanner(rehu_path, excluded_patterns).excluded_names(names)


def content_size_on_disk(rehu_path: Path, excluded_patterns: tuple[str, ...] = EXCLUDED_FILE_PATTERNS) -> int:
    """Sum the sizes of ``rehu_path``'s content files -- the resource's footprint on disk
    ([[field-schema#duration-size]], #223).

    A ``stat`` sum over :func:`enumerate_content_files`, deliberately not a walk of its own: the size a
    user is shown and the files a checksum manifest covers must be the same set, and the one way to
    guarantee that is to ask the same question (#226).

    **The apparent size, not the allocated size.** ``st_size`` is what the file claims to be, which is
    what a listing quotes and what a re-download has to fetch; block allocation and compression are
    properties of the filesystem it happens to sit on, so the same content would measure differently per
    host and the number would stop being comparable.

    **A partial measurement is refused rather than reported low** (#245). A total summed over the
    branches that happened to answer is not this resource's size, and a number that reads as authority
    is worse than no number: the caller is told what could not be read and can measure again when the
    mount is back ([[mounts-and-storage#offline-mounts]]).

    :param rehu_path: the resource's ``.rehu`` file.
    :param excluded_patterns: filename globs to leave out of the directory-scoped walk, passed straight
        through to :func:`enumerate_content_files`.
    :returns: the total size in whole bytes; ``0`` when the resource has content files nowhere -- there
        is content and there is none of it, which is now a different answer from *unreachable*.
    :raises ContentUnreachableError: some directory under the resource would not list, or a content file
        that was listed refused to be measured.
    """
    enumeration = enumerate_content_files(rehu_path, excluded_patterns)
    enumeration.require_complete()
    total = 0
    for path in enumeration.files:
        try:
            total += path.stat().st_size
        except FileNotFoundError:
            # deleted between the listing and the stat: genuinely not there any more, and absent bytes
            # weigh nothing. Distinct from the refusal below, which says nothing about the file at all
            continue
        except OSError as error:
            raise ContentUnreachableError(f"A content file could not be measured: {path}") from error
    return total
