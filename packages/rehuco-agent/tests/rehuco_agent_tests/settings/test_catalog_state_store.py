"""Tests for the per-catalog state file: the Browsers dock's layout, each browser in its sub-dock's entry (#396,
#461, #102).

The config folder is the test's ``tmp_path``: every file is real, and nothing outside it is touched.
"""

import json
import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

from pytest import LogCaptureFixture, fixture, mark
from pytest_mock import MockerFixture
from rehuco_agent.settings import catalog_state_store as store_module
from rehuco_agent.settings.catalog_state_store import (
    CATALOG_STATE_VERSION,
    TABLE_BROWSER_KIND,
    BrowserState,
    CatalogState,
    CatalogStateStore,
    catalog_state_path,
)

REHUCO_ID = uuid4()
FIRST = BrowserState(uuid4(), TABLE_BROWSER_KIND, "Everything", 'type:"tutorial"', b"\x00\x01header")
LAYOUT: dict[str, Any] = {
    "format": 1,
    "main": {
        "split": "h",
        "sizes": [300, 500],
        "children": [
            {"area": [{"name": str(FIRST.browser_id), "closed": False, "state": "c3RhdGU="}]},
            {"area": [{"name": "other", "closed": True}], "current": "other"},
        ],
    },
}
STATE = CatalogState(LAYOUT)
NOT_UTF8 = bytes([0xFF, 0xFE, 0x7B])


@fixture(name="config")
def config_fixture(real_path_stat: None, mocker: MockerFixture, tmp_path: Path) -> Path:
    """The test's own config folder, so no test reads or writes the developer's real one.

    :param real_path_stat: the real ``Path.stat``, which the atomic write of a new file needs.
    :param mocker: the mocker.
    :param tmp_path: the test's folder.
    :returns: the config folder.
    """
    del real_path_stat
    mocker.patch.object(store_module, "config_folder", return_value=tmp_path)
    return tmp_path


def serve(text: str) -> None:
    """Put ``text`` where the state of :data:`REHUCO_ID` is read from.

    :param text: what the file holds.
    """
    path = catalog_state_path(REHUCO_ID)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_the_path_is_the_ids_json_in_the_catalogs_folder(config: Path) -> None:
    """The file is named by the rehuco id, in a folder of its own, and two ids never share one.

    **Test steps:**

    * ask for the path of a known id and of another
    * verify the first is ``<config>/catalogs/<id>.json`` and the two differ
    """
    assert catalog_state_path(REHUCO_ID) == config / "catalogs" / f"{REHUCO_ID}.json"
    assert catalog_state_path(REHUCO_ID) != catalog_state_path(uuid4())


@mark.usefixtures("config")
def test_a_layout_survives_a_round_trip() -> None:
    """The layout comes back as it was saved: its splits, sizes, entries and their states.

    **Test steps:**

    * save a state, then load it
    * verify the loaded state equals the saved one
    """
    store = CatalogStateStore()
    store.save(REHUCO_ID, STATE)

    assert store.load(REHUCO_ID) == STATE


@mark.usefixtures("config")
def test_no_layout_survives_a_round_trip() -> None:
    """A state with no layout -- one default browser next time -- is saved as such, not as an empty layout.

    **Test steps:**

    * save an empty state, then load it
    * verify the layout is ``None``
    """
    store = CatalogStateStore()
    store.save(REHUCO_ID, CatalogState())

    assert store.load(REHUCO_ID) == CatalogState(None)


@mark.usefixtures("config")
def test_a_save_writes_the_ids_path_and_creates_its_folder() -> None:
    """The write goes to the id's path, after making the folder that does not exist yet.

    **Test steps:**

    * save a state into a config folder with no ``catalogs`` folder
    * verify the id's file now holds this version and the layout
    """
    CatalogStateStore().save(REHUCO_ID, STATE)

    written = json.loads(catalog_state_path(REHUCO_ID).read_text(encoding="utf-8"))
    assert written == {"version": CATALOG_STATE_VERSION, "layout": LAYOUT}


@mark.usefixtures("config")
def test_a_missing_file_is_an_empty_state() -> None:
    """A catalog never seen before has nothing remembered.

    **Test steps:**

    * load an id no file was written for
    * verify the state has no layout
    """
    assert CatalogStateStore().load(REHUCO_ID) == CatalogState(None)


@mark.usefixtures("config")
def test_an_unreadable_file_is_an_empty_state_and_logged(caplog: LogCaptureFixture) -> None:
    """A read that fails costs the remembered state, and says so.

    **Test steps:**

    * put a folder where the id's file should be, so reading it fails
    * verify the state has no layout and an error was logged
    """
    catalog_state_path(REHUCO_ID).mkdir(parents=True)

    with caplog.at_level(logging.ERROR):
        state = CatalogStateStore().load(REHUCO_ID)

    assert state == CatalogState(None)
    assert "could not be read" in caplog.text


@mark.usefixtures("config")
def test_a_file_that_is_not_json_is_an_empty_state() -> None:
    """Damaged text is ignored.

    **Test steps:**

    * serve text that is not JSON
    * verify the state has no layout
    """
    serve("{not json")

    assert CatalogStateStore().load(REHUCO_ID) == CatalogState(None)


