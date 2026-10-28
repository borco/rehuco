"""Tests for ToolPathControl: the installs found and a custom path, as one settings value (#521)."""

from pathlib import Path
from typing import Any

from pytest import mark, param
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.settings.ui.tool_path_control import NOT_FOUND_TEXT, WARNING_PROPERTY, ToolPathControl, summarize
from rehuco_core import ToolCandidate, ToolStatus

NEWEST = ToolCandidate(Path("/gyan/bin"), "winget", ToolStatus.USABLE, (9, 0, 2))
OLDER = ToolCandidate(Path("/scoop/bin"), "scoop", ToolStatus.USABLE, (8, 1))
GIT = ToolCandidate(Path("/btbn/bin"), "winget", ToolStatus.UNTESTED, None, "The version could not be read.")
TOO_OLD = ToolCandidate(Path("/old/bin"), "PATH", ToolStatus.TOO_OLD, (3, 4), "Version 4.0 or newer is needed.")
FOUND = (NEWEST, OLDER, GIT, TOO_OLD)
"""What a search found, best first, as the discovery stores it."""


def control_ui(control: ToolPathControl) -> Any:
    """The control's generated UI object, for reaching its widgets.

    :param control: the control to reach into.
    :returns: the ``Ui_ToolPathControl`` instance.
    """
    return control._ToolPathControl__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access


def make_control(qtbot: QtBot, candidates: tuple[ToolCandidate, ...] = FOUND) -> ToolPathControl:
    """Build the control listing ``candidates``, kept alive for the test.

    :param qtbot: the pytest-qt fixture.
    :param candidates: the installs to list.
    :returns: the control.
    """
    control = ToolPathControl()
    qtbot.addWidget(control)
    control.set_candidates(candidates)
    return control


@mark.parametrize(
    ("candidate", "expected"),
    [
        param(NEWEST, "9.0.2, usable", id="usable"),
        param(GIT, "unknown version, untested", id="untested-is-usable-so-no-reason"),
        param(TOO_OLD, "3.4, too old: Version 4.0 or newer is needed.", id="unusable-with-its-reason"),
        param(
            ToolCandidate(Path("/x"), "Custom", ToolStatus.MISSING, reason="No FFmpeg at /x."), "not found", id="gone"
        ),
        param(
            ToolCandidate(Path("/x"), "Custom", ToolStatus.NOT_RUNNABLE, reason="/x/ffprobe did not run."),
            "not runnable: /x/ffprobe did not run.",
            id="not-runnable",
        ),
    ],
)
def test_a_candidate_is_summarized_in_the_parenthesis_beside_it(candidate: ToolCandidate, expected: str) -> None:
    """Each row reads its version and status; one that cannot be used says why.

    **Test steps:**

    * summarize each kind of candidate
    * verify the text
    """
    assert summarize(candidate) == expected


def test_one_row_per_install_found_with_its_version_and_the_best_chosen(qtbot: QtBot) -> None:
    """The list is what was found, best first, and the best is chosen by default -- an empty value.

    **Test steps:**

    * list four installs
    * verify one row each, naming its folder and summary, the first checked and the value empty
    """
    control = make_control(qtbot)

    assert [row.full_text() for row in control.rows] == [f"{c.folder} ({summarize(c)})" for c in FOUND]
    assert control.rows[0].isChecked() is True
    assert control.settings_value() == ""
    assert control.chosen_candidate() == NEWEST


def test_an_unusable_install_is_listed_but_cannot_be_chosen(qtbot: QtBot) -> None:
    """Listed so the user sees why it is not used, greyed so it cannot be picked.

    **Test steps:**

    * list four installs, the last too old
    * verify only that row is disabled
    """
    control = make_control(qtbot)

    assert [row.isEnabled() for row in control.rows] == [True, True, True, False]


def test_choosing_another_install_pins_its_folder(qtbot: QtBot) -> None:
    """Any row but the best stores its folder, so a later search finding something newer does not move it.

    **Test steps:**

    * check the second row
    * verify the value is its folder, then check the best again and verify the value is empty
    """
    control = make_control(qtbot)

    control.rows[1].setChecked(True)
    assert control.settings_value() == str(OLDER.folder)

    control.rows[0].setChecked(True)
    assert control.settings_value() == ""


