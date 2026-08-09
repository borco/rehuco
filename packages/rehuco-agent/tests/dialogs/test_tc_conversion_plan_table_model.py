"""Tests for TcConversionPlanTableModel: the `Import Legacy Catalog…` wizard's plan/result table
(#192)."""

from pathlib import Path
from typing import Any, Final

from PySide6.QtCore import QModelIndex, Qt
from rehuco_agent.dialogs.tc_conversion_plan_table_model import (
    CHECKED_COLUMN,
    FLAGS_COLUMN,
    OUTCOME_COLUMN,
    PATH_COLUMN,
    SCREENSHOTS_COLUMN,
    TARGET_COLUMN,
    TcConversionPlanFilterProxyModel,
    TcConversionPlanTableModel,
)
from rehuco_core import ScreenshotRename, StrandedManifestPlan, TcConversionPlan

ROOT: Final = Path("/fake/library")

FLAG_DEFAULTS: Final = {
    "tie_break": False,
    "rehu_exists": False,
    "stale_backup": False,
    "size_unparsed": False,
    "duration_present": False,
    "unmapped_keys": (),
    "suspect_mtime": False,
}


def plan(name: str, *, renames: tuple[ScreenshotRename, ...] = (), **flags: Any) -> TcConversionPlan:
    """Build one minimal plan record under a subdirectory of :data:`ROOT`.

    :param name: the resource's subdirectory name, holding ``info.tc``.
    :param renames: the screenshot rename plan.
    :param flags: overrides over :data:`FLAG_DEFAULTS`.
    :returns: the plan.
    """
    values = {**FLAG_DEFAULTS, **flags}
    return TcConversionPlan(
        tc_path=ROOT / name / "info.tc",
        rehu_path=ROOT / name / "info.rehu",
        data={},
        renames=renames,
        **values,
    )


CLEAN: Final = plan("a")
TIED: Final = plan(
    "b", tie_break=True, renames=(ScreenshotRename("info00.jpg", "cover.jpg", ("cover.jpg", "sample-00.png")),)
)
BLOCKED: Final = plan("c", rehu_exists=True)
STRANDED: Final = StrandedManifestPlan(rehu_path=ROOT / "d/info.rehu", manifest=ROOT / "d/info.sfv")
"""An already-converted resource still carrying the manifest its record was made from (#259)."""


def cell(model: TcConversionPlanTableModel, row: int, column: int, role: Qt.ItemDataRole) -> Any:
    """Read one cell.

    :param model: the model to read.
    :param row: the row to read.
    :param column: the column to read.
    :param role: the role to read it under.
    :returns: whatever the model answers.
    """
    return model.data(model.index(row, column), role)


# region What a row starts as


