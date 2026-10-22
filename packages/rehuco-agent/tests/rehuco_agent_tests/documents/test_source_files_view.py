"""Tests for the inspection views' one section per file (#513): a record is its ``.rehu`` and a sidecar per user
([[data-model#single-file]]), so the Save Preview and On Disk views each show every file under a banner that collapses
it, the way a content-image group's does."""

import json
from pathlib import Path
from typing import Final

from PySide6.QtCore import Qt
from pytest import raises
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.documents.source_views import (
    NOT_ON_DISK_PLACEHOLDER,
    OnDiskView,
    SavePreviewView,
    SourceFilesView,
)
from rehuco_core import RehuDocument

FILES: Final = [("info.rehu", "{record}\n"), ("info.user-bob.rehuser", "{bob}\n"), ("info.user-ioan.rehuser", "{}\n")]

RATED: Final = {
    "format_version": 2,
    "core": {"id": "00000000-0000-0000-0000-000000000001", "type": "tutorial"},
    "tutorial": {"format_version": 2, "users": {"ioan": {"rating": 4}, "bob": {"rating": 2}}},
}


def shown[View: SourceFilesView](qtbot: QtBot, view: View) -> View:
    """Register a view for teardown and show it.

    :param qtbot: the pytest-qt bot.
    :param view: the view.
    :returns: the view, shown.
    """
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    return view


# region The sections


def test_every_file_is_shown_expanded_under_its_banner(qtbot: QtBot) -> None:
    """Each file gets a banner naming it and its text below, in the order given, all expanded at first.

    **Test steps:**

    * show three files
    * verify the files shown, each banner's ``-`` mark and name, and every text visible
    """
    view = shown(qtbot, SourceFilesView())

    view.set_files(FILES)

    assert view.files() == FILES
    assert [view.banner(name).text for name, _ in FILES] == [f"- {name}" for name, _ in FILES]
    assert all(view.text_label(name).isVisible() for name, _ in FILES)


def test_a_click_on_a_banner_collapses_its_file_and_another_expands_it(qtbot: QtBot) -> None:
    """A banner toggles its own file, leaving the others as they are.

    **Test steps:**

    * show three files and click Bob's banner
    * verify Bob's text hidden under a ``+`` banner, the others visible
    * click it again and verify Bob's text is back under a ``-`` banner
    """
    view = shown(qtbot, SourceFilesView())
    view.set_files(FILES)
    bob = "info.user-bob.rehuser"

    qtbot.mouseClick(view.banner(bob), Qt.MouseButton.LeftButton)

    assert view.is_collapsed(bob)
    assert view.banner(bob).text == f"+ {bob}"
    assert [view.text_label(name).isVisible() for name, _ in FILES] == [True, False, True]
    qtbot.mouseClick(view.banner(bob), Qt.MouseButton.LeftButton)
    assert not view.is_collapsed(bob)
    assert view.text_label(bob).isVisible()


def test_only_a_left_click_toggles_a_file(qtbot: QtBot) -> None:
    """A right click on a banner leaves its file as it is.

    **Test steps:**

    * show three files and right-click the record's banner
    * verify the record still expanded
    """
    view = shown(qtbot, SourceFilesView())
    view.set_files(FILES)

    qtbot.mouseClick(view.banner("info.rehu"), Qt.MouseButton.RightButton)

    assert not view.is_collapsed("info.rehu")
    assert view.text_label("info.rehu").isVisible()


def test_a_file_not_shown_has_no_section(qtbot: QtBot) -> None:
    """Asking for a file the view does not show is an error, not a guess.

    **Test steps:**

    * show three files
    * verify asking for another file's banner raises ``KeyError``
    """
    view = shown(qtbot, SourceFilesView())
    view.set_files(FILES)

    with raises(KeyError, match="other.rehu"):
        view.banner("other.rehu")