def test_a_pinned_folder_is_staged_into_its_row(qtbot: QtBot) -> None:
    """Reset, Defaults and a page reopening write the value back through here.

    **Test steps:**

    * stage the second install's folder
    * verify its row is checked and the value reads back
    """
    control = make_control(qtbot)

    control.set_settings_value(str(OLDER.folder))

    assert control.rows[1].isChecked() is True
    assert control.settings_value() == str(OLDER.folder)


@mark.parametrize(
    "value",
    [
        param("/elsewhere/bin", id="a-folder-never-found"),
        param(str(TOO_OLD.folder), id="a-found-folder-that-cannot-be-used"),
    ],
)
def test_a_path_that_is_no_usable_row_is_custom(qtbot: QtBot, value: str) -> None:
    """A browsed path, or a pinned install that has gone or broken since, shows under Custom, to be marked there.

    **Test steps:**

    * stage the path
    * verify Custom is checked, holding it, and the value reads back
    """
    control = make_control(qtbot)

    control.set_settings_value(value)

    assert control_ui(control).custom_radio_button.isChecked() is True
    assert control_ui(control).path_edit.text() == value
    assert control.settings_value() == value
    assert control.chosen_candidate() is None


def test_finding_nothing_checks_custom_without_an_edit(qtbot: QtBot) -> None:
    """With nothing listed, Custom is the only row -- and the value is still empty, so it is not a change.

    **Test steps:**

    * list nothing
    * verify no rows, Custom checked and editable, and the value empty
    """
    control = make_control(qtbot, ())

    assert not control.rows
    assert control_ui(control).custom_radio_button.isChecked() is True
    assert control_ui(control).path_edit.isEnabled() is True
    assert control.settings_value() == ""


def test_a_new_list_keeps_the_choice(qtbot: QtBot) -> None:
    """A search finishing while the page is open keeps what the user chose: the best follows, a pin stays.

    **Test steps:**

    * with the best chosen, list a newer install first and verify the new best is chosen
    * pin the older install, list again, and verify the pin is kept
    """
    control = make_control(qtbot, (OLDER,))
    control.set_candidates((NEWEST, OLDER))
    assert control.chosen_candidate() == NEWEST

    control.set_settings_value(str(OLDER.folder))
    control.set_candidates((NEWEST, OLDER, GIT))
    assert control.chosen_candidate() == OLDER


def test_a_pinned_install_that_becomes_the_best_stays_pinned(qtbot: QtBot) -> None:
    """A row chosen by its folder keeps that value when a later search lists it first: the page must not go dirty
    by itself, and a best row chosen by a click still stores the empty value.

    **Test steps:**

    * pin the older install, then list it as the best
    * verify the value is still its folder
    * click the row that is now best and verify the value is empty; click another and verify its folder
    """
    control = make_control(qtbot, (NEWEST, OLDER))
    control.set_settings_value(str(OLDER.folder))

    control.set_candidates((OLDER, GIT))
    assert control.chosen_candidate() == OLDER
    assert control.settings_value() == str(OLDER.folder)

    control.rows[0].click()
    assert control.settings_value() == ""
    control.rows[1].click()
    assert control.settings_value() == str(GIT.folder)


def test_clicking_custom_keeps_what_was_pinned_for_the_rows(qtbot: QtBot) -> None:
    """Custom is its own value, the typed path; clicking it forgets no pin, so clicking the row back restores it.

    **Test steps:**

    * pin the older install, click Custom, then click the older install's row again
    * verify the value went to the typed path and back to the pinned folder
    """
    control = make_control(qtbot, (NEWEST, OLDER))
    control.set_settings_value(str(OLDER.folder))

    control_ui(control).custom_radio_button.click()
    assert control.settings_value() == ""

    control.rows[1].click()
    assert control.settings_value() == str(OLDER.folder)


def test_an_empty_custom_gives_way_to_an_install_found_later(qtbot: QtBot) -> None:
    """Once something is installed, an unused Custom gives way to the best; a typed path does not.

    **Test steps:**

    * list nothing, then an install, and verify it is chosen
    * type a custom path, list again, and verify Custom is kept
    """
    control = make_control(qtbot, ())
    control.set_candidates((NEWEST,))
    assert control.chosen_candidate() == NEWEST

    control_ui(control).custom_radio_button.setChecked(True)
    control_ui(control).path_edit.setText("/mine")
    control.set_candidates((NEWEST,))
    assert control.settings_value() == "/mine"


