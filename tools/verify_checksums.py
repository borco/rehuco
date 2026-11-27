"""Verify ``.checksum`` records from a terminal, without the app and without writing anything (#715).

::

    uv run python tools/verify_checksums.py PATH [PATH ...]

Each ``PATH`` is a ``.checksum`` file or a folder; a folder stands for every ``.checksum`` under it, at any depth
unless ``--no-recursive``. The records and the files they list are only read: no verification date, no adopted file,
no pruned entry, no lock -- a share the app is using sees nothing of the run, and a read-only disk can be checked.
The check is :func:`rehuco_core.inspect_checksums`, which hashes the way a verify does and answers in a verify's own
report, so the words are the app's.

The excluded files are the app's current list (``--settings-dir`` picks which settings, as it does for the app);
``--exclude`` adds a glob for the run.

Exit status: 0 nothing found, 1 a file mismatched, is missing or could not be read (or ``--show-without-checksum``
listed one), 2 a path or a record could not be read at all, 130 stopped by Ctrl+C.
"""

import argparse
import io
import os
import shutil
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from rehuco_agent.__main__ import SETTINGS_DIR_ENVIRONMENT_VARIABLE, resolve_settings_dir
from rehuco_agent.settings.excluded_files_settings import shared_excluded_files_settings
from rehuco_agent.settings.persistent_settings import folders, set_settings_dir
from rehuco_core import (
    CHECKSUM_RECORD_SUFFIX,
    REHU_SUFFIX,
    ChecksumInspection,
    ChecksumRecordError,
    ContentUnreachableError,
    checksum_report_summary,
    inspect_checksums,
)
from rehuco_core.checksum_inspection import CLEAN_FILE_STATUSES
from rehuco_core.checksum_reporting import status_counts_text

EXIT_CLEAN: Final = 0
EXIT_FOUND: Final = 1
EXIT_UNREADABLE: Final = 2
EXIT_INTERRUPTED: Final = 130


@dataclass
class Totals:
    """What the whole run found, for its last line.

    :param records: the records checked.
    :param counts: how many files came back with each verdict.
    :param unreadable: the files that could not be read.
    :param without_checksum: the files listed as having no checksum.
    :param unreadable_records: the records or paths that could not be read at all.
    """

    records: int = 0
    counts: dict[str, int] = field(default_factory=dict)
    unreadable: int = 0
    without_checksum: int = 0
    unreadable_records: int = 0

    def add(self, inspection: ChecksumInspection) -> None:
        """Count one record's answer.

        :param inspection: what the check established.
        """
        self.records += 1
        for status in inspection.report.statuses.values():
            self.counts[status] = self.counts.get(status, 0) + 1
        self.unreadable += len(inspection.report.unreadable)
        self.without_checksum += len(inspection.without_checksum)

    def line(self) -> str:
        """The last line.

        :returns: the totals, in a summary's words.
        """
        parts = status_counts_text(self.counts)
        if self.unreadable:
            parts.append(f"{self.unreadable} unreadable")
        if self.without_checksum:
            parts.append(f"{self.without_checksum} without a checksum")
        if self.unreadable_records:
            parts.append(f"{self.unreadable_records} could not be read")
        records = f"{self.records} record{'' if self.records == 1 else 's'}"
        return f"Total: {records}: {', '.join(parts) if parts else 'nothing to check'}."


class Console:
    """Prints lines, and on a terminal one rewritten progress line that is cleared before each of them.

    :param interactive: whether the output is a terminal; a piped one gets no progress line.
    """

    def __init__(self, interactive: bool) -> None:
        self.__interactive: Final = interactive
        self.__drawn = False
        self.__label = ""
        self.__file = ""

    def say(self, text: str, *, error: bool = False) -> None:
        """Print one line.

        :param text: the line.
        :param error: whether it goes to the error stream.
        """
        self.clear()
        print(text, file=sys.stderr if error else sys.stdout, flush=True)

    def begin(self, record: Path) -> None:
        """Start a record's progress line.

        :param record: the ``.checksum`` file about to be checked.
        """
        self.__label = record.name
        self.__file = ""

    def on_file(self, name: str) -> None:
        """Say which file is being hashed.

        :param name: the file's name.
        """
        self.__file = name
        self.show(f"{self.__label}: {name}")

    def on_bytes(self, done: int, total: int | None) -> None:
        """Say how many bytes the run has read.

        :param done: bytes so far.
        :param total: bytes expected, or ``None``.
        """
        self.show(f"{self.__label}: {self.__file}  {human_bytes(done)} / {human_bytes(total or 0)}")

    def show(self, text: str) -> None:
        """Draw the progress line, cut to the terminal's width.

        :param text: what is being done.
        """
        if not self.__interactive:
            return
        width = shutil.get_terminal_size().columns - 1
        sys.stdout.write("\r" + text[:width].ljust(width))
        sys.stdout.flush()
        self.__drawn = True

    def clear(self) -> None:
        """Erase the progress line, when one is drawn."""
        if self.__drawn:
            width = shutil.get_terminal_size().columns - 1
            sys.stdout.write("\r" + " " * width + "\r")
            self.__drawn = False