@mark.usefixtures("config")
@mark.parametrize(
    "values",
    [
        {"version": 99, "layout": LAYOUT},
        {"version": 1, "layout": LAYOUT},
        {"layout": LAYOUT},
        [CATALOG_STATE_VERSION, LAYOUT],
    ],
    ids=["a later version", "an earlier version", "no version", "not an object"],
)
def test_a_file_of_another_shape_is_an_empty_state(values: object) -> None:
    """A file of another version, or no state file at all, is not guessed at: its layout is not read.

    **Test steps:**

    * serve a file whose version is not this build's, or that is not an object
    * verify the state has no layout
    """
    serve(json.dumps(values))

    assert CatalogStateStore().load(REHUCO_ID) == CatalogState(None)


@mark.usefixtures("config")
@mark.parametrize("layout", [None, "bGF5b3V0", [LAYOUT], 7], ids=["null", "a string", "a list", "a number"])
def test_a_layout_that_is_not_an_object_is_no_layout(layout: object) -> None:
    """A layout value that is not a tree -- an old base64 blob among them -- opens the default browser.

    **Test steps:**

    * serve a file of this version whose layout is not an object
    * verify the state has no layout
    """
    serve(json.dumps({"version": CATALOG_STATE_VERSION, "layout": layout}))

    assert CatalogStateStore().load(REHUCO_ID) == CatalogState(None)


def test_a_failed_write_is_logged_not_raised(config: Path, caplog: LogCaptureFixture) -> None:
    """Losing the layout must not block closing.

    **Test steps:**

    * put a file where the ``catalogs`` folder should be, so the save cannot make it
    * save, and verify nothing was raised and an error was logged
    """
    (config / store_module.CATALOG_STATE_FOLDER).write_text("", encoding="utf-8")

    with caplog.at_level(logging.ERROR):
        CatalogStateStore().save(REHUCO_ID, STATE)

    assert "could not be saved" in caplog.text


# region A browser in its layout entry


def entry(**values: object) -> bytes:
    """A browser entry as :meth:`BrowserState.to_bytes` writes :data:`FIRST`, with ``values`` replacing or adding keys.

    :param values: the keys to change; ``None`` removes one.
    :returns: the entry's bytes.
    """
    fields = json.loads(FIRST.to_bytes())
    fields.update(values)
    return json.dumps({key: value for key, value in fields.items() if value is not None}).encode("utf-8")


def test_a_browser_survives_a_round_trip_through_its_bytes() -> None:
    """A browser's entry keeps its id, kind, name, filter and header state.

    **Test steps:**

    * turn a browser with columns into bytes and back, and one with none
    * verify each equals the original
    """
    bare = BrowserState(uuid4(), TABLE_BROWSER_KIND, "Tutorials")

    assert BrowserState.from_bytes(FIRST.to_bytes()) == FIRST
    assert BrowserState.from_bytes(bare.to_bytes()) == bare


def test_a_browser_with_no_filter_or_bad_columns_reads_with_none() -> None:
    """A filter left out is no filter, and columns that are missing or not base64 are no header state.

    **Test steps:**

    * read entries with no filter, no columns and columns that do not decode
    * verify each reads, with an empty filter or empty columns
    """
    assert BrowserState.from_bytes(entry(filter=None)) == BrowserState(
        FIRST.browser_id, FIRST.kind, FIRST.name, "", FIRST.columns
    )
    no_columns = BrowserState(FIRST.browser_id, FIRST.kind, FIRST.name, FIRST.filter)
    assert BrowserState.from_bytes(entry(columns=None)) == no_columns
    assert BrowserState.from_bytes(entry(columns="!!!")) == no_columns


@mark.parametrize(
    "data",
    [
        b"\xff\xfe",
        b"{not json",
        b'["a", "list"]',
        entry(id=None),
        entry(id="not a uuid"),
        entry(kind=None),
        entry(kind=3),
        entry(name=None),
        entry(name=["x"]),
        entry(filter=False),
    ],
    ids=[
        "not utf-8",
        "not json",
        "not an object",
        "no id",
        "a bad id",
        "no kind",
        "a kind that is not text",
        "no name",
        "a name that is not text",
        "a filter that is not text",
    ],
)
def test_an_entry_that_is_not_a_browser_reads_as_none(data: bytes) -> None:
    """An entry that cannot be a browser is refused whole, rather than built half-way.

    **Test steps:**

    * read the damaged entry
    * verify there is no browser
    """
    assert BrowserState.from_bytes(data) is None


# endregion


@mark.usefixtures("config")
def test_a_file_that_is_not_utf8_is_an_empty_state_kept_as_bak_by_the_next_save(caplog: LogCaptureFixture) -> None:
    """Bytes no decoder takes do not stop the agent, and the next save does not destroy them (#478).

    **Test steps:**

    * put a file that is not valid UTF-8 where the id's state is read from
    * verify it loads as an empty state, logged
    * save a state
    * verify the new state is in place and the old bytes are in ``<name>.bak``
    """
    path = catalog_state_path(REHUCO_ID)
    path.parent.mkdir(parents=True)
    path.write_bytes(NOT_UTF8)
    store = CatalogStateStore()

    with caplog.at_level(logging.ERROR):
        assert store.load(REHUCO_ID) == CatalogState(None)
    store.save(REHUCO_ID, STATE)

    assert "could not be read" in caplog.text
    assert store.load(REHUCO_ID) == STATE
    assert path.with_name(path.name + ".bak").read_bytes() == NOT_UTF8
