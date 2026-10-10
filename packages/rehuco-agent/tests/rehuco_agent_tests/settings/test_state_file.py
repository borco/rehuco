"""Tests for the versioned JSON state files (#404).

The file system is mocked the way ``test_catalog_state_store.py`` mocks it: reads come from a patched
``Path.read_text``, writes land in a patched ``atomic_write_text``, and no real folder is touched. conftest's autouse
``state_files`` replaces :func:`read_state_file` and :func:`write_state_file` for every other test, so these reach the
real functions through :data:`real_read` and :data:`real_write`, bound at import.
"""

import json
from pathlib import Path
from typing import Final
from unittest.mock import MagicMock

from pytest import LogCaptureFixture, fixture, mark
from pytest_mock import MockerFixture
from rehuco_agent.settings import state_file
from rehuco_agent.settings.state_file import decode_bytes, encode_bytes

real_read: Final = state_file.read_state_file
real_write: Final = state_file.write_state_file
FILE: Final = Path("/fake/config/state.json")


@fixture(name="written")
def written_fixture(mocker: MockerFixture) -> MagicMock:
    """The mocked atomic write, with folder creation mocked too."""
    mocker.patch.object(Path, "mkdir", autospec=True)
    return mocker.patch.object(state_file, "atomic_write_text")


def serve(mocker: MockerFixture, text: str) -> None:
    """Make every read answer ``text``."""
    mocker.patch.object(Path, "read_text", return_value=text)


def test_a_file_of_the_right_version_reads_back(mocker: MockerFixture) -> None:
    """The values come back as written, version included.

    **Test steps:**

    * serve a version 1 object
    * verify it is returned whole
    """
    serve(mocker, json.dumps({"version": 1, "answer": 42}))

    assert real_read(FILE, 1) == {"version": 1, "answer": 42}


def test_a_missing_file_reads_as_absent(mocker: MockerFixture) -> None:
    """A first run is not an error and is not logged as one.

    **Test steps:**

    * make the read raise ``FileNotFoundError``
    * verify ``None`` comes back
    """
    mocker.patch.object(Path, "read_text", side_effect=FileNotFoundError)

    assert real_read(FILE, 1) is None


def test_an_unreadable_file_reads_as_absent(mocker: MockerFixture) -> None:
    """A permission error costs the file's contents and nothing else.

    **Test steps:**

    * make the read raise ``PermissionError``
    * verify ``None`` comes back
    """
    mocker.patch.object(Path, "read_text", side_effect=PermissionError)

    assert real_read(FILE, 1) is None


def test_text_that_is_not_json_reads_as_absent(mocker: MockerFixture) -> None:
    """A file cut short by a crash is ignored.

    **Test steps:**

    * serve text that is not JSON
    * verify ``None`` comes back
    """
    serve(mocker, "{not json")

    assert real_read(FILE, 1) is None


def test_a_file_of_another_version_or_shape_reads_as_absent(mocker: MockerFixture) -> None:
    """A file this build does not understand is not guessed at.

    **Test steps:**

    * serve a version 2 object, a list and an object with no version
    * verify each reads as ``None`` for version 1
    """
    for text in (json.dumps({"version": 2}), json.dumps([1]), json.dumps({"answer": 42})):
        serve(mocker, text)

        assert real_read(FILE, 1) is None


def test_a_write_stamps_the_version_and_makes_the_folder(written: MagicMock) -> None:
    """The folder is made on the first write, and the file carries its version.

    **Test steps:**

    * write one value
    * verify the atomic write got the path and a JSON object holding the version and the value
    """
    real_write(FILE, 3, {"answer": 42})

    path, text = written.call_args.args
    assert path == FILE
    assert json.loads(text) == {"version": 3, "answer": 42}


def test_a_failed_write_is_logged_not_raised(written: MagicMock, caplog: LogCaptureFixture) -> None:
    """Losing a layout must not block closing.

    **Test steps:**

    * make the atomic write raise ``OSError``
    * verify the write returns and logs the failure
    """
    written.side_effect = OSError("disk full")

    real_write(FILE, 1, {})

    assert "could not be saved" in caplog.text


def test_a_blob_round_trips_through_its_text() -> None:
    """Binary state survives JSON.

    **Test steps:**

    * encode bytes that are not valid UTF-8 and decode them
    * verify they come back unchanged
    """
    blob = b"\x00\xff layout \x80"

    assert decode_bytes(encode_bytes(blob)) == blob


def test_a_damaged_blob_decodes_to_nothing() -> None:
    """A missing, mistyped or invalid blob costs only itself.

    **Test steps:**

    * decode ``None``, a number and text that is not base64
    * verify each is empty
    """
    assert [decode_bytes(value) for value in (None, 7, "not base64!", "é")] == [b""] * 4