def human_bytes(size: int) -> str:
    """A byte count a person reads.

    :param size: bytes.
    :returns: e.g. ``"1.5 GiB"``.
    """
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TiB"


def records_under(folder: Path, *, recursive: bool, failures: list[str]) -> list[Path]:
    """The ``.checksum`` files of a folder, in the order of their paths.

    :param folder: the folder.
    :param recursive: whether to go down into its sub-folders.
    :param failures: told of each folder that would not list.
    :returns: the files.
    """

    def failed(error: OSError) -> None:
        """Remember one folder that would not list.

        :param error: what the walk raised.
        """
        failures.append(f"{error.filename}: {error.strerror}")

    found: list[Path] = []
    for directory, _, names in os.walk(folder, onerror=failed):
        found.extend(Path(directory) / name for name in names if name.lower().endswith(CHECKSUM_RECORD_SUFFIX))
        if not recursive:
            break
    return sorted(found)


def resolve_records(paths: Sequence[Path], *, recursive: bool, failures: list[str]) -> Iterator[Path]:
    """Each distinct record the paths stand for, in order.

    :param paths: the command line's paths.
    :param recursive: whether a folder is read at any depth.
    :param failures: told of each path that is no record, is not found, or holds none.
    :returns: the ``.checksum`` files.
    """
    seen: set[Path] = set()
    for path in paths:
        if path.is_dir():
            found = records_under(path, recursive=recursive, failures=failures)
            if not found:
                failures.append(f"{path}: no {CHECKSUM_RECORD_SUFFIX} file found")
        elif not path.exists():
            failures.append(f"{path}: not found")
            continue
        elif path.name.lower().endswith(CHECKSUM_RECORD_SUFFIX):
            found = [path]
        else:
            failures.append(f"{path}: not a {CHECKSUM_RECORD_SUFFIX} file or a folder")
            continue
        for record in found:
            key = record.resolve()
            if key not in seen:
                seen.add(key)
                yield record


def has_finding(inspection: ChecksumInspection) -> bool:
    """Whether a record has anything to say, which is what the exit status and ``--quiet`` turn on.

    :param inspection: what the check established.
    :returns: whether a file mismatched, is missing, could not be read, has no checksum, or a branch would not list.
    """
    report = inspection.report
    return bool(
        inspection.findings or inspection.without_checksum or report.unnamed_malformed or report.unreadable_directories
    )


def describe(record: Path, inspection: ChecksumInspection, *, verbose: bool, quiet: bool) -> list[str]:
    """The lines one record is shown as.

    :param record: the ``.checksum`` file.
    :param inspection: what the check established.
    :param verbose: name every file, not only the ones with a finding.
    :param quiet: show only a record with a finding.
    :returns: the lines: the record's own, then one per file named.
    """
    if quiet and not has_finding(inspection):
        return []
    summary = checksum_report_summary(inspection.report)
    if inspection.without_checksum:
        summary += f", {len(inspection.without_checksum)} without a checksum"
    lines = [f"{record}: {summary}"]
    for name, status in inspection.report.statuses.items():
        if verbose or status not in CLEAN_FILE_STATUSES:
            lines.append(f"  {status}: {name}")
    lines.extend(f"  unreadable: {name}" for name in inspection.report.unreadable)
    lines.extend(f"  unreadable folder: {name}" for name in inspection.report.unreadable_directories)
    lines.extend(f"  no checksum: {name}" for name in inspection.without_checksum)
    return lines


