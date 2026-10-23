"""Tests for what a per-user sidecar that cannot be read does to an open document (#568, [[data-model#single-file]]):
the model mirrors it, the banner names it, and only the user's own state goes read-only -- never the details."""

from pathlib import Path
from typing import Final

from borco_pyside.widgets import MessageBanner
from PySide6.QtWidgets import QLabel, QLineEdit
from pytest import mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.document_sub_docks import OWN_SIDECAR_MESSAGE, UNREADABLE_SIDECAR_REMEDY
from rehuco_agent.documents.document_widget import DocumentWidget
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields.widgets import RatingSlider
from rehuco_core import DEFAULT_CURRENT_USERNAME, user_sidecar_path

from .test_rehu_document_model_conflict import opened, write_record

pytestmark = mark.usefixtures("real_path_stat")

BAD: Final = "{not json"
"""A sidecar text this build cannot read."""

GOOD: Final = '{"format_version": 1, "tutorial": {"rating": 3}}'
"""A sidecar text it can."""


def banner_rows(widget: DocumentWidget) -> list[str]:
    """What each row of the document's banner says.

    :param widget: the document's widget.
    :returns: the rows' texts.
    """
    banner = widget.findChild(MessageBanner)
    assert isinstance(banner, MessageBanner)
    return [label.text() for label in banner.findChildren(QLabel)]


def title_editor(widget: DocumentWidget, title: str) -> QLineEdit:
    """The line edit holding a title, in the editor docks as they are now.

    :param widget: the document's widget.
    :param title: the title it holds.
    :returns: the edit.
    """
    docks = widget.sub_docks._DocumentSubDocks__editor_docks  # type: ignore[attr-defined]  # pylint: disable=protected-access
    return next(
        edit for dock in docks.values() for edit in dock.widget().findChildren(QLineEdit) if edit.text() == title
    )


def rating_editor(widget: DocumentWidget) -> RatingSlider:
    """The rating's editor, in the editor docks as they are now.

    :param widget: the document's widget.
    :returns: the slider.
    """
    docks = widget.sub_docks._DocumentSubDocks__editor_docks  # type: ignore[attr-defined]  # pylint: disable=protected-access
    slider = next(
        dock.widget().findChild(RatingSlider) for dock in docks.values() if dock.widget().findChild(RatingSlider)
    )
    assert isinstance(slider, RatingSlider)
    return slider


def record_beside(tmp_path: Path, username: str, text: str) -> Path:
    """A record, and a sidecar of ``username`` beside it.

    :param tmp_path: where they are written.
    :param username: whose sidecar.
    :param text: what it holds.
    :returns: the sidecar.
    """
    record = tmp_path / "info.rehu"
    write_record(record, "Old")
    sidecar = user_sidecar_path(record, username)
    sidecar.write_text(text, encoding="utf-8")
    return sidecar


def test_the_model_mirrors_a_sidecar_that_cannot_be_read_without_locking(tmp_path: Path) -> None:
    """Another user's bad sidecar is named, and the document is neither locked nor read-only for its owner's state.

    **Test steps:**

    * open a record beside a bad sidecar of ``bob``
    * verify his file's reason is listed, the user's state is not locked and the model is not locked
    """
    record_beside(tmp_path, "bob", BAD)

    model = opened(tmp_path / "info.rehu")

    assert [reason.split(":", maxsplit=1)[0] for reason in model.unreadable_sidecars] == ["info.user-bob.rehuser"]
    assert not model.user_state_locked
    assert not model.locked


def test_the_model_follows_the_current_users_own_bad_sidecar_through_a_revert(
    mocker: MockerFixture, tmp_path: Path
) -> None:
    """The user's own state is locked while their sidecar is bad, and a revert after fixing it frees it, each way
    announced.

    **Test steps:**

    * open a record beside a bad sidecar of the current user
    * verify the user's state is locked and the model is not
    * fix the sidecar, and revert, watching the two signals
    * verify both cleared, each announced once
    """
    sidecar = record_beside(tmp_path, DEFAULT_CURRENT_USERNAME, BAD)
    model = opened(tmp_path / "info.rehu")
    assert model.user_state_locked
    assert not model.locked
    sidecar.write_text(GOOD, encoding="utf-8")

    listed, locked = mocker.Mock(), mocker.Mock()
    model.unreadable_sidecars_changed.connect(listed)  # type: ignore[attr-defined]
    model.user_state_locked_changed.connect(locked)  # type: ignore[attr-defined]

    model.revert()

    assert model.unreadable_sidecars == []
    assert not model.user_state_locked
    assert (listed.call_count, locked.call_count) == (1, 1)


