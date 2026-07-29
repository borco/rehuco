"""Tests for the Keep a Changelog section extractor used to build GitHub Release notes."""

from pathlib import Path

from pytest import mark, raises
from pytest_mock import MockerFixture

from tools import extract_changelog

# region Fixtures / helpers

CHANGELOG = """# Changelog

Preamble prose that is not part of any release.

## [Unreleased]

## [0.1.0] - 2026-08-01

### Added

- A second thing.

## [0.0.1] - 2026-07-29

First tagged release.

### Added

- A first thing.

### Known limitations

- Not signed.
"""


def run_main(mocker: MockerFixture, text: str, version: str) -> tuple[int, str, str]:
    """Run ``main()`` against an in-memory changelog, with no real disk I/O.

    :param mocker: pytest-mock fixture.
    :param text: the changelog contents ``read_text`` should return.
    :param version: version argument to pass on the command line.
    :returns: the exit code, everything printed to stdout, and everything printed to stderr.
    """
    mocker.patch.object(Path, "read_text", lambda self, encoding="utf-8": text)
    print_mock = mocker.patch("builtins.print")

    exit_code = extract_changelog.main(["CHANGELOG.md", version])

    out = "\n".join(call.args[0] for call in print_mock.call_args_list if "file" not in call.kwargs)
    err = "\n".join(call.args[0] for call in print_mock.call_args_list if "file" in call.kwargs)
    return exit_code, out, err


# endregion

# region extract tests


def test_extract_returns_the_section_body_without_its_heading() -> None:
    """The heading itself is dropped -- the release already carries the version in its title."""
    section = extract_changelog.extract(CHANGELOG, "0.0.1")

    assert section.startswith("First tagged release.")
    assert "## [0.0.1]" not in section


def test_extract_stops_at_the_next_version_heading() -> None:
    """A middle section must not swallow the older entries below it."""
    section = extract_changelog.extract(CHANGELOG, "0.1.0")

    assert "A second thing." in section
    assert "A first thing." not in section


def test_extract_keeps_subsections_of_the_requested_version() -> None:
    """Level-3 headings belong to the section; only a level-2 heading ends it."""
    section = extract_changelog.extract(CHANGELOG, "0.0.1")

    assert "### Added" in section
    assert "### Known limitations" in section


def test_extract_reads_the_last_section_to_the_end_of_the_file() -> None:
    """The oldest entry has no following heading to stop at."""
    section = extract_changelog.extract(CHANGELOG, "0.0.1")

    assert section.endswith("- Not signed.")


def test_extract_excludes_the_preamble() -> None:
    """Prose above the first version heading is never part of a release body."""
    section = extract_changelog.extract(CHANGELOG, "0.0.1")

    assert "Preamble prose" not in section


def test_extract_returns_empty_for_a_heading_with_no_body() -> None:
    """``## [Unreleased]`` is a real heading with nothing under it; main() rejects that separately."""
    assert extract_changelog.extract(CHANGELOG, "Unreleased") == ""


def test_extract_raises_for_an_unknown_version() -> None:
    """A version with no section must fail loudly rather than yield empty notes."""
    with raises(KeyError):
        extract_changelog.extract(CHANGELOG, "9.9.9")


# endregion

# region main tests


def test_main_prints_the_section_and_succeeds(mocker: MockerFixture) -> None:
    """The happy path writes the section to stdout for `--notes-file` to pick up."""
    exit_code, out, err = run_main(mocker, CHANGELOG, "0.0.1")

    assert exit_code == 0
    assert "First tagged release." in out
    assert err == ""


@mark.parametrize(
    ("version", "reason"),
    [("9.9.9", "no section for version"), ("Unreleased", "is empty")],
)
def test_main_fails_rather_than_publishing_blank_notes(mocker: MockerFixture, version: str, reason: str) -> None:
    """A missing or empty section stops the release while the tag can still be moved.

    :param version: version whose section is absent or empty.
    :param reason: fragment the diagnostic must carry, so the two cases stay distinguishable.
    """
    exit_code, out, err = run_main(mocker, CHANGELOG, version)

    assert exit_code == 1
    assert out == ""
    assert reason in err


# endregion