def test_the_custom_row_is_marked_with_what_is_at_its_path(qtbot: QtBot) -> None:
    """A custom path that holds nothing usable reads *not found* beside it and is painted as a warning.

    **Test steps:**

    * mark the custom row with a missing install, then with a usable one, then with nothing
    * verify the parenthesis and the warning follow
    """
    control = make_control(qtbot)
    ui = control_ui(control)

    control.set_custom_status(ToolCandidate(Path("/x"), "Custom", ToolStatus.MISSING, reason="No FFmpeg at /x."))
    assert ui.custom_status_label.text() == f"({NOT_FOUND_TEXT})"
    assert ui.path_edit.property(WARNING_PROPERTY) is True

    control.set_custom_status(NEWEST)
    assert ui.custom_status_label.text() == "(9.0.2, usable)"
    assert ui.path_edit.property(WARNING_PROPERTY) is False

    control.set_custom_status(None)
    assert ui.custom_status_label.text() == ""


def test_the_path_is_editable_only_under_custom(qtbot: QtBot) -> None:
    """The path and Browse follow the radios, and what was typed stays visible under a row.

    **Test steps:**

    * choose Custom, type, and choose the best row
    * verify the controls were enabled and then disabled, and the text kept
    """
    control = make_control(qtbot)
    ui = control_ui(control)

    ui.custom_radio_button.setChecked(True)
    assert ui.path_edit.isEnabled() is True
    assert ui.browse_button.isEnabled() is True
    ui.path_edit.setText("/mine")

    control.rows[0].setChecked(True)
    assert ui.path_edit.isEnabled() is False
    assert ui.path_edit.text() == "/mine"


def test_the_choice_changing_is_announced_once_per_switch(qtbot: QtBot) -> None:
    """The frame re-checks its status on each of these, and once is enough.

    **Test steps:**

    * switch rows, switch to Custom and type
    * verify one announcement each
    """
    control = make_control(qtbot)
    announced: list[None] = []
    control.choice_changed.connect(lambda: announced.append(None))

    control.rows[1].setChecked(True)
    control_ui(control).custom_radio_button.setChecked(True)
    control_ui(control).path_edit.setText("/mine")

    assert len(announced) == 3


def test_looking_shows_until_a_list_arrives(qtbot: QtBot) -> None:
    """A search going is said, and the list it brings replaces it.

    **Test steps:**

    * say a search is going and verify the line is shown
    * list installs and verify it is gone
    """
    control = make_control(qtbot, ())

    control.set_looking()
    assert control_ui(control).looking_label.isHidden() is False

    control.set_candidates(FOUND)
    assert control_ui(control).looking_label.isHidden() is True


def test_browse_fills_the_path_from_the_file_dialog(qtbot: QtBot, mocker: MockerFixture) -> None:
    """Picking a file writes its path into the edit, titled for the tool.

    **Test steps:**

    * name the dialog's title, mock it to return a path, choose Custom and click Browse
    * verify the edit holds the path and the dialog was titled
    """
    dialog = mocker.patch(
        "rehuco_agent.settings.ui.tool_path_control.QFileDialog.getOpenFileName", return_value=("/pick", "")
    )
    control = make_control(qtbot)
    control.browse_title = "Locate FFmpeg"
    ui = control_ui(control)
    ui.custom_radio_button.setChecked(True)

    ui.browse_button.click()

    assert ui.path_edit.text() == "/pick"
    assert dialog.call_args.args[1] == "Locate FFmpeg"


def test_a_cancelled_pick_leaves_the_path_alone(qtbot: QtBot, mocker: MockerFixture) -> None:
    """Cancelling the dialog must not blank a path already typed.

    **Test steps:**

    * type a path, mock the dialog to return nothing and click Browse
    * verify the edit still holds the path
    """
    mocker.patch("rehuco_agent.settings.ui.tool_path_control.QFileDialog.getOpenFileName", return_value=("", ""))
    control = make_control(qtbot)
    ui = control_ui(control)
    ui.custom_radio_button.setChecked(True)
    ui.path_edit.setText("/mine")

    ui.browse_button.click()

    assert ui.path_edit.text() == "/mine"
