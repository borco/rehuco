"""Tests for the dialog that asks which licenses' saved texts to replace (#688, [[assets#licenses]])."""

import datetime
from pathlib import Path
from typing import Final

from PySide6.QtCore import Qt
from pytest import fixture
from pytestqt.qtbot import QtBot
from rehuco_agent.dialogs.license_refresh_dialog import (
    KEEP_TEXT,
    REPLACE_TEXT,
    TOOLTIP_RECORDS,
    LicenseRefreshDialog,
)
from rehuco_agent.scraping.license_refresh_job import LicenseDifference, SavedLicense
from rehuco_core import LicenseTerms

STORE: Final = LicenseTerms("Standard License", "https://example.com/eula", datetime.date(2026, 11, 25), "New")
CC: Final = LicenseTerms("Creative Commons BY 4.0", "https://example.com/cc", datetime.date(2026, 11, 24), "CC")


def saved(name: str, day: datetime.date) -> SavedLicense:
    """A record holding an older text of a license.

    :param name: the record's folder.
    :param day: the day it read it.
    :returns: the record.
    """
    return SavedLicense(Path("/assets") / name / "info.rehu", LicenseTerms("Old", STORE.url, day, "Old"))


ONE_DAY: Final = datetime.date(2026, 3, 1)
OTHER_DAY: Final = datetime.date(2026, 9, 12)
STANDARD: Final = LicenseDifference(
    STORE.url or "", STORE, (saved("a", ONE_DAY), saved("b", OTHER_DAY), saved("c", ONE_DAY))
)
CREATIVE: Final = LicenseDifference(CC.url or "", CC, (saved("d", ONE_DAY),))


@fixture(name="dialog")
def fixture_dialog(qtbot: QtBot) -> LicenseRefreshDialog:
    """A dialog over two licenses.

    :param qtbot: pytest-qt fixture.
    :returns: the dialog.
    """
    dialog = LicenseRefreshDialog([STANDARD, CREATIVE])
    qtbot.addWidget(dialog)
    return dialog


def rows_of(dialog: LicenseRefreshDialog):  # type: ignore[no-untyped-def]
    """The list of licenses.

    :param dialog: the dialog.
    :returns: its list widget.
    """
    return dialog._LicenseRefreshDialog__ui.licenses_list  # type: ignore[attr-defined]  # pylint: disable=protected-access


def test_a_license_is_a_row_naming_it_how_many_records_hold_another_text_and_both_days(
    dialog: LicenseRefreshDialog,
) -> None:
    """**Test steps:**

    * open the dialog over two licenses
    * verify a row each, the first saying the license, its address, three records, the span of days they read it and
      the day the store's was read, the second saying one record and its one day
    """
    texts = [rows_of(dialog).item(row).text() for row in range(rows_of(dialog).count())]

    assert texts == [
        "Standard License - https://example.com/eula\n"
        "3 records hold another text, read 2026-03-01 to 2026-09-12. The store's was read 2026-11-25.",
        "Creative Commons BY 4.0 - https://example.com/cc\n"
        "1 record holds another text, read 2026-03-01. The store's was read 2026-11-24.",
    ]


def test_nothing_is_checked_until_the_user_checks_it_and_replacing_waits_for_a_check(
    dialog: LicenseRefreshDialog,
) -> None:
    """A saved text is replaced only on a yes.

    **Test steps:**

    * verify nothing is checked, the buttons say what they do, and replacing is disabled
    * check the second license and verify replacing is offered and only that license is chosen
    * check the first and uncheck the second and verify the choice follows, in the order listed
    """
    assert dialog.chosen == ()
    assert dialog.replace_button.text() == REPLACE_TEXT
    assert not dialog.replace_button.isEnabled()

    rows_of(dialog).item(1).setCheckState(Qt.CheckState.Checked)
    assert dialog.replace_button.isEnabled()
    assert dialog.chosen == (CREATIVE,)

    rows_of(dialog).item(0).setCheckState(Qt.CheckState.Checked)
    rows_of(dialog).item(1).setCheckState(Qt.CheckState.Unchecked)
    assert dialog.chosen == (STANDARD,)


def test_keep_all_is_cancel(dialog: LicenseRefreshDialog) -> None:
    """**Test steps:**

    * check a license and press the cancel button
    * verify it says *Keep All* and the dialog was rejected
    """
    rows_of(dialog).item(0).setCheckState(Qt.CheckState.Checked)
    keep = dialog._LicenseRefreshDialog__ui.button_box.buttons()[1]  # type: ignore[attr-defined]  # pylint: disable=protected-access

    keep.click()

    assert dialog.result() == LicenseRefreshDialog.DialogCode.Rejected
    assert KEEP_TEXT in {button.text() for button in dialog._LicenseRefreshDialog__ui.button_box.buttons()}  # type: ignore[attr-defined]  # pylint: disable=protected-access


def test_a_rows_tooltip_names_the_records_and_says_how_many_more_there_are(qtbot: QtBot) -> None:
    """**Test steps:**

    * open the dialog over a license held by more records than a tooltip names
    * verify the tooltip lists that many and says how many more
    * open one over a few records and verify the tooltip lists every one
    """
    many = LicenseDifference(
        STORE.url or "", STORE, tuple(saved(f"r{number}", ONE_DAY) for number in range(TOOLTIP_RECORDS + 5))
    )
    big = LicenseRefreshDialog([many])
    few = LicenseRefreshDialog([CREATIVE])
    qtbot.addWidget(big)
    qtbot.addWidget(few)

    lines = rows_of(big).item(0).toolTip().splitlines()

    assert len(lines) == TOOLTIP_RECORDS + 1
    assert lines[-1] == "... and 5 more"
    # astroid reads the dataclass's holders as a signal
    assert rows_of(few).item(0).toolTip() == str(CREATIVE.holders[0].record)  # pylint: disable=no-member
