"""Tests for what a document's sub-docks show and do about saves handed to jobs (#497): the banner rows of a save out,
a save pending and a record gone, and Save handing the edits to the window's save jobs.

Driven through `DocumentWidget`, as ``test_document_sub_docks_conflict`` is; the model is an in-memory document bound
to a path under ``tmp_path`` with no file, since only what it says is shown -- nothing here reads or writes it.
"""

from pathlib import Path
from unittest.mock import MagicMock

from borco_pyside.widgets import MessageBanner, MessageBannerSeverity
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.document_sub_docks import CONFLICT_MESSAGE, GONE_REMEDY, SAVING_MESSAGE
from rehuco_agent.documents.document_widget import DocumentWidget
from rehuco_agent.documents.pending_saves import PendingSaves
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_core import RecordConflict, RecordVersion, RehuDocument


@fixture(name="model")
def fixture_model(tmp_path: Path) -> RehuDocumentModel:
    """A tutorial's model, bound to a path under ``tmp_path`` with no file there.

    :param tmp_path: pytest's temporary folder.
    :returns: the model.
    """
    return RehuDocumentModel(
        RehuDocument({"type": "Tutorial", "sources": [{"title": "Foo", "primary": True}]}, tmp_path / "info.rehu")
    )


@fixture(name="banner_rows")
def fixture_banner_rows(
    qtbot: QtBot, model: RehuDocumentModel, mocker: MockerFixture
) -> tuple[DocumentWidget, MagicMock]:
    """A document widget over ``model``, with the rows its banner is given recorded.

    :param qtbot: pytest-qt fixture.
    :param model: the document.
    :param mocker: pytest-mock fixture.
    :returns: the widget, and the spy on its banner's ``set_rows``.
    """
    widget = DocumentWidget(model)
    qtbot.addWidget(widget)
    banner = widget.findChild(MessageBanner)
    assert isinstance(banner, MessageBanner)
    return widget, mocker.spy(banner, "set_rows")


def shown(spy: MagicMock) -> list[tuple[MessageBannerSeverity, str]]:
    """The rows the banner was last given, each as its severity and text.

    :param spy: the spy on the banner's ``set_rows``.
    :returns: the rows.
    """
    (rows,) = spy.call_args.args
    return [(row.severity, row.text) for row in rows]


def conflict_over(model: RehuDocumentModel) -> RecordConflict:
    """A refusal of ``model``'s save, for the conflict row.

    :param model: the document.
    :returns: the refusal.
    """
    return RecordConflict(RehuDocument.new(model.path), RecordVersion("metadata", "file", ()))


def test_a_record_gone_is_an_error_row_saying_what_to_do(
    banner_rows: tuple[DocumentWidget, MagicMock], model: RehuDocumentModel
) -> None:
    """The document's file or folder that went is named in an error row, with what the edits can still become; once
    it is back the row goes.

    **Test steps:**

    * say the document's file is gone
    * verify the banner shows an error row naming it, followed by the remedy
    * say it is back
    * verify the row is gone
    """
    _, spy = banner_rows

    model.gone = "The file is gone: here"

    assert shown(spy) == [(MessageBannerSeverity.ERROR, "The file is gone: here" + GONE_REMEDY)]

    model.gone = ""

    assert shown(spy) == []


def test_the_save_rows_follow_the_gone_and_conflict_rows(
    banner_rows: tuple[DocumentWidget, MagicMock], model: RehuDocumentModel
) -> None:
    """A save out shows beside what is gone and a refused save, in that order: the error first, then the conflict, then
    what is under way.

    **Test steps:**

    * say the file is gone, hold a conflict, and hand the document to a save
    * verify the banner shows the gone error row, the conflict warning row and the saving info row, in that order
    """
    _, spy = banner_rows

    model.gone = "The file is gone: here"
    model.conflict = conflict_over(model)
    model.saving = True

    assert shown(spy) == [
        (MessageBannerSeverity.ERROR, "The file is gone: here" + GONE_REMEDY),
        (MessageBannerSeverity.WARNING, CONFLICT_MESSAGE),
        (MessageBannerSeverity.INFO, SAVING_MESSAGE),
    ]