def test_a_collapsed_file_stays_collapsed_when_the_files_are_shown_again(qtbot: QtBot) -> None:
    """Re-rendering -- the same files with new text, or a different set holding the same name -- keeps a file's
    section collapsed.

    **Test steps:**

    * show three files and collapse Bob's
    * show them again with new text, then show only the record and Bob's
    * verify Bob's section collapsed throughout, holding its new text
    """
    view = shown(qtbot, SourceFilesView())
    view.set_files(FILES)
    bob = "info.user-bob.rehuser"
    view.set_collapsed(bob, True)

    view.set_files([(name, text + "changed\n") for name, text in FILES])
    collapsed_after_new_text = view.is_collapsed(bob) and not view.text_label(bob).isVisible()
    view.set_files([FILES[0], (bob, "{bob again}\n")])

    assert collapsed_after_new_text
    assert view.files() == [FILES[0], (bob, "{bob again}\n")]
    assert view.banner(bob).text == f"+ {bob}"
    assert not view.text_label(bob).isVisible()


# endregion

# region What each view shows


def test_the_save_preview_shows_the_record_and_each_users_sidecar(qtbot: QtBot, tmp_path: Path) -> None:
    """The preview is the files a save writes: the record without its maps, then each user's sidecar.

    **Test steps:**

    * preview a document carrying two users' ratings, bound to ``info.rehu``
    * verify the record's text, then Bob's and Ioan's sidecars, as the document serializes them
    """
    document = RehuDocument(json.loads(json.dumps(RATED)), tmp_path / "info.rehu")
    view = shown(qtbot, SavePreviewView(RehuDocumentModel(document)))

    sidecars = document.serialize_user_sidecars()
    assert view.files() == [
        ("info.rehu", document.serialize()),
        ("info.user-bob.rehuser", sidecars["bob"]),
        ("info.user-ioan.rehuser", sidecars["ioan"]),
    ]
    assert '"users"' not in document.serialize()


def test_the_save_preview_of_a_document_with_no_file_names_it_untitled(qtbot: QtBot) -> None:
    """A document never saved has no name yet; its files are previewed under ``untitled``.

    **Test steps:**

    * preview a pathless document carrying Ioan's rating
    * verify the files are named ``untitled.rehu`` and ``untitled.user-ioan.rehuser``
    """
    data = {"tutorial": {"format_version": 2, "users": {"ioan": {"rating": 4}}}}
    view = shown(qtbot, SavePreviewView(RehuDocumentModel(RehuDocument(data))))

    assert [name for name, _ in view.files()] == ["untitled.rehu", "untitled.user-ioan.rehuser"]


def test_on_disk_shows_the_record_and_every_users_sidecar_as_stored(
    qtbot: QtBot, tmp_path: Path, real_path_stat: None
) -> None:
    """The view reads every file of the record off disk, verbatim: the record, then each user's sidecar by name --
    every user's, not only the one opened as.

    **Test steps:**

    * save a record carrying two users' ratings, and open it as ``ioan``
    * show the On Disk view
    * verify the record's and both sidecars' bytes, the record first
    """
    del real_path_stat
    record = tmp_path / "info.rehu"
    RehuDocument(json.loads(json.dumps(RATED)), record, username="ioan").save()
    model = RehuDocumentModel(RehuDocument.load(record, username="ioan"))

    view = shown(qtbot, OnDiskView(model))

    assert view.files() == [
        (name, (tmp_path / name).read_text(encoding="utf-8"))
        for name in ("info.rehu", "info.user-bob.rehuser", "info.user-ioan.rehuser")
    ]


def test_on_disk_names_the_placeholder_after_the_record(qtbot: QtBot) -> None:
    """With no file there is one section: the record's name, and the placeholder.

    **Test steps:**

    * show the On Disk view of a pathless document
    * verify one ``untitled.rehu`` section holding the placeholder
    """
    view = shown(qtbot, OnDiskView(RehuDocumentModel(RehuDocument({}))))

    assert view.files() == [("untitled.rehu", NOT_ON_DISK_PLACEHOLDER)]


# endregion
