"""Tests for a path made absolute without being resolved (#511)."""

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import patch

from borco_core import absolute_path
from pytest import MonkeyPatch, mark


@contextmanager
def nothing_asked() -> Iterator[None]:
    """Make every call that would ask the disk or the network about a path fail the test while the block runs.

    :yields: nothing; the block makes the call under test.
    """
    refused = AssertionError("the path was looked up")
    with ExitStack() as stack:
        for target in ("os.stat", "os.lstat", "os.path.realpath", "pathlib.Path.resolve", "pathlib.Path.stat"):
            stack.enter_context(patch(target, side_effect=refused))
        yield


def test_a_relative_path_is_joined_to_the_working_directory_and_folded(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A relative path is made absolute against the working directory, its ``.`` and ``..`` folded, as a string or a
    path alike -- and the folder it names need not exist.

    **Test steps:**

    * change to a temporary folder, and refuse every lookup of a path
    * verify ``a/./b/../c`` as a string and as a path both become ``<cwd>/a/c``, which is not there
    """
    monkeypatch.chdir(tmp_path)

    with nothing_asked():
        from_string = absolute_path("a/./b/../c")
        from_path = absolute_path(Path("a") / "." / "b" / ".." / "c")

    assert from_string == from_path == Path.cwd() / "a" / "c"
    assert not from_string.exists()


def test_an_absolute_path_is_only_folded(tmp_path: Path) -> None:
    """An absolute path keeps everything but its ``..``.

    **Test steps:**

    * refuse every lookup, and make ``<tmp>/x/../y`` absolute
    * verify it is ``<tmp>/y``
    """
    with nothing_asked():
        made = absolute_path(tmp_path / "x" / ".." / "y")

    assert made == tmp_path / "y"


@mark.windows
def test_a_drive_letter_is_kept_as_typed_never_resolved_to_its_share() -> None:
    """A mapped drive's path keeps its letter: ``resolve`` would follow it to the share behind it, asking the server.
    Every lookup is refused, so the test needs no mapped drive and proves none was made.

    **Test steps:**

    * refuse every lookup, and make ``T:\\DATA2\\x\\..\\y`` absolute
    * verify it is ``T:\\DATA2\\y``
    """
    with nothing_asked():
        made = absolute_path(r"T:\DATA2\x\..\y")

    assert made == Path(r"T:\DATA2\y")
    assert str(made).startswith("T:")
