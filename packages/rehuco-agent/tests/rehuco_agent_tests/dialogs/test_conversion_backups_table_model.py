"""Tests for the `Conversion Backups…` dialog's table model and its filter proxy (#193).

The inventory builder reads the same here as in `test_conversion_backups_dialog` -- one describes the
rows the model renders, the other the rows the dialog acts on -- and is kept as a separate copy per
module, this codebase's test-fixture convention.
"""

# pylint: disable=duplicate-code

from pathlib import Path
from typing import Final

from PySide6.QtCore import QModelIndex, Qt
from pytest import fixture
from rehuco_agent.dialogs.conversion_backups_table_model import (
    BACKUPS_COLUMN,
    CHECKED_COLUMN,
    COLUMN_TITLES,
    CONVERTED_COLUMN,
    EDITED_SINCE_FLAG,
    FLAGS_COLUMN,
    NO_FLAGS,
    NO_OUTCOME,
    NOT_REVERTIBLE_FLAG,
    OUTCOME_COLUMN,
    REFUSED_OUTCOME,
    RESOURCE_COLUMN,
    TIE_BREAK_FLAG,
    ConversionBackupsFilterProxyModel,
    ConversionBackupsTableModel,
    describe_backups,
    format_size,
)
from rehuco_core import ConversionBackups

ROOT: Final = Path("/fake/library")
SCULPTING: Final = ROOT / "Sculpting" / "info.rehu"
ZBRUSH: Final = ROOT / "ZBrush" / "info.rehu"
PAINTING: Final = ROOT / "Painting" / "info.rehu"

CONVERTED_STAMP: Final = "2023-11-14T22:13:20Z"


# region Sample inventories


# a builder's parameters *are* the shapes worth testing; collapsing them into a config object would put
# a second vocabulary between each test and the inventory it is about
def make_backups(  # pylint: disable=too-many-arguments
    rehu_path: Path,
    *,
    files: int = 2,
    total_bytes: int = 14_000_000,
    installed: int = 2,
    edited_since: bool = False,
    legacy: bool = True,
    obstructed: bool = False,
    converted: str = CONVERTED_STAMP,
) -> ConversionBackups:
    """One resource's inventory, built the way :func:`~rehuco_core.conversion_backups` would report it.

    :param rehu_path: the converted resource.
    :param files: how many image backups it retains.
    :param total_bytes: what they occupy.
    :param installed: how many ``<stem>NN`` screenshots the conversion installed -- fewer than ``files``
        is a tie-break.
    :param edited_since: whether the ``.rehu`` has been saved again since the conversion.
    :param legacy: whether a backed-up ``.tc`` is here at all.
    :param obstructed: whether a restore target is occupied.
    :param converted: the ``.rehu``'s ``created`` stamp.
    :returns: the inventory.
    """
    directory = rehu_path.parent
    backups = tuple(directory / f"sample-{index:02}.jpg.orig" for index in range(files))
    if legacy:
        backups = (*backups, directory / "info.tc.orig")
    written = (rehu_path, *(directory / f"info{index:02}.jpg" for index in range(installed)))
    return ConversionBackups(
        rehu_path=rehu_path,
        backups=backups,
        total_bytes=total_bytes,
        written=written,
        obstructions=(directory / "sample-00.jpg",) if obstructed else (),
        legacy_restored=(directory / "info.tc") if legacy else None,
        edited_since=edited_since,
        converted=converted,
    )


@fixture(name="model")
def fixture_model() -> ConversionBackupsTableModel:
    """A model over three resources: a tie-break, an edited-since, and an unrevertible one."""
    model = ConversionBackupsTableModel()
    model.set_backups(
        ROOT,
        [
            make_backups(SCULPTING, files=3, installed=2),
            make_backups(ZBRUSH, edited_since=True, total_bytes=1000),
            make_backups(PAINTING, legacy=False, total_bytes=2000),
        ],
    )
    return model


def cell(model: ConversionBackupsTableModel, row: int, column: int) -> str:
    """One cell's display text."""
    return str(model.data(model.index(row, column), Qt.ItemDataRole.DisplayRole))


# endregion


# region What a row says


def test_every_row_starts_checked(model: ConversionBackupsTableModel) -> None:
    """Nothing here is dangerous to *select* -- the danger is in which action is then run, and both of
    those confirm -- so the common ending of the import flow is one filter and one click.

    **Test steps:**

    * build a model over three resources
    * verify every row is checked
    """
    assert len(model.checked_rows()) == 3


def test_a_row_names_the_resource_relative_to_the_scanned_root(model: ConversionBackupsTableModel) -> None:
    """A catalog's absolute paths are all prefix; what tells two rows apart is what comes after the root.

    **Test steps:**

    * read the resource column of each row
    * verify each is the path relative to the scanned root
    """
    assert cell(model, 0, RESOURCE_COLUMN) == "Sculpting/info.rehu"
    assert cell(model, 1, RESOURCE_COLUMN) == "ZBrush/info.rehu"


