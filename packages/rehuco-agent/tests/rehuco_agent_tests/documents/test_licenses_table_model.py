"""Tests for the License dock's list of a record's licenses as a table (#705, [[assets#licenses]]): what it shows, and
how each edit of it reaches the document -- a preset bringing its URL and asking for its text, a custom id keeping what
the row's user typed.

The document is a ``Mock(spec=...)``: its license edits are tested with it
(:mod:`~rehuco_agent_tests.documents.test_rehu_document_model_license`).
"""

from typing import Final
from unittest.mock import Mock

from PySide6.QtCore import QModelIndex, Qt
from pytest import fixture, mark
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.licenses_table_model import (
    HEADERS,
    LICENSE_COLUMN,
    LICENSE_MIME_TYPE,
    PRESET_URLS,
    URL_COLUMN,
    LicensesTableModel,
)
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_core import AssetLicense

URL: Final = "https://example.com/eula"
FIRST: Final = AssetLicense("fab-standard", URL)
SECOND: Final = AssetLicense("fab-uefn-reference-only")
THIRD: Final = AssetLicense("cc-by-4.0")
MINE: Final = "my-license"
"""A custom id: no preset names it."""
MINE_URL: Final = "https://example.com/mine"


@fixture(name="document")
def fixture_document() -> Mock:
    """A document never yet given licenses (``None``).

    :returns: the mock.
    """
    document = Mock(spec=RehuDocumentModel)
    document.licenses = None
    return document


def make(document: Mock, *entries: AssetLicense, editable: bool = True) -> LicensesTableModel:
    """A table over ``entries``.

    :param document: the document.
    :param entries: the licenses shown.
    :param editable: whether it edits.
    :returns: the model.
    """
    model = LicensesTableModel(document)
    model.set_entries(entries)
    model.set_editable(editable)
    return model


def cells(model: LicensesTableModel) -> list[list[str]]:
    """What each row shows.

    :param model: the model.
    :returns: each row's cells.
    """
    return [[model.index(row, column).data() for column in range(model.columnCount())] for row in range(model.count)]


# region what it shows


def test_each_license_is_a_row_of_its_id_and_url(document: Mock) -> None:
    """**Test steps:**

    * show two licenses
    * verify the rows, the headers, a row's tooltip, where each license is, and the ids another row holds
    """
    model = make(document, FIRST, SECOND)

    assert cells(model) == [[FIRST.license, URL], [SECOND.license, ""]]
    assert [model.headerData(column, Qt.Orientation.Horizontal) for column in range(2)] == list(HEADERS)
    assert model.index(0, URL_COLUMN).data(Qt.ItemDataRole.ToolTipRole) == URL
    assert model.entries == [FIRST, SECOND]
    assert (model.row_of(SECOND.license), model.row_of("other")) == (1, -1)
    assert (model.license_at(1), model.license_at(2), model.license_at(-1)) == (SECOND.license, None, None)
    assert model.taken(0) == {SECOND.license}


def test_every_preset_is_a_license_a_scan_writes_with_its_terms_address() -> None:
    """**Test steps:**

    * verify the presets and their addresses, the Marketplace license having none
    """
    assert PRESET_URLS == {
        "fab-standard": "https://www.fab.com/eula",
        "fab-uefn-reference-only": "https://www.fab.com/eula",
        "cc-by-4.0": "https://creativecommons.org/licenses/by/4.0/",
        "fab-ue-only": "",
    }


def test_what_qt_asks_beyond_the_rows_is_answered_as_nothing(document: Mock) -> None:
    """**Test steps:**

    * ask about an invalid index, a child of a row, a role not shown and a header not drawn
    * verify each is nothing
    """
    model = make(document, FIRST)

    assert model.data(QModelIndex()) is None
    assert model.index(0, 0).data(Qt.ItemDataRole.DecorationRole) is None
    assert model.flags(QModelIndex()) == Qt.ItemFlag.NoItemFlags
    assert (model.rowCount(model.index(0, 0)), model.columnCount(model.index(0, 0))) == (0, 0)
    assert model.headerData(0, Qt.Orientation.Vertical) == 1
    assert model.headerData(0, Qt.Orientation.Horizontal, Qt.ItemDataRole.ToolTipRole) is None
    assert not model.setData(QModelIndex(), "x")
    assert not model.setData(model.index(0, URL_COLUMN), "x", Qt.ItemDataRole.DisplayRole)


