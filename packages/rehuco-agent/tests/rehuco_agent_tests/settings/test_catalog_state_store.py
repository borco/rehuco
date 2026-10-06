"""Tests for the per-catalog state file: the Browsers dock's browsers and layout (#396, #461).

No file is ever created: ``Path.read_text`` serves the file and ``atomic_write_text`` is captured.
"""

import json
import logging
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

from pytest import LogCaptureFixture, fixture
from pytest_mock import MockerFixture
from rehuco_agent.settings import catalog_state_store as store_module
from rehuco_agent.settings.catalog_state_store import (
    TABLE_BROWSER_KIND,
    BrowserState,
    CatalogState,
    CatalogStateStore,
    catalog_state_path,
)

REHUCO_ID = uuid4()
FIRST = BrowserState(uuid4(), TABLE_BROWSER_KIND, "Everything", 'type:"tutorial"', b"\x00\x01header")
SECOND = BrowserState(uuid4(), TABLE_BROWSER_KIND, "Tutorials")
STATE = CatalogState([FIRST, SECOND], layout=b"layout\xff")


@fixture(autouse=True)
def config(mocker: MockerFixture) -> None:
    """A fixed config folder, so no test reads the developer's real one."""
    mocker.patch.object(store_module, "config_folder", return_value=Path("/fake/config"))


@fixture(name="written")
def written_fixture(mocker: MockerFixture) -> MagicMock:
    """The captured write, with the folder creation mocked away."""
    mocker.patch.object(Path, "mkdir", autospec=True)
    return mocker.patch.object(store_module, "atomic_write_text")


def serve(mocker: MockerFixture, text: str) -> None:
    """Make every ``read_text`` answer ``text``.

    :param mocker: the mocker.
    :param text: what the file holds.
    """
    mocker.patch.object(Path, "read_text", return_value=text)


def saved_text(written: MagicMock) -> str:
    """What the last write was asked to put on disk.

    :param written: the captured ``atomic_write_text``.
    :returns: the text.
    """
    return written.call_args[0][1]


def test_the_path_is_the_ids_json_in_the_catalogs_folder() -> None:
    """The file is named by the rehuco id, in a folder of its own, and two ids never share one.

    **Test steps:**

    * ask for the path of a known id and of another
    * verify the first is ``<config>/catalogs/<id>.json`` and the two differ
    """
    assert catalog_state_path(REHUCO_ID) == Path("/fake/config/catalogs") / f"{REHUCO_ID}.json"
    assert catalog_state_path(REHUCO_ID) != catalog_state_path(uuid4())


def test_a_state_survives_a_round_trip(mocker: MockerFixture, written: MagicMock) -> None:
    """Browsers keep their order, names, filters and bytes, and so do the layout and the roots header.

    **Test steps:**

    * save a state, then serve the written text back and load it
    * verify the loaded state equals the saved one
    """
    store = CatalogStateStore()
    store.save(REHUCO_ID, STATE)
    serve(mocker, saved_text(written))

    assert store.load(REHUCO_ID) == STATE


def test_a_save_writes_the_ids_path_and_creates_its_folder(mocker: MockerFixture) -> None:
    """The write goes to the id's path, after making the folder that may not exist yet.

    **Test steps:**

    * save a state with ``mkdir`` and the write captured
    * verify the folder was made and the write named the id's path
    """
    mkdir = mocker.patch.object(Path, "mkdir", autospec=True)
    write = mocker.patch.object(store_module, "atomic_write_text")

    CatalogStateStore().save(REHUCO_ID, STATE)

    mkdir.assert_called_once()
    assert write.call_args[0][0] == catalog_state_path(REHUCO_ID)


def test_a_missing_file_is_an_empty_state(mocker: MockerFixture) -> None:
    """A catalog never seen before has nothing remembered.

    **Test steps:**

    * make the read raise ``FileNotFoundError``
    * verify the state is empty
    """
    mocker.patch.object(Path, "read_text", side_effect=FileNotFoundError)

    assert CatalogStateStore().load(REHUCO_ID) == CatalogState()


def test_an_unreadable_file_is_an_empty_state_and_logged(mocker: MockerFixture, caplog: LogCaptureFixture) -> None:
    """A read that fails costs the remembered state, and says so.

    **Test steps:**

    * make the read raise ``OSError``
    * verify the state is empty and an error was logged
    """
    mocker.patch.object(Path, "read_text", side_effect=OSError("denied"))

    with caplog.at_level(logging.ERROR):
        state = CatalogStateStore().load(REHUCO_ID)

    assert state == CatalogState()
    assert "could not be read" in caplog.text


def test_a_file_that_is_not_json_is_an_empty_state(mocker: MockerFixture) -> None:
    """Damaged text is ignored.

    **Test steps:**

    * serve text that is not JSON
    * verify the state is empty
    """
    serve(mocker, "{not json")

    assert CatalogStateStore().load(REHUCO_ID) == CatalogState()