# region An unreadable file is kept (#478)


@fixture(name="folder")
def folder_fixture(real_path_stat: None, tmp_path: Path) -> Path:
    """A real folder for the files, with the real ``Path.stat`` an atomic write needs."""
    del real_path_stat
    return tmp_path


def test_a_file_that_is_not_utf8_reads_as_absent_and_is_logged(folder: Path, caplog: LogCaptureFixture) -> None:
    """Bytes no decoder takes must not stop the agent starting.

    **Test steps:**

    * write a file that is not valid UTF-8
    * verify it reads as ``None`` and the failure was logged
    """
    path = folder / "state.json"
    path.write_bytes(b"\xff\xfe{")

    assert real_read(path, 1) is None
    assert "could not be read" in caplog.text


@mark.parametrize(
    "content",
    [b"\xff\xfe{", b"{not json", json.dumps({"version": 2}).encode(), json.dumps([1]).encode()],
    ids=["not-utf8", "not-json", "other-version", "not-an-object"],
)
def test_a_file_that_read_as_absent_is_kept_as_bak_by_the_next_write(folder: Path, content: bytes) -> None:
    """The load that follows starts empty, and its save must not destroy the file.

    **Test steps:**

    * write a file that reads as absent, read it, then write a state to the same path
    * verify the new state is in place and the old bytes are in ``<name>.bak``
    """
    path = folder / "state.json"
    path.write_bytes(content)
    assert real_read(path, 1) is None

    real_write(path, 1, {"answer": 42})

    assert real_read(path, 1) == {"version": 1, "answer": 42}
    assert (folder / "state.json.bak").read_bytes() == content


def test_a_read_that_fails_with_permission_error_keeps_the_file(folder: Path, mocker: MockerFixture) -> None:
    """A lock at startup gone by the time of the save leaves the good file recoverable.

    **Test steps:**

    * write a good file, make one read of it raise ``PermissionError``
    * write a state to the path
    * verify the good file's content is in ``<name>.bak``
    """
    path = folder / "state.json"
    path.write_text(json.dumps({"version": 1, "answer": 1}), encoding="utf-8")
    read = mocker.patch.object(Path, "read_text", side_effect=PermissionError("locked"))
    assert real_read(path, 1) is None
    mocker.stop(read)

    real_write(path, 1, {"answer": 2})

    assert json.loads((folder / "state.json.bak").read_text(encoding="utf-8")) == {"version": 1, "answer": 1}


def test_a_file_that_read_fine_or_was_never_read_gets_no_bak(folder: Path) -> None:
    """Only a failed read earns a backup, so an ordinary save leaves nothing behind.

    **Test steps:**

    * write a state, read it back and write again; write a state to another path never read
    * verify no ``.bak`` exists
    """
    path = folder / "state.json"
    real_write(path, 1, {"answer": 1})
    assert real_read(path, 1) is not None
    real_write(path, 1, {"answer": 2})
    real_write(folder / "other.json", 1, {})

    assert not list(folder.glob("*.bak"))


def test_the_file_is_kept_once_however_many_saves_follow(folder: Path) -> None:
    """The first save sets the damaged file aside; later saves replace the good one it wrote.

    **Test steps:**

    * read a damaged file, write twice
    * verify the ``.bak`` still holds the damaged bytes
    """
    path = folder / "state.json"
    path.write_bytes(b"\xff")
    assert real_read(path, 1) is None

    real_write(path, 1, {"answer": 1})
    real_write(path, 1, {"answer": 2})

    assert (folder / "state.json.bak").read_bytes() == b"\xff"


def test_a_set_aside_that_fails_is_tried_again_by_the_next_save(
    folder: Path, mocker: MockerFixture, caplog: LogCaptureFixture
) -> None:
    """A lock still held at save time must not forget the file.

    **Test steps:**

    * read a damaged file, make ``Path.replace`` fail and write
    * verify the failure was logged and no ``.bak`` exists
    * let the replace work and write again
    * verify the damaged bytes are in ``<name>.bak``
    """
    path = folder / "state.json"
    path.write_bytes(b"\xff")
    assert real_read(path, 1) is None
    replace = mocker.patch.object(Path, "replace", side_effect=PermissionError("locked"))

    real_write(path, 1, {"answer": 1})

    assert "could not be set aside" in caplog.text
    assert not (folder / "state.json.bak").exists()
    mocker.stop(replace)
    real_write(path, 1, {"answer": 2})
    assert (folder / "state.json.bak").exists()


# endregion