def test_the_same_licenses_coming_back_keep_the_rows_and_a_change_replaces_them(document: Mock, qtbot: QtBot) -> None:
    """The document's licenses come back as this model wrote them, which must not lose a row being added.

    **Test steps:**

    * add a row, then hand the model the licenses it holds
    * verify no reset and the row is still there
    * hand it others and verify a reset to them
    """
    model = make(document, FIRST)
    model.insert(0)

    with qtbot.assertNotEmitted(model.modelReset):
        model.set_entries([FIRST])
    assert model.count == 2
    with qtbot.waitSignal(model.modelReset):
        model.set_entries([SECOND])
    assert cells(model) == [[SECOND.license, ""]]


def test_a_dragged_row_carries_its_number(document: Mock) -> None:
    """**Test steps:**

    * ask for the drag data of a row's cells, and of none
    * verify the row's number under the model's one type, and nothing for none
    """
    model = make(document, FIRST, SECOND)

    mime = model.mimeData([model.index(1, LICENSE_COLUMN), model.index(1, URL_COLUMN)])

    assert model.mimeTypes() == [LICENSE_MIME_TYPE]
    assert bytes(mime.data(LICENSE_MIME_TYPE).data()) == b"1"
    assert not model.mimeData([]).hasFormat(LICENSE_MIME_TYPE)


# endregion

# region reading only


def test_while_reading_nothing_can_be_edited_added_deleted_or_moved(document: Mock, qtbot: QtBot) -> None:
    """**Test steps:**

    * over a model that only reads, try every edit
    * verify the cells take no edit and no drag, nothing changed, and the document was not touched
    """
    model = make(document, FIRST, SECOND, editable=False)

    assert model.flags(model.index(0, LICENSE_COLUMN)) == Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
    assert model.insert(0) == 0
    model.delete(0)
    assert model.move_down(0) == 0
    assert not model.setData(model.index(0, URL_COLUMN), "x")
    assert cells(model) == [[FIRST.license, URL], [SECOND.license, ""]]
    assert not document.mock_calls
    with qtbot.assertNotEmitted(model.layoutChanged):
        model.set_editable(False)


def test_editing_lets_every_cell_be_edited_and_dragged(document: Mock, qtbot: QtBot) -> None:
    """**Test steps:**

    * make a model edit, and verify it is laid out again
    * verify each cell is editable and draggable
    """
    model = make(document, FIRST, editable=False)

    with qtbot.waitSignal(model.layoutChanged):
        model.set_editable(True)

    assert model.editable
    for column in range(2):
        flags = model.flags(model.index(0, column))
        assert flags & Qt.ItemFlag.ItemIsEditable and flags & Qt.ItemFlag.ItemIsDragEnabled


# endregion

# region adding


def test_a_row_added_has_no_id_and_is_not_a_license_yet(document: Mock) -> None:
    """**Test steps:**

    * add a row after the first, and one at the end
    * verify where they landed, and that they are not licenses
    """
    model = make(document, FIRST, SECOND)

    assert model.insert(0) == 1
    assert model.insert(-1) == 3

    assert cells(model)[1] == ["", ""]
    assert model.entries == [FIRST, SECOND]


def test_rows_with_no_id_are_dropped_when_asked_and_the_licenses_stay(document: Mock) -> None:
    """**Test steps:**

    * add a row between two licenses and one at the end, and drop the unnamed
    * verify the two licenses are left, and the document was not given anything
    """
    model = make(document, FIRST, SECOND)
    model.insert(0)
    model.insert(-1)

    model.drop_unnamed()

    assert cells(model) == [[FIRST.license, URL], [SECOND.license, ""]]
    assert document.licenses is None