def test_a_row_summarizes_its_backups_rather_than_listing_them(model: ConversionBackupsTableModel) -> None:
    """Grouped per resource, not per file: six `.orig` files are one decision, and six rows would put
    five of them in front of a reader who cannot act on any one alone.

    **Test steps:**

    * read the backups column of the first row
    * verify it counts the files and names the bytes
    """
    assert cell(model, 0, BACKUPS_COLUMN) == "4 files, 14.0 MB"


def test_a_single_backup_is_not_pluralized() -> None:
    """*1 files* is the kind of thing a reader notices instead of the number.

    **Test steps:**

    * describe an inventory holding one backup
    * verify the singular
    """
    backups = make_backups(SCULPTING, files=0, total_bytes=500)

    assert describe_backups(backups) == "1 file, 500 Bytes"


def test_a_row_dates_the_conversion(model: ConversionBackupsTableModel) -> None:
    """A conversion mints ``created``, so it dates the conversion rather than the resource.

    **Test steps:**

    * read the converted column
    * verify it is the ``.rehu``'s own stamp
    """
    assert cell(model, 0, CONVERTED_COLUMN) == CONVERTED_STAMP


def test_a_rehu_that_would_not_read_shows_no_conversion_date() -> None:
    """The inventory reports an empty stamp for an unreadable record, and a row must not render that as
    a blank cell that reads like a missing value.

    **Test steps:**

    * build a model over a resource whose stamp is empty
    * verify the cell shows the same placeholder an absent outcome does
    """
    model = ConversionBackupsTableModel()
    model.set_backups(ROOT, [make_backups(SCULPTING, converted="")])

    assert cell(model, 0, CONVERTED_COLUMN) == NO_OUTCOME


# endregion


# region Flags


def test_a_tie_break_is_flagged(model: ConversionBackupsTableModel) -> None:
    """A conversion that backed up three screenshots and installed two dropped one -- the ~1--2 % #193
    exists to review.

    **Test steps:**

    * read the flags of the tie-break row
    * verify it says so and says nothing else
    """
    assert cell(model, 0, FLAGS_COLUMN) == TIE_BREAK_FLAG


def test_an_edited_resource_is_flagged(model: ConversionBackupsTableModel) -> None:
    """Reverting this one costs real work, which is a reason to look before selecting it.

    **Test steps:**

    * read the flags of the edited row
    * verify it says so
    """
    assert cell(model, 1, FLAGS_COLUMN) == EDITED_SINCE_FLAG


def test_a_resource_with_no_backed_up_tc_is_flagged_unrevertible(model: ConversionBackupsTableModel) -> None:
    """Without a backed-up `.tc` this is not a conversion to undo, so only discarding is left -- and the
    row has to say that before anyone selects it for a revert.

    **Test steps:**

    * read the flags of the row whose backups hold no `.tc`
    * verify it says so
    """
    assert cell(model, 2, FLAGS_COLUMN) == NOT_REVERTIBLE_FLAG


def test_a_resource_with_nothing_to_report_shows_a_placeholder() -> None:
    """An empty flags cell would read as a rendering gap rather than as *nothing to say*.

    **Test steps:**

    * build a model over a clean, revertible, unedited resource
    * verify the flags cell shows the em dash
    """
    model = ConversionBackupsTableModel()
    model.set_backups(ROOT, [make_backups(SCULPTING)])

    assert cell(model, 0, FLAGS_COLUMN) == NO_FLAGS


def test_every_reason_to_look_is_listed_at_once() -> None:
    """A resource can be several kinds of interesting, and dropping all but the first would hide the
    one that mattered.

    **Test steps:**

    * build a model over a resource that is a tie-break, edited, and unrevertible
    * verify all three flags appear
    """
    model = ConversionBackupsTableModel()
    model.set_backups(ROOT, [make_backups(SCULPTING, files=3, installed=1, edited_since=True, legacy=False)])

    assert cell(model, 0, FLAGS_COLUMN) == f"{TIE_BREAK_FLAG}, {EDITED_SINCE_FLAG}, {NOT_REVERTIBLE_FLAG}"


def test_an_occupied_restore_target_is_unrevertible() -> None:
    """A legacy name the user has since put back by hand refuses the whole revert, exactly as a missing
    backup does -- so it earns the same flag rather than passing for revertible.

    **Test steps:**

    * build a model over a resource whose restore target is occupied
    * verify it is flagged unrevertible
    """
    model = ConversionBackupsTableModel()
    model.set_backups(ROOT, [make_backups(SCULPTING, obstructed=True)])

    assert cell(model, 0, FLAGS_COLUMN) == NOT_REVERTIBLE_FLAG


