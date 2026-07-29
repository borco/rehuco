"""Extract one version's section from a Keep a Changelog file, to use as GitHub Release notes.

The release workflow pipes this into `gh release create --notes-file`, so a tagged release's body is
the same text the repository already carries under `packages/<package>/CHANGELOG.md` -- never a second
copy written by hand at release time, which is the copy that goes stale.

Failing is the point when a version has no section, or an empty one: a release whose notes are silently
blank looks identical to a release nobody wrote notes for, and the mistake is only visible after
publishing. Exiting non-zero instead stops the run while the tag can still be moved.
"""

import argparse
import re
import sys
from pathlib import Path

H2_RE = re.compile(r"^##\s")
"""Any level-2 heading -- what ends a version's section, whatever the next heading turns out to be."""

VERSION_H2_RE = re.compile(r"^##\s+\[(?P<version>[^\]]+)\]")
"""A Keep a Changelog version heading: ``## [0.0.1] - 2026-07-29``."""


def extract(text: str, version: str) -> str:
    """Return the body of ``text``'s ``## [<version>]`` section, without its own heading.

    :param text: full contents of a Keep a Changelog file.
    :param version: the version to extract, written without brackets (e.g. ``0.0.1``).
    :returns: the section body, with surrounding blank lines stripped.
    :raises KeyError: when no heading declares that version.
    """
    lines = text.splitlines()
    start: int | None = None
    for index, line in enumerate(lines):
        if start is not None and H2_RE.match(line):
            return "\n".join(lines[start:index]).strip("\n")
        match = VERSION_H2_RE.match(line)
        if start is None and match is not None and match["version"] == version:
            start = index + 1
    if start is None:
        raise KeyError(version)
    return "\n".join(lines[start:]).strip("\n")


def main(argv: list[str] | None = None) -> int:
    """Print one version's changelog section to stdout.

    :param argv: command-line arguments; ``None`` reads them from ``sys.argv``.
    :returns: process exit code -- non-zero when the section is missing or empty.
    """
    parser = argparse.ArgumentParser(
        prog="extract_changelog",
        description="Extract one version's section from a Keep a Changelog file.",
    )
    parser.add_argument("changelog", type=Path, help="path to a Keep a Changelog file")
    parser.add_argument("version", help="version to extract, without brackets (e.g. 0.0.1)")
    args = parser.parse_args(argv)

    try:
        section = extract(args.changelog.read_text(encoding="utf-8"), args.version)
    except KeyError:
        print(f"{args.changelog}: no section for version {args.version}", file=sys.stderr)
        return 1

    if not section:
        print(f"{args.changelog}: the section for version {args.version} is empty", file=sys.stderr)
        return 1

    print(section)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