def test_a_custom_id_on_a_row_added_keeps_the_url_typed_first(document: Mock, qtbot: QtBot) -> None:
    """**Test steps:**

    * add a row between two licenses, type its URL, then a custom id
    * verify the document was not given the licenses until the id, then holds the three, the new one in its place with
      its URL, and no text was asked for
    """
    model = make(document, FIRST, SECOND)
    model.insert(0)

    assert model.setData(model.index(1, URL_COLUMN), MINE_URL)
    assert document.licenses is None
    with qtbot.assertNotEmitted(model.preset_chosen):
        assert model.setData(model.index(1, LICENSE_COLUMN), f" {MINE} ")

    assert document.licenses == [FIRST, AssetLicense(MINE, MINE_URL), SECOND]


def test_a_preset_on_a_row_added_brings_its_url_and_asks_for_its_text(document: Mock, qtbot: QtBot) -> None:
    """**Test steps:**

    * add a row, type a URL, and pick a preset
    * verify the row holds the preset's URL, not the one typed, the document holds it, and its text was asked for
    """
    model = make(document, FIRST)
    model.insert(-1)
    model.setData(model.index(1, URL_COLUMN), MINE_URL)

    with qtbot.waitSignal(model.preset_chosen) as chosen:
        assert model.setData(model.index(1, LICENSE_COLUMN), THIRD.license)

    url = PRESET_URLS[THIRD.license]
    assert chosen.args == [THIRD.license, url]
    assert cells(model)[1] == [THIRD.license, url]
    assert document.licenses == [FIRST, AssetLicense(THIRD.license, url)]


def test_a_preset_with_no_terms_asks_for_no_text(document: Mock, qtbot: QtBot) -> None:
    """**Test steps:**

    * add a row and pick the Marketplace license
    * verify it has no URL and no text was asked for
    """
    model = make(document)
    model.insert(-1)

    with qtbot.assertNotEmitted(model.preset_chosen):
        assert model.setData(model.index(0, LICENSE_COLUMN), "fab-ue-only")

    assert document.licenses == [AssetLicense("fab-ue-only")]


@mark.parametrize("typed", ["", "  ", SECOND.license, FIRST.license])
def test_an_id_that_is_empty_or_taken_is_refused(document: Mock, typed: str) -> None:
    """Licenses are unique by id, and one cannot be without one.

    **Test steps:**

    * type an empty, a blank, a taken and the same id into the first row
    * verify each is refused and the document untouched
    """
    model = make(document, FIRST, SECOND)

    assert not model.setData(model.index(0, LICENSE_COLUMN), typed)

    assert model.license_at(0) == FIRST.license
    document.replace_license.assert_not_called()


# endregion

# region another id


@mark.parametrize(
    ("before", "picked", "url", "keep_text"),
    [
        (FIRST, THIRD.license, PRESET_URLS[THIRD.license], False),
        (FIRST, MINE, "", False),
        (AssetLicense(MINE, MINE_URL), "theirs", MINE_URL, True),
        (AssetLicense(MINE, MINE_URL), THIRD.license, PRESET_URLS[THIRD.license], False),
    ],
    ids=["preset-to-preset", "preset-to-custom", "custom-to-custom", "custom-to-preset"],
)
def test_another_id_replaces_the_license_keeping_only_what_was_typed(
    document: Mock, before: AssetLicense, picked: str, url: str, keep_text: bool
) -> None:
    """A preset's URL and text are the preset's: another id drops them. A custom license's are the user's: another
    custom id keeps them, a preset replaces them with its own.

    **Test steps:**

    * give a license another id
    * verify the row's URL, and that the document replaced the license in place, keeping its text or not
    """
    model = make(document, before)

    assert model.setData(model.index(0, LICENSE_COLUMN), picked)

    assert cells(model) == [[picked, url]]
    document.replace_license.assert_called_once_with(
        before.license, AssetLicense(picked, url or None), keep_text=keep_text
    )