# endregion


# region Selection


def test_a_checkbox_toggles_one_row(model: ConversionBackupsTableModel) -> None:
    """The per-row control the view drives.

    **Test steps:**

    * uncheck the first row through the model
    * verify only that row left the selection
    """
    model.setData(model.index(0, CHECKED_COLUMN), Qt.CheckState.Unchecked.value, Qt.ItemDataRole.CheckStateRole)

    assert [row.path for row in model.checked_rows()] == [ZBRUSH, PAINTING]


def test_setting_checks_in_bulk_changes_exactly_the_named_rows(model: ConversionBackupsTableModel) -> None:
    """*Select all shown* hands in the rows the filter lets through, so a row the filter hides must be
    left exactly as it was.

    **Test steps:**

    * uncheck two named rows in bulk
    * verify the third is untouched
    """
    model.set_checked([SCULPTING, ZBRUSH], False)

    assert [row.path for row in model.checked_rows()] == [PAINTING]


def test_setting_checks_over_an_unknown_path_changes_nothing(model: ConversionBackupsTableModel) -> None:
    """A path from a scan this model has since replaced has nowhere honest to land.

    **Test steps:**

    * set checks over a path the model has no row for
    * verify every row is still checked
    """
    model.set_checked([ROOT / "Gone" / "info.rehu"], False)

    assert len(model.checked_rows()) == 3


# endregion


# region Outcomes


def test_a_row_shows_nothing_before_an_action_has_run(model: ConversionBackupsTableModel) -> None:
    """An empty outcome cell would read as a rendering gap rather than as *nothing has happened yet*.

    **Test steps:**

    * read the outcome column of a fresh row
    * verify the placeholder
    """
    assert cell(model, 0, OUTCOME_COLUMN) == NO_OUTCOME


def test_a_finished_action_is_recorded_on_its_row(model: ConversionBackupsTableModel) -> None:
    """What became of each resource, so a reader can tell a run that happened from one that did not.

    **Test steps:**

    * record a finished discard
    * verify the row says so
    """
    model.set_row_outcome(SCULPTING, "discarded")

    assert cell(model, 0, OUTCOME_COLUMN) == "discarded"


def test_a_refusal_carries_its_reason(model: ConversionBackupsTableModel) -> None:
    """*A refused revert surfaces the reason and changes nothing* -- and the reason belongs on the row
    it is about, not in a dialog the reader has already dismissed.

    **Test steps:**

    * record a refusal with a reason
    * verify the cell reads both
    """
    model.set_row_outcome(PAINTING, REFUSED_OUTCOME, "no backed-up .tc file")

    assert cell(model, 2, OUTCOME_COLUMN) == f"{REFUSED_OUTCOME}: no backed-up .tc file"


def test_an_outcome_for_a_path_this_model_has_no_row_for_is_dropped(model: ConversionBackupsTableModel) -> None:
    """A job enqueued before a rescan reports into a table that no longer describes it.

    **Test steps:**

    * record an outcome for an unknown path
    * verify no row changed
    """
    model.set_row_outcome(ROOT / "Gone" / "info.rehu", "discarded")

    assert all(row.outcome is None for row in model.rows())


# endregion


# region Filtering


def test_filtering_by_a_flag_reaches_the_review_pass(model: ConversionBackupsTableModel) -> None:
    """Typing the flag's own word is how the review #192 skipped is actually done, which is why the
    Flags column is matched rather than sitting behind a separate control.

    **Test steps:**

    * filter by the tie-break flag
    * verify only the tie-break row is shown
    """
    proxy = ConversionBackupsFilterProxyModel()
    proxy.setSourceModel(model)

    proxy.set_filter_text(TIE_BREAK_FLAG)

    assert proxy.rowCount() == 1
    assert proxy.data(proxy.index(0, RESOURCE_COLUMN), Qt.ItemDataRole.DisplayRole) == "Sculpting/info.rehu"


def test_filtering_matches_the_resource_path_too(model: ConversionBackupsTableModel) -> None:
    """The other way a reader narrows a catalog: by where the resource sits.

    **Test steps:**

    * filter by part of one resource's path, in the wrong case
    * verify only that row is shown
    """
    proxy = ConversionBackupsFilterProxyModel()
    proxy.setSourceModel(model)

    proxy.set_filter_text("zBrUsH")

    assert proxy.rowCount() == 1


def test_an_empty_filter_shows_everything(model: ConversionBackupsTableModel) -> None:
    """Clearing the filter has to put the whole scan back.

    **Test steps:**

    * filter, then clear
    * verify every row is shown again
    """
    proxy = ConversionBackupsFilterProxyModel()
    proxy.setSourceModel(model)
    proxy.set_filter_text(TIE_BREAK_FLAG)

    proxy.set_filter_text("")

    assert proxy.rowCount() == 3