def test_the_banner_names_another_users_bad_sidecar_and_the_state_stays_editable(qtbot: QtBot, tmp_path: Path) -> None:
    """The banner says which file and why, never claims the user's own state is read-only, and leaves every editor
    enabled.

    **Test steps:**

    * open a record beside a bad sidecar of ``bob`` in a document widget
    * verify one row names his file with the remedy, and no row speaks of the user's own state
    * verify the rating and the title editors are enabled
    """
    record_beside(tmp_path, "bob", BAD)
    widget = DocumentWidget(opened(tmp_path / "info.rehu"))
    qtbot.addWidget(widget)

    rows = banner_rows(widget)

    assert [row for row in rows if row.startswith("info.user-bob.rehuser") and row.endswith(UNREADABLE_SIDECAR_REMEDY)]
    assert OWN_SIDECAR_MESSAGE not in rows
    assert rating_editor(widget).isEnabled()
    assert title_editor(widget, "Old").isEnabled()


def test_the_users_own_bad_sidecar_makes_only_their_state_read_only(qtbot: QtBot, tmp_path: Path) -> None:
    """The rating's editor is disabled and the title's is not, the banner says so, and fixing the file and reverting
    gives the editor back and clears the rows.

    **Test steps:**

    * open a record beside a bad sidecar of the current user in a document widget
    * verify the banner holds the file's row and the own-state row, the rating editor is disabled and the title
      editor enabled
    * fix the sidecar and revert
    * verify the rows are gone and the rating editor is enabled
    """
    sidecar = record_beside(tmp_path, DEFAULT_CURRENT_USERNAME, BAD)
    model: RehuDocumentModel = opened(tmp_path / "info.rehu")
    widget = DocumentWidget(model)
    qtbot.addWidget(widget)

    rows = banner_rows(widget)

    assert OWN_SIDECAR_MESSAGE in rows
    assert [row for row in rows if row.endswith(UNREADABLE_SIDECAR_REMEDY)]
    assert not rating_editor(widget).isEnabled()
    assert title_editor(widget, "Old").isEnabled()
    sidecar.write_text(GOOD, encoding="utf-8")

    model.revert()

    assert not [row for row in banner_rows(widget) if row.endswith(UNREADABLE_SIDECAR_REMEDY)]
    assert OWN_SIDECAR_MESSAGE not in banner_rows(widget)
    assert rating_editor(widget).isEnabled()


def test_the_banner_and_the_editors_follow_the_model_without_a_reload(qtbot: QtBot, tmp_path: Path) -> None:
    """What the model says changes the banner and the rating's editor at once -- no load, no rebuilt form -- and the
    other way round.

    **Test steps:**

    * open a clean record in a document widget
    * make the model name an unreadable sidecar
    * verify the banner holds the file's row alone, and the rating editor is enabled
    * lock the user's own state
    * verify the banner also holds the own-state row, and the rating editor is disabled
    * clear both
    * verify the rows are gone and the rating editor is enabled
    """
    record = tmp_path / "info.rehu"
    write_record(record, "Old")
    model = opened(record)
    widget = DocumentWidget(model)
    qtbot.addWidget(widget)

    model.unreadable_sidecars = ["info.user-bob.rehuser: invalid JSON."]

    assert f"info.user-bob.rehuser: invalid JSON.{UNREADABLE_SIDECAR_REMEDY}" in banner_rows(widget)
    assert OWN_SIDECAR_MESSAGE not in banner_rows(widget)
    assert rating_editor(widget).isEnabled()
    model.user_state_locked = True

    assert OWN_SIDECAR_MESSAGE in banner_rows(widget)
    assert not rating_editor(widget).isEnabled()
    model.unreadable_sidecars = []
    model.user_state_locked = False

    assert not [row for row in banner_rows(widget) if row.endswith(UNREADABLE_SIDECAR_REMEDY)]
    assert OWN_SIDECAR_MESSAGE not in banner_rows(widget)
    assert rating_editor(widget).isEnabled()