def test_a_clean_row_starts_checked_and_a_blocked_row_starts_unchecked() -> None:
    """A blocked row starts unchecked, which is the whole of #192's *no automatic overwrite* rule --
    checking it later is the explicit opt-in.

    **Test steps:**

    * build a model over a clean and a blocked plan
    * verify the checkbox state each starts at
    """
    model = TcConversionPlanTableModel()
    model.set_plans(ROOT, [CLEAN, BLOCKED])

    assert cell(model, 0, CHECKED_COLUMN, Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
    assert cell(model, 1, CHECKED_COLUMN, Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Unchecked


def test_checking_a_blocked_row_is_offered_the_same_as_any_other() -> None:
    """A blocked row's checkbox is not disabled -- checking it *is* the per-row opt-in, so refusing to
    let it be checked would remove the only way #192 offers one.

    **Test steps:**

    * build a model over a blocked plan
    * verify its checkbox is user-checkable and setting it sticks
    """
    model = TcConversionPlanTableModel()
    model.set_plans(ROOT, [BLOCKED])
    index = model.index(0, CHECKED_COLUMN)

    assert model.flags(index) & Qt.ItemFlag.ItemIsUserCheckable

    assert model.setData(index, Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)

    assert model.checked_rows()[0].plan is BLOCKED


def test_checked_rows_reflects_only_what_is_currently_checked() -> None:
    """Unchecking a started-checked row drops it from the selection.

    **Test steps:**

    * build a model over two clean plans
    * uncheck the first
    * verify only the second is in the checked set
    """
    model = TcConversionPlanTableModel()
    other = plan("d")
    model.set_plans(ROOT, [CLEAN, other])

    model.setData(model.index(0, CHECKED_COLUMN), Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)

    assert [row.plan for row in model.checked_rows()] == [other]


# endregion


# region What each column shows


def test_path_and_target_columns_show_relative_paths() -> None:
    """The path columns are shown relative to the scanned root, not the absolute filesystem path.

    **Test steps:**

    * build a model over one resource
    * verify the path and target cells
    """
    model = TcConversionPlanTableModel()
    model.set_plans(ROOT, [CLEAN])

    assert cell(model, 0, PATH_COLUMN, Qt.ItemDataRole.DisplayRole) == "a/info.tc"
    assert cell(model, 0, TARGET_COLUMN, Qt.ItemDataRole.DisplayRole) == "a/info.rehu"


def test_screenshots_column_names_a_tie_break_dropped_count() -> None:
    """A tie-break shows the winners installed and how many recognized files were dropped.

    **Test steps:**

    * build a model over a plan with one tied slot (two recognized files, one winner)
    * verify the summary text
    """
    model = TcConversionPlanTableModel()
    model.set_plans(ROOT, [TIED])

    assert cell(model, 0, SCREENSHOTS_COLUMN, Qt.ItemDataRole.DisplayRole) == "1 → info00, 1 dropped"


def test_screenshots_column_shows_none_for_no_recognized_screenshots() -> None:
    """A resource with nothing to rename says so plainly.

    **Test steps:**

    * build a model over a plan with an empty rename list
    * verify the summary text
    """
    model = TcConversionPlanTableModel()
    model.set_plans(ROOT, [CLEAN])

    assert cell(model, 0, SCREENSHOTS_COLUMN, Qt.ItemDataRole.DisplayRole) == "none"


def test_flags_column_lists_every_active_flag() -> None:
    """The flags column names every flag that fired, and an em dash when nothing did.

    **Test steps:**

    * build a model over a tied plan and a clean one
    * verify each flags cell
    """
    model = TcConversionPlanTableModel()
    model.set_plans(ROOT, [CLEAN, TIED])

    assert cell(model, 0, FLAGS_COLUMN, Qt.ItemDataRole.DisplayRole) == "—"
    assert cell(model, 1, FLAGS_COLUMN, Qt.ItemDataRole.DisplayRole) == "tie-break"


def test_outcome_column_is_blank_before_import_and_names_a_failure_after() -> None:
    """The outcome column has nothing to say before import runs, and names the message once one fails.

    **Test steps:**

    * build a model, read the outcome cell, then record a failure and read it again
    * verify both readings
    """
    model = TcConversionPlanTableModel()
    model.set_plans(ROOT, [CLEAN])

    assert cell(model, 0, OUTCOME_COLUMN, Qt.ItemDataRole.DisplayRole) == "—"

    model.set_row_outcome(CLEAN.tc_path, "failed", "target exists")

    assert cell(model, 0, OUTCOME_COLUMN, Qt.ItemDataRole.DisplayRole) == "failed: target exists"


def test_set_row_outcome_over_a_path_the_model_no_longer_has_is_a_no_op() -> None:
    """A stale report -- the plan was rebuilt since the job that reports this was enqueued -- lands
    nowhere rather than raising.

    **Test steps:**

    * build a model over one resource
    * report an outcome for a path it does not have
    * verify nothing raised and the model's one row is untouched
    """
    model = TcConversionPlanTableModel()
    model.set_plans(ROOT, [CLEAN])

    model.set_row_outcome(ROOT / "elsewhere" / "info.tc", "converted")

    assert cell(model, 0, OUTCOME_COLUMN, Qt.ItemDataRole.DisplayRole) == "—"


# endregion


# region Filtering


def test_the_filter_proxy_matches_flags_case_insensitively() -> None:
    """Filtering by a flag name shows only the rows carrying it, whatever case it was typed in.

    **Test steps:**

    * build a proxy over a clean and a tied plan, filtered on "tie-break" in an odd case
    * verify only the tied row survives
    """
    model = TcConversionPlanTableModel()
    model.set_plans(ROOT, [CLEAN, TIED])
    proxy = TcConversionPlanFilterProxyModel()
    proxy.setSourceModel(model)

    proxy.set_filter_text("TIE-Break")

    assert proxy.rowCount() == 1
    assert proxy.data(proxy.index(0, PATH_COLUMN)) == "b/info.tc"


def test_an_empty_filter_shows_every_row() -> None:
    """Clearing the filter text shows every row again.

    **Test steps:**

    * filter to one row, then clear the filter
    * verify every row is back
    """
    model = TcConversionPlanTableModel()
    model.set_plans(ROOT, [CLEAN, TIED])
    proxy = TcConversionPlanFilterProxyModel()
    proxy.setSourceModel(model)
    proxy.set_filter_text("tie-break")

    proxy.set_filter_text("")

    assert proxy.rowCount() == 2


def test_the_filter_matches_the_path_column_too() -> None:
    """A plain substring search reaches the path, not only the flags -- a reader can search by name.

    **Test steps:**

    * filter on part of one resource's directory name
    * verify only that row survives
    """
    model = TcConversionPlanTableModel()
    model.set_plans(ROOT, [CLEAN, TIED])
    proxy = TcConversionPlanFilterProxyModel()
    proxy.setSourceModel(model)

    proxy.set_filter_text("b/info")

    assert proxy.rowCount() == 1


# endregion


def test_rows_come_back_in_scan_order() -> None:
    """``rows()`` answers the plans in the order they were set, for a caller building its own view of
    them.

    **Test steps:**

    * set three plans
    * verify their order is preserved
    """
    model = TcConversionPlanTableModel()
    third = plan("e")
    model.set_plans(ROOT, [CLEAN, TIED, third])

    assert [row.plan for row in model.rows()] == [CLEAN, TIED, third]


def test_the_header_names_every_column_and_nothing_else() -> None:
    """The header names each column horizontally, and answers nothing for any other axis or role.

    **Test steps:**

    * read a horizontal header cell, a vertical one, and a horizontal one under an unrelated role
    * verify only the first answers
    """
    model = TcConversionPlanTableModel()

    assert model.headerData(PATH_COLUMN, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) == "Path"
    assert model.headerData(0, Qt.Orientation.Vertical, Qt.ItemDataRole.DisplayRole) is None
    assert model.headerData(PATH_COLUMN, Qt.Orientation.Horizontal, Qt.ItemDataRole.EditRole) is None


def test_only_the_checked_column_is_ever_checkable() -> None:
    """No other column offers a checkbox.

    **Test steps:**

    * build a model over one resource
    * verify the path column's flags carry no checkable bit
    """
    model = TcConversionPlanTableModel()
    model.set_plans(ROOT, [CLEAN])

    assert not model.flags(model.index(0, PATH_COLUMN)) & Qt.ItemFlag.ItemIsUserCheckable


def test_the_checked_column_has_no_display_text() -> None:
    """The checkbox column carries a check state, never display text of its own.

    **Test steps:**

    * read the checked cell under the display role
    * verify it answers nothing
    """
    model = TcConversionPlanTableModel()
    model.set_plans(ROOT, [CLEAN])

    assert cell(model, 0, CHECKED_COLUMN, Qt.ItemDataRole.DisplayRole) is None


def test_data_answers_nothing_for_a_role_no_column_supports() -> None:
    """A role that is neither display, tooltip nor (on the checked column) check-state has nothing to
    say.

    **Test steps:**

    * read the path cell under the edit role
    * verify it answers nothing
    """
    model = TcConversionPlanTableModel()
    model.set_plans(ROOT, [CLEAN])

    assert cell(model, 0, PATH_COLUMN, Qt.ItemDataRole.EditRole) is None


def test_a_path_outside_the_root_is_shown_in_full() -> None:
    """A resource that does not sit under the scanned root -- should the two ever diverge -- falls back
    to its absolute path rather than raising.

    **Test steps:**

    * build a model over a plan whose paths sit outside the scanned root
    * verify the path cell shows the absolute path
    """
    elsewhere = TcConversionPlan(
        tc_path=Path("/fake/elsewhere/info.tc"),
        rehu_path=Path("/fake/elsewhere/info.rehu"),
        data={},
        renames=(),
        **FLAG_DEFAULTS,
    )
    model = TcConversionPlanTableModel()
    model.set_plans(ROOT, [elsewhere])

    assert cell(model, 0, PATH_COLUMN, Qt.ItemDataRole.DisplayRole) == str(elsewhere.tc_path)


def test_setdata_on_the_wrong_column_or_role_changes_nothing() -> None:
    """Only the checked column, under the check-state role, is writable.

    **Test steps:**

    * try to set the path column, and the checked column under the display role
    * verify both are refused
    """
    model = TcConversionPlanTableModel()
    model.set_plans(ROOT, [CLEAN])

    assert not model.setData(model.index(0, PATH_COLUMN), "x", Qt.ItemDataRole.CheckStateRole)
    assert not model.setData(model.index(0, CHECKED_COLUMN), "x", Qt.ItemDataRole.DisplayRole)


def test_outcome_column_shows_a_non_failure_outcome_plainly() -> None:
    """A ``"converted"``/``"cancelled"``/``"skipped"`` outcome shows as itself, with no message to append.

    **Test steps:**

    * record a converted outcome
    * verify the cell shows it verbatim
    """
    model = TcConversionPlanTableModel()
    model.set_plans(ROOT, [CLEAN])

    model.set_row_outcome(CLEAN.tc_path, "converted")

    assert cell(model, 0, OUTCOME_COLUMN, Qt.ItemDataRole.DisplayRole) == "converted"


def test_an_invalid_index_answers_nothing() -> None:
    """The Qt contract for a root/invalid index: no data, and never the checkbox flag.

    **Test steps:**

    * build a model over one resource
    * read an invalid index
    * verify it answers ``None`` and is not offered as checkable
    """
    model = TcConversionPlanTableModel()
    model.set_plans(ROOT, [CLEAN])
    invalid = QModelIndex()

    assert model.data(invalid) is None
    assert not model.flags(invalid) & Qt.ItemFlag.ItemIsUserCheckable


# region Stranded-manifest rows (#259)


def test_a_stranded_row_comes_after_the_conversions_and_starts_checked() -> None:
    """Nothing blocks a remediation, and finding them is what the scan was run for.

    **Test steps:**

    * build a model over one conversion and one stranded manifest
    * verify the row order and that both are checked
    """
    model = TcConversionPlanTableModel()
    model.set_plans(ROOT, [CLEAN], [STRANDED])

    assert [row.path for row in model.rows()] == [CLEAN.tc_path, STRANDED.rehu_path]
    assert [row.checked for row in model.rows()] == [True, True]


def test_a_stranded_row_shows_the_record_it_merges_into_and_names_the_manifest() -> None:
    """The three cells that differ from a conversion's, and the only ones a reader needs here.

    **Test steps:**

    * build a model over one stranded manifest
    * verify the path, target, screenshots and flags cells
    """
    model = TcConversionPlanTableModel()
    model.set_plans(ROOT, [], [STRANDED])

    assert cell(model, 0, PATH_COLUMN, Qt.ItemDataRole.DisplayRole) == "d/info.rehu"
    assert cell(model, 0, TARGET_COLUMN, Qt.ItemDataRole.DisplayRole) == "d/info.checksum"
    assert cell(model, 0, SCREENSHOTS_COLUMN, Qt.ItemDataRole.DisplayRole) == "—"
    assert cell(model, 0, FLAGS_COLUMN, Qt.ItemDataRole.DisplayRole) == "stranded manifest: info.sfv"


def test_a_stranded_row_takes_its_outcome_under_the_rehu_path() -> None:
    """A finished job's ``source`` is the `.rehu`, which is what the row is keyed by.

    **Test steps:**

    * build a model over one conversion and one stranded manifest
    * record an outcome against the `.rehu`
    * verify it landed on the stranded row and nowhere else
    """
    model = TcConversionPlanTableModel()
    model.set_plans(ROOT, [CLEAN], [STRANDED])

    model.set_row_outcome(STRANDED.rehu_path, "retired")

    assert cell(model, 1, OUTCOME_COLUMN, Qt.ItemDataRole.DisplayRole) == "retired"
    assert cell(model, 0, OUTCOME_COLUMN, Qt.ItemDataRole.DisplayRole) == "—"


def test_the_filter_finds_stranded_rows_by_name() -> None:
    """Writing it as a flag rather than a row type is what puts it inside the filter's reach.

    **Test steps:**

    * filter a mixed model for ``stranded``
    * verify only the stranded row survives
    """
    model = TcConversionPlanTableModel()
    model.set_plans(ROOT, [CLEAN], [STRANDED])
    proxy = TcConversionPlanFilterProxyModel()
    proxy.setSourceModel(model)

    proxy.set_filter_text("stranded")

    assert proxy.rowCount() == 1
    assert proxy.data(proxy.index(0, PATH_COLUMN), Qt.ItemDataRole.DisplayRole) == "d/info.rehu"


# endregion