def build_parser() -> argparse.ArgumentParser:
    """The command line.

    :returns: the parser.
    """
    parser = argparse.ArgumentParser(
        prog="verify_checksums",
        description="Verify .checksum records without the app, reading only.",
    )
    parser.add_argument("paths", nargs="+", type=Path, help=".checksum files or folders holding them")
    parser.add_argument("--no-recursive", action="store_true", help="only the .checksum files directly in a folder")
    parser.add_argument(
        "--show-without-checksum",
        action="store_true",
        help="also list the content files a record does not list",
    )
    parser.add_argument(
        "--no-checksum",
        action="store_true",
        help="hash nothing: only check that each listed file exists",
    )
    parser.add_argument("--exclude", action="append", default=[], metavar="GLOB", help="also exclude GLOB for this run")
    parser.add_argument(
        "--settings-dir",
        metavar="DIR",
        type=Path,
        help=f"read the app's settings from DIR, as rehuco-agent's own option (default: "
        f"${SETTINGS_DIR_ENVIRONMENT_VARIABLE}, else the platform's locations)",
    )
    volume = parser.add_mutually_exclusive_group()
    volume.add_argument("--quiet", action="store_true", help="only the records with a finding, and the total")
    volume.add_argument("--verbose", action="store_true", help="name every file")
    return parser


def set_settings_folder(parser: argparse.ArgumentParser, flag: Path | None) -> None:
    """Make the folder whose settings this run reads the app's settings location, before any is read.

    The app's own resolution (:func:`rehuco_agent.__main__.resolve_settings_dir`): the flag, else the environment's,
    else ``None`` for the platform's locations. Nothing is created, unlike the app's, which starts a folder.

    :param parser: reports a path that is not a folder, and exits.
    :param flag: ``--settings-dir``, or ``None``.
    """
    folder = resolve_settings_dir(flag, os.environ.get(SETTINGS_DIR_ENVIRONMENT_VARIABLE))
    if folder is not None:
        if folder.exists() and not folder.is_dir():
            parser.error(f"--settings-dir: {folder} is not a folder")
        set_settings_dir(folder)


def main(argv: list[str] | None = None) -> int:
    """Verify the records the command line names.

    :param argv: command-line arguments; ``None`` reads them from ``sys.argv``.
    :returns: the exit status, see the module's docstring.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    set_settings_folder(parser, args.settings_dir)
    app_patterns = shared_excluded_files_settings().excluded_file_patterns
    patterns = (*app_patterns, *(extra for extra in args.exclude if extra not in app_patterns))
    for stream in (sys.stdout, sys.stderr):
        # a piped stream on Windows is the ANSI code page's, which refuses most of the names a library holds
        if isinstance(stream, io.TextIOWrapper) and not stream.isatty():
            stream.reconfigure(encoding="utf-8")
    console = Console(sys.stdout.isatty())
    console.say(f"settings: {folders().settings}; excluded: {', '.join(patterns)}")
    failures: list[str] = []
    totals = Totals()
    found = False
    try:
        for record in resolve_records(args.paths, recursive=not args.no_recursive, failures=failures):
            console.begin(record)
            try:
                inspection = inspect_checksums(
                    record.with_suffix(REHU_SUFFIX),
                    excluded_patterns=patterns,
                    hash_files=not args.no_checksum,
                    list_without_checksum=args.show_without_checksum,
                    progress=console.on_bytes,
                    # nothing is hashed without checksums, and no progress line is drawn
                    on_file=None if args.no_checksum else console.on_file,
                )
            except (OSError, ChecksumRecordError, ContentUnreachableError) as error:
                failures.append(f"{record}: {error}")
                continue
            totals.add(inspection)
            found = found or has_finding(inspection)
            for line in describe(record, inspection, verbose=args.verbose, quiet=args.quiet):
                console.say(line)
    except KeyboardInterrupt:
        console.say(f"Interrupted. {totals.line()}")
        return EXIT_INTERRUPTED
    for failure in failures:
        console.say(failure, error=True)
    totals.unreadable_records = len(failures)
    console.say(totals.line())
    if failures:
        return EXIT_UNREADABLE
    return EXIT_FOUND if found else EXIT_CLEAN


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