def test_a_url_typed_is_the_licenses_and_the_same_one_changes_nothing(document: Mock) -> None:
    """**Test steps:**

    * type a URL into a license with none, then the same again, then empty the first's
    * verify the document holds each change, and the repeat was refused
    """
    model = make(document, FIRST, SECOND)

    assert model.setData(model.index(1, URL_COLUMN), "https://example.com/ref")
    assert document.licenses == [FIRST, AssetLicense(SECOND.license, "https://example.com/ref")]
    assert not model.setData(model.index(1, URL_COLUMN), "https://example.com/ref")
    assert model.setData(model.index(0, URL_COLUMN), "")

    assert document.licenses == [AssetLicense(FIRST.license), AssetLicense(SECOND.license, "https://example.com/ref")]


# endregion

# region deleting and moving


def test_deleting_a_license_takes_it_off_the_record_and_a_row_with_no_id_goes_alone(document: Mock) -> None:
    """**Test steps:**

    * add a row, delete it, then delete the first license and a row there is not
    * verify the document was asked to remove the first license alone, and the second is left
    """
    model = make(document, FIRST, SECOND)
    model.insert(-1)

    model.delete(2)
    model.delete(0)
    model.delete(-1)
    model.delete(5)

    document.remove_license.assert_called_once_with(FIRST.license)
    assert cells(model) == [[SECOND.license, ""]]


def test_duplicating_and_resetting_do_nothing(document: Mock) -> None:
    """A copy would hold a taken id, and there are no default licenses.

    **Test steps:**

    * duplicate the first row and reset
    * verify the rows are as they were
    """
    model = make(document, FIRST)

    assert model.duplicate(0) == 0
    model.reset()

    assert model.entries == [FIRST]


def test_each_move_gives_the_document_the_new_order(document: Mock) -> None:
    """**Test steps:**

    * move the first license down, the last up, the second to the top and the first to the bottom
    * verify where each ended up and the order the document was given after each
    """
    model = make(document, FIRST, SECOND, THIRD)

    assert model.move_down(0) == 1
    assert document.licenses == [SECOND, FIRST, THIRD]
    assert model.move_up(2) == 1
    assert document.licenses == [SECOND, THIRD, FIRST]
    assert model.move_to_top(2) == 0
    assert document.licenses == [FIRST, SECOND, THIRD]
    assert model.move_to_bottom(0) == 2
    assert document.licenses == [SECOND, THIRD, FIRST]


@mark.parametrize(("row", "destination"), [(0, 0), (-1, 0), (0, 3), (0, -1)])
def test_a_move_out_of_range_or_to_its_own_place_changes_nothing(document: Mock, row: int, destination: int) -> None:
    """**Test steps:**

    * move a row to its own place, a row there is not, and a row out of range
    * verify nothing moved and the document was not given the licenses
    """
    model = make(document, FIRST, SECOND, THIRD)

    assert model.move(row, destination) == row

    assert model.entries == [FIRST, SECOND, THIRD]
    assert document.licenses is None


def test_the_row_primitives_refuse_what_is_not_a_row_of_theirs(document: Mock) -> None:
    """**Test steps:**

    * insert, remove and move rows under a parent, out of range, and onto themselves
    * verify each is refused
    """
    model = make(document, FIRST, SECOND)
    child = model.index(0, 0)

    assert not model.insertRows(0, 1, child)
    assert not model.insertRows(5, 1)
    assert not model.removeRows(0, 1, child)
    assert not model.removeRows(1, 2)
    assert not model.moveRows(child, 0, 1, QModelIndex(), 1)
    assert not model.moveRows(QModelIndex(), 0, 1, QModelIndex(), 1)
    assert model.entries == [FIRST, SECOND]


# endregion