def test_another_version_is_an_empty_state(mocker: MockerFixture) -> None:
    """A file of another version is not guessed at.

    **Test steps:**

    * serve a file stamped with a different version
    * verify the state is empty
    """
    serve(mocker, json.dumps({"version": 99, "browsers": [{"id": str(uuid4()), "kind": "table", "name": "x"}]}))

    assert CatalogStateStore().load(REHUCO_ID) == CatalogState()


def test_a_file_from_before_the_split_keeps_its_browsers_and_drops_its_layout(
    mocker: MockerFixture, written: MagicMock
) -> None:
    """A version 1 file's layout nests the Roots view among the browsers, which no longer share a shell with it:
    its browsers are read whole, its layout not at all (#461).

    **Test steps:**

    * save the state, then serve what was written stamped as version 1
    * verify the browsers -- names, filters, columns -- come back and the layout is empty
    """
    CatalogStateStore().save(REHUCO_ID, STATE)
    values = json.loads(saved_text(written))
    values["version"] = 1
    serve(mocker, json.dumps(values))

    assert CatalogStateStore().load(REHUCO_ID) == CatalogState([FIRST, SECOND])


def test_malformed_and_repeated_browsers_are_skipped(mocker: MockerFixture, written: MagicMock) -> None:
    """A bad entry costs only itself.

    **Test steps:**

    * serve a file whose list holds a good browser, a repeat of it, junk, an id that is not a uuid and a missing name
    * verify only the first good browser is read
    """
    CatalogStateStore().save(REHUCO_ID, CatalogState([FIRST]))
    values = json.loads(saved_text(written))
    good = values["browsers"][0]
    nameless = {key: value for key, value in good.items() if key != "name"}
    values["browsers"] = [good, dict(good), "junk", {**good, "id": "nope"}, nameless]
    serve(mocker, json.dumps(values))

    assert CatalogStateStore().load(REHUCO_ID).browsers == [FIRST]


def test_a_browsers_value_that_is_not_a_list_is_no_browsers(mocker: MockerFixture) -> None:
    """A damaged list costs the browsers, not the layout.

    **Test steps:**

    * serve a file whose ``browsers`` is a string but whose layout is intact
    * verify no browsers and the layout read
    """
    serve(mocker, json.dumps({"version": 2, "browsers": "nope", "layout": "bGF5b3V0"}))

    state = CatalogStateStore().load(REHUCO_ID)

    assert not state.browsers
    assert state.layout == b"layout"


def test_a_file_that_still_carries_a_roots_header_loads(mocker: MockerFixture) -> None:
    """The Roots table's header state a build before the column view wrote is ignored, not an error (#378).

    **Test steps:**

    * serve a file with a layout and a ``roots_header``
    * verify the layout is read and nothing else is lost
    """
    serve(mocker, json.dumps({"version": 2, "browsers": [], "layout": "bGF5b3V0", "roots_header": "cm9vdHM="}))

    assert CatalogStateStore().load(REHUCO_ID) == CatalogState(layout=b"layout")


def test_damaged_bytes_read_as_empty(mocker: MockerFixture, written: MagicMock) -> None:
    """A base64 value that does not decode is an empty blob, not an error.

    **Test steps:**

    * serve a file whose layout and a browser's columns are not valid base64
    * verify each reads as empty bytes
    """
    CatalogStateStore().save(REHUCO_ID, CatalogState([FIRST]))
    values = json.loads(saved_text(written))
    values["layout"] = "!!!"
    values["browsers"][0]["columns"] = "é"
    serve(mocker, json.dumps(values))

    state = CatalogStateStore().load(REHUCO_ID)

    assert state.layout == b""
    assert state.browsers == [BrowserState(FIRST.browser_id, FIRST.kind, FIRST.name, FIRST.filter)]


def test_missing_or_non_text_bytes_read_as_empty(mocker: MockerFixture, written: MagicMock) -> None:
    """A blob that is absent or not a string is an empty blob, not an error.

    **Test steps:**

    * serve a file with no layout and a browser whose columns are ``null``
    * verify each reads as empty bytes and the browser is kept
    """
    CatalogStateStore().save(REHUCO_ID, CatalogState([FIRST]))
    values = json.loads(saved_text(written))
    del values["layout"]
    values["browsers"][0]["columns"] = None
    serve(mocker, json.dumps(values))

    state = CatalogStateStore().load(REHUCO_ID)

    assert state.layout == b""
    assert state.browsers == [BrowserState(FIRST.browser_id, FIRST.kind, FIRST.name, FIRST.filter)]


def test_a_failed_write_is_logged_not_raised(mocker: MockerFixture, caplog: LogCaptureFixture) -> None:
    """Losing the layout must not block closing.

    **Test steps:**

    * make the write raise ``OSError`` and save
    * verify nothing was raised and an error was logged
    """
    mocker.patch.object(Path, "mkdir", autospec=True)
    mocker.patch.object(store_module, "atomic_write_text", side_effect=OSError("disk full"))

    with caplog.at_level(logging.ERROR):
        CatalogStateStore().save(REHUCO_ID, STATE)

    assert "could not be saved" in caplog.text