def test_what_the_pending_save_is_doing_comes_before_saving_which_stands_in_while_the_row_says_nothing(
    banner_rows: tuple[DocumentWidget, MagicMock], model: RehuDocumentModel
) -> None:
    """While a save is out, the banner says what its row is doing -- pending, waiting -- as a warning; only while the
    row says nothing, which is while it writes, does *Saving…* stand in; once the save is back, no row is left.

    **Test steps:**

    * hand the document to a save, and say its row is waiting
    * verify only the waiting row shows, as a warning
    * have the row say nothing, as a writing one does
    * verify only the saving info row shows
    * take the save back
    * verify no row is left
    """
    _, spy = banner_rows

    model.saving = True
    model.pending_save = "Save waiting: the share does not answer"

    assert shown(spy) == [(MessageBannerSeverity.WARNING, "Save waiting: the share does not answer")]

    model.pending_save = ""

    assert shown(spy) == [(MessageBannerSeverity.INFO, SAVING_MESSAGE)]

    model.saving = False

    assert shown(spy) == []


def test_a_pending_row_gives_way_to_a_conflict_row(
    banner_rows: tuple[DocumentWidget, MagicMock], model: RehuDocumentModel
) -> None:
    """A pending save refused as a conflict is said by the conflict row, which says what Save does now; the pending
    row is not shown beside it.

    **Test steps:**

    * say the pending save failed, then hold a conflict
    * verify only the conflict row shows
    * drop the conflict
    * verify the pending row is back
    """
    _, spy = banner_rows
    model.pending_save = "Save failed"

    model.conflict = conflict_over(model)

    assert shown(spy) == [(MessageBannerSeverity.WARNING, CONFLICT_MESSAGE)]

    model.conflict = None

    assert shown(spy) == [(MessageBannerSeverity.WARNING, "Save failed")]


def test_save_hands_the_edits_to_the_windows_save_jobs(
    qtbot: QtBot, model: RehuDocumentModel, mocker: MockerFixture
) -> None:
    """With the window's save jobs given, Save hands the document to them and goes back to editing; nothing is
    written here.

    **Test steps:**

    * build a document widget over the model with stand-in save jobs, and edit the title
    * trigger Save
    * verify the save jobs were asked to save the document, parented to the widget, and the model did not save itself
    """
    pending = mocker.Mock(spec=PendingSaves)
    widget = DocumentWidget(model, pending_saves=pending)
    qtbot.addWidget(widget)
    model.title = "Mine"
    save = mocker.patch.object(model, "save")

    widget.save_action.trigger()

    pending.save.assert_called_once_with(widget, model)
    save.assert_not_called()


def test_save_is_offered_on_a_clean_document_while_its_record_has_a_pending_save(
    qtbot: QtBot, model: RehuDocumentModel
) -> None:
    """A save not landed is the saved state, and Save is what tries it again or settles its failure: it is offered on
    the clean document while that save is pending, and not once it is gone (#497).

    **Test steps:**

    * build a document widget over the clean model
    * verify Save is not offered
    * say the record's save failed, then clear it
    * verify Save was offered while it was said, and not after
    """
    widget = DocumentWidget(model)
    qtbot.addWidget(widget)
    assert not widget.save_action.isEnabled()

    model.pending_save = "Save failed"
    offered = widget.save_action.isEnabled()
    model.pending_save = ""

    assert offered
    assert not widget.save_action.isEnabled()


def test_save_is_offered_at_once_on_a_document_opened_with_a_pending_save(
    qtbot: QtBot, model: RehuDocumentModel
) -> None:
    """A document whose record already has a save pending when its widget is built offers Save from the start.

    **Test steps:**

    * say the clean model's record has a pending save
    * build a document widget over it
    * verify Save is offered
    """
    model.pending_save = "Save pending"

    widget = DocumentWidget(model)
    qtbot.addWidget(widget)

    assert widget.save_action.isEnabled()
