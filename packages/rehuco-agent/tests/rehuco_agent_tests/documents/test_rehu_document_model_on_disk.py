"""Tests for a document model following its file as it is on disk (#487, verify-on-access).

What the catalog reports of a file -- its modification time and size now -- reaches every open model; each compares it
with what it read or wrote itself. Real files under ``tmp_path``.
"""

from pathlib import Path

from pytest import mark
from rehuco_agent.documents.document_registry import load_or_locked
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_core import RehuDocument

pytestmark = mark.usefixtures("real_path_stat")


def saved(path: Path, title: str) -> None:
    """Write a record with ``title``.

    :param path: where.
    :param title: its title.
    """
    document = RehuDocument.new(path)
    document.title = title
    document.save()


def on_disk(path: Path) -> tuple[int, int]:
    """The file's modification time and size, as the catalog reports them."""
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


def opened(path: Path) -> RehuDocumentModel:
    """The model an open builds."""
    return RehuDocumentModel(load_or_locked(path))


def test_an_opened_document_that_is_clean_reloads_a_file_changed_outside_the_app(tmp_path: Path) -> None:
    """The title follows the file, with nothing asked.

    **Test steps:**

    * open a record, then change its file outside the app
    * report the file as it is now
    * verify the model reads the new title and is still clean
    """
    path = tmp_path / "info.rehu"
    saved(path, "Old")
    model = opened(path)
    saved(path, "New, and longer")

    model.note_file_signature(*on_disk(path))

    assert (model.title, model.dirty, model.changed_on_disk) == ("New, and longer", False, False)


def test_a_document_with_unsaved_edits_is_left_alone_and_says_the_file_changed(tmp_path: Path) -> None:
    """A reload would discard the edits and a save would overwrite the other change: the user chooses.

    **Test steps:**

    * open a record and edit its title, then change its file outside the app
    * report the file as it is now
    * verify the edit stands and :attr:`changed_on_disk` is raised; a revert reads the file and lowers it
    """
    path = tmp_path / "info.rehu"
    saved(path, "Old")
    model = opened(path)
    model.title = "Mine"
    saved(path, "Theirs, and longer")

    model.note_file_signature(*on_disk(path))

    assert (model.title, model.dirty, model.changed_on_disk) == ("Mine", True, True)
    model.revert()
    assert (model.title, model.changed_on_disk) == ("Theirs, and longer", False)


def test_a_report_of_the_file_as_the_model_last_read_or_wrote_it_changes_nothing(tmp_path: Path) -> None:
    """The report that follows an open, or the model's own save, is not a change.

    **Test steps:**

    * open a record and report it unchanged: verify nothing moves
    * edit and save it, and report it as saved: verify nothing moves either
    """
    path = tmp_path / "info.rehu"
    saved(path, "Old")
    model = opened(path)
    reloads: list[None] = []
    model.reloaded.connect(lambda: reloads.append(None))

    model.note_file_signature(*on_disk(path))
    model.title = "Saved here, and longer"
    model.save()
    model.note_file_signature(*on_disk(path))

    assert (reloads, model.changed_on_disk) == ([], False)


def test_a_document_whose_file_cannot_be_read_has_nothing_to_compare_with(tmp_path: Path) -> None:
    """A model standing for a file that is not there never reloads, nor flags: a report cannot tell it anything.

    **Test steps:**

    * build a model over a path with no file, and report some file state
    * verify it neither reloaded nor flagged
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, tmp_path / "missing" / "info.rehu"))
    reloads: list[None] = []
    model.reloaded.connect(lambda: reloads.append(None))

    model.note_file_signature(7, 3)

    assert (reloads, model.changed_on_disk) == ([], False)