def test_the_checkbox_column_is_not_matched(model: ConversionBackupsTableModel) -> None:
    """The checkbox column has no display text, so a filter must not accept every row through it.

    **Test steps:**

    * filter by a string no text column holds
    * verify nothing is shown
    """
    proxy = ConversionBackupsFilterProxyModel()
    proxy.setSourceModel(model)

    proxy.set_filter_text("no-column-says-this")

    assert proxy.rowCount() == 0


# endregion


# region Qt model interface


def test_only_the_checkbox_column_is_user_checkable(model: ConversionBackupsTableModel) -> None:
    """Every other cell is a readout, and offering a check on one would be a control that does nothing.

    **Test steps:**

    * read the flags of a checkbox cell and a text cell
    * verify only the first is checkable
    """
    checkable = Qt.ItemFlag.ItemIsUserCheckable

    assert model.flags(model.index(0, CHECKED_COLUMN)) & checkable
    assert not model.flags(model.index(0, RESOURCE_COLUMN)) & checkable
    assert not model.flags(QModelIndex()) & checkable


def test_the_checkbox_column_answers_the_check_state_role(model: ConversionBackupsTableModel) -> None:
    """What the view actually paints in column zero.

    **Test steps:**

    * uncheck one row, then read the check-state role of both
    * verify each answers its own state
    """
    model.set_checked([ZBRUSH], False)
    checked = model.data(model.index(0, CHECKED_COLUMN), Qt.ItemDataRole.CheckStateRole)
    unchecked = model.data(model.index(1, CHECKED_COLUMN), Qt.ItemDataRole.CheckStateRole)

    assert checked == Qt.CheckState.Checked
    assert unchecked == Qt.CheckState.Unchecked


def test_the_model_answers_nothing_it_was_not_asked_for(model: ConversionBackupsTableModel) -> None:
    """An invalid index, a role this table has no answer for, and a column past the last one are all
    *no answer* rather than a guess -- a guess would render as data the resource does not carry.

    **Test steps:**

    * ask for an invalid index, a decoration role and a column beyond the table
    * verify each answers ``None``
    """
    assert model.data(QModelIndex()) is None
    assert model.data(model.index(0, RESOURCE_COLUMN), Qt.ItemDataRole.DecorationRole) is None
    # createIndex, not index(): the latter validates the column away, and what is being proved here is
    # that a column this table does not draw answers nothing rather than the wrong cell's text
    assert model.data(model.createIndex(0, len(COLUMN_TITLES))) is None


def test_only_a_check_on_the_checkbox_column_is_accepted(model: ConversionBackupsTableModel) -> None:
    """Every other write would be an edit to a readout, so the model refuses rather than storing it.

    **Test steps:**

    * write to an invalid index, to a text column, and with the wrong role
    * verify each is refused and no row changed
    """
    refused = [
        model.setData(QModelIndex(), Qt.CheckState.Unchecked.value, Qt.ItemDataRole.CheckStateRole),
        model.setData(model.index(0, RESOURCE_COLUMN), Qt.CheckState.Unchecked.value, Qt.ItemDataRole.CheckStateRole),
        model.setData(model.index(0, CHECKED_COLUMN), "anything", Qt.ItemDataRole.EditRole),
    ]

    assert not any(refused)
    assert len(model.checked_rows()) == 3


def test_a_resource_outside_the_scanned_root_shows_its_full_path() -> None:
    """A relative path only exists relative to something; a resource the root does not contain has to be
    named in full rather than by a path that would resolve somewhere else.

    **Test steps:**

    * build a model whose root does not contain its resource
    * verify the cell shows the absolute path
    """
    model = ConversionBackupsTableModel()
    model.set_backups(ROOT / "Elsewhere", [make_backups(SCULPTING)])

    assert cell(model, 0, RESOURCE_COLUMN) == str(SCULPTING)


def test_the_model_reports_no_children(model: ConversionBackupsTableModel) -> None:
    """A flat table: a valid parent index has no rows or columns under it.

    **Test steps:**

    * ask for the counts under a valid index
    * verify both are zero
    """
    parent = model.index(0, 0)

    assert model.rowCount(parent) == 0
    assert model.columnCount(parent) == 0


def test_sizes_read_as_prose_rather_than_raw_bytes() -> None:
    """The header and the rows are sentences about reclaiming space, not a dense grid of fields.

    **Test steps:**

    * format a few totals
    * verify the long-form rendering
    """
    assert format_size(0) == "0 Bytes"
    assert format_size(14_000_000) == "14.0 MB"


# endregion
