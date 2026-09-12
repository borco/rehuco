"""Tests for the file browser dock: when it reads, where it will and will not go, and what a
double-click does (#266).

The rows arrive through the real background loader, so every test settles the pool before reading the
table -- which is also the claim that *a listing does not block the GUI* being exercised rather than
stated. What each file *is* comes from the real classifier over a mocked listing; which row is which
kind is `test_rehu_file_kinds`' subject, and the rows themselves are `test_files_rows`'.
"""

from pathlib import Path
from typing import Any, Final

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.files_rows import NAME_COLUMN, PARENT_ROW_NAME, FileRow, FilesTableModel
from rehuco_agent.documents.files_view import LOADING_SUMMARY, NO_PATH_SUMMARY, UNREACHABLE_SUMMARY, FilesView
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_core import (
    ChecksumRecordError,
    DirectoryClassifier,
    DirectoryEntry,
    DirectoryListing,
    FileKind,
    FileType,
    RehuDocument,
)

DIRECTORY: Final = Path("/fake/library/sculpting")
INFO_PATH: Final = DIRECTORY / "info.rehu"
SUB: Final = DIRECTORY / "sub"

TIMEOUT: Final = 5000

ROOT_ENTRIES: Final = (
    DirectoryEntry("info.rehu", FileKind.OWN_RECORD, FileType.RECORD),
    DirectoryEntry("info.checksum", FileKind.OWN_MANIFEST, FileType.MANIFEST),
    DirectoryEntry("info00.jpg", FileKind.OWN_SCREENSHOT, FileType.IMAGE),
    DirectoryEntry("info01.jpg", FileKind.OWN_SCREENSHOT, FileType.IMAGE),
    DirectoryEntry("other.rehu", FileKind.FOREIGN_RECORD, FileType.RECORD),
    DirectoryEntry("other00.jpg", FileKind.FOREIGN_SIDECAR, FileType.IMAGE),
    DirectoryEntry("lesson01.mp4", FileKind.CONTENT, FileType.VIDEO),
    DirectoryEntry("sub", FileKind.DIRECTORY, FileType.DIRECTORY),
)
SUB_ENTRIES: Final = (DirectoryEntry("deeper.mp4", FileKind.CONTENT, FileType.VIDEO),)

TREE: Final = {DIRECTORY: ROOT_ENTRIES, SUB: SUB_ENTRIES}


@fixture(name="listing", autouse=True)
def fixture_listing(mocker: MockerFixture) -> Any:
    """The classifier, answering per directory from :data:`TREE`.

    Mocked at the classifier rather than at ``os.scandir`` so a test declares a folder without also
    declaring how a listing spells it; the filesystem is never touched either way.

    :param mocker: pytest-mock fixture.
    :returns: the patched ``classify``, for the tests that count how often it ran.
    """
    return mocker.patch.object(
        DirectoryClassifier,
        "classify",
        autospec=True,
        side_effect=lambda _self, directory: DirectoryListing(directory, entries=TREE.get(directory, ())),
    )


@fixture(name="record", autouse=True)
def fixture_record(mocker: MockerFixture) -> None:
    """A resource that has never been checksummed -- the column is `test_files_rows`' subject.

    :param mocker: pytest-mock fixture.
    """
    mocker.patch("rehuco_agent.documents.files_rows.load_checksum_record", side_effect=FileNotFoundError)


@fixture(name="model")
def fixture_model() -> RehuDocumentModel:
    """A view-model over a directory-scoped resource.

    :returns: the model the browser is about.
    """
    return RehuDocumentModel(RehuDocument({"type": "Tutorial"}, INFO_PATH))


@fixture(name="view")
def fixture_view(qtbot: QtBot, model: RehuDocumentModel) -> FilesView:
    """A shown browser whose first read has already landed.

    Parentless and shown, because a hidden dock deliberately reads nothing (#111's discipline): every
    test here but the deferral pair is about what the table says once someone is looking at it.

    :param qtbot: pytest-qt fixture.
    :param model: the document.
    :returns: the view.
    """
    view = FilesView(model)
    qtbot.addWidget(view)
    view.show()
    settle(qtbot, view)
    return view


def settle(qtbot: QtBot, view: FilesView) -> None:
    """Wait for the background listing to land.

    :param qtbot: pytest-qt fixture.
    :param view: the view whose summary stops saying *reading* once it has.
    """
    qtbot.waitUntil(lambda: view.summary != LOADING_SUMMARY, timeout=TIMEOUT)


def drawn(view: FilesView) -> list[str]:
    """The names, in the order the table draws them.

    :param view: the view to read.
    :returns: the names.
    """
    return [view.proxy.index(row, NAME_COLUMN).data() for row in range(view.proxy.rowCount())]


def row_of(view: FilesView, name: str) -> int:
    """Which view row a name is drawn on.

    :param view: the view to read.
    :param name: the row's name.
    :returns: the row number as drawn -- the only numbering an activation speaks in.
    """
    return drawn(view).index(name)


def enabled(view: FilesView, name: str) -> bool:
    """Whether a row can be acted on at all.

    :param view: the view to read.
    :param name: the row's name.
    :returns: whether its index is enabled.
    """
    index = view.proxy.index(row_of(view, name), NAME_COLUMN)
    return bool(view.proxy.flags(index) & Qt.ItemFlag.ItemIsEnabled)


# region When it reads


def test_showing_the_dock_triggers_exactly_one_listing(qtbot: QtBot, model: RehuDocumentModel, listing: Any) -> None:
    """A hidden dock reads nothing, so opening a document costs nothing until its folder is asked for
    -- and being shown then costs exactly one listing, not one per signal that fired on the way.

    **Test steps:**

    * build the browser without showing it, and verify nothing was listed
    * show it, and verify exactly one listing ran
    """
    view = FilesView(model)
    qtbot.addWidget(view)

    assert listing.call_count == 0

    view.show()
    settle(qtbot, view)

    assert listing.call_count == 1


def test_a_refresh_while_hidden_is_caught_up_when_shown(qtbot: QtBot, model: RehuDocumentModel, listing: Any) -> None:
    """The deferral is not a refusal: a refresh asked for while hidden flags the table stale, and the
    next show reads it -- otherwise a dock reopened after a rename would draw the old folder.

    **Test steps:**

    * refresh a hidden browser twice, and verify nothing was listed
    * show it, and verify the deferred read ran once
    """
    view = FilesView(model)
    qtbot.addWidget(view)

    view.refresh()
    view.refresh()

    assert listing.call_count == 0

    view.show()
    settle(qtbot, view)

    assert listing.call_count == 1


def test_the_refresh_action_reads_again(qtbot: QtBot, view: FilesView, listing: Any) -> None:
    """What ``F5`` and the toolbar button both reach -- the same action object, so the two cannot drift.

    **Test steps:**

    * trigger the refresh action on a shown browser
    * verify a second listing ran
    """
    view.refresh_action.trigger()
    settle(qtbot, view)

    assert listing.call_count == 2


def test_re_showing_a_current_browser_reads_nothing(qtbot: QtBot, view: FilesView, listing: Any) -> None:
    """The other half of the deferral: a show only catches up a read that was *deferred*, so a dock
    tabbed away from and back -- which Qt reports as a hide and a show -- does not re-list the folder
    every time a reader glances at it.

    **Test steps:**

    * hide and re-show a browser whose read has already landed
    * verify no second listing ran
    """
    view.hide()
    view.show()
    settle(qtbot, view)

    assert listing.call_count == 1


def test_a_finished_checksum_run_is_not_needed_to_read_the_folder(view: FilesView) -> None:
    """The browser is built with no queue in this suite, so the one row that would enqueue a verify is
    simply inert -- the folder itself is a folder regardless (#266).

    **Test steps:**

    * verify the table drew the folder despite there being no checksum actions
    """
    assert "lesson01.mp4" in drawn(view)


# endregion


# region What it shows


def test_the_folder_is_listed_with_folders_first(view: FilesView) -> None:
    """Folders lead so the listing can be walked, and the resource's own name is above the table.

    **Test steps:**

    * read the root listing
    * verify the subfolder is drawn first and the path label names the resource's folder
    """
    assert drawn(view)[0] == "sub"
    assert view.path_label == DIRECTORY.name
    assert view.summary == "1 folder, 7 files"


def test_a_never_saved_document_has_no_folder_to_show(qtbot: QtBot) -> None:
    """A document bound to no path has nowhere to list, and saying so is better than an empty table.

    **Test steps:**

    * build a browser over a path-less model
    * verify it says there is no folder yet and offers no way up
    """
    view = FilesView(RehuDocumentModel(RehuDocument({}, None)))
    qtbot.addWidget(view)
    view.show()

    assert view.summary == NO_PATH_SUMMARY
    assert not view.up_action.isEnabled()


def test_an_away_mount_says_so_rather_than_drawing_an_empty_folder(
    qtbot: QtBot, model: RehuDocumentModel, listing: Any
) -> None:
    """*Empty* and *away* are not the same answer (#245) -- an empty table would say this resource's
    folder has nothing in it.

    **Test steps:**

    * make the listing answer unreachable
    * verify the summary names the condition and no rows were drawn
    """
    listing.side_effect = lambda _self, directory: DirectoryListing(directory, reachable=False)
    view = FilesView(model)
    qtbot.addWidget(view)
    view.show()
    settle(qtbot, view)

    assert view.summary == UNREACHABLE_SUMMARY
    assert drawn(view) == []


def test_refused_folders_are_explained_by_naming_the_record_that_owns_them(
    qtbot: QtBot, model: RehuDocumentModel, listing: Any
) -> None:
    """A greyed row with no reason given reads as a bug, so the line under the table names the record
    the folders belong to and the one thing to do about it -- the row right there (#254).

    Named from the listing rather than from whichever foreign record happens to be drawn first: a
    directory can hold a file-scoped neighbour as well, and it is not the one that owns the folders.

    **Test steps:**

    * answer a listing covered by a foreign ``info.rehu``, beside a file-scoped neighbour
    * verify the summary names the ``info.rehu``
    """
    listing.side_effect = lambda _self, directory: DirectoryListing(
        directory,
        entries=(
            DirectoryEntry("foo.rehu", FileKind.FOREIGN_RECORD, FileType.RECORD),
            DirectoryEntry("info.rehu", FileKind.FOREIGN_RECORD, FileType.RECORD),
            DirectoryEntry("sub", FileKind.DIRECTORY, FileType.DIRECTORY),
        ),
        foreign_directory_record="info.rehu",
    )
    view = FilesView(model)
    qtbot.addWidget(view)
    view.show()
    settle(qtbot, view)

    assert not enabled(view, "sub")
    assert "info.rehu" in view.summary


def test_nothing_is_explained_where_there_are_no_folders_to_refuse(
    qtbot: QtBot, model: RehuDocumentModel, listing: Any
) -> None:
    """The sentence exists to explain a greyed folder row; with no folder rows it would be noise about
    something the reader cannot see.

    **Test steps:**

    * answer a covered listing that holds no folders
    * verify the summary is the plain tally
    """
    listing.side_effect = lambda _self, directory: DirectoryListing(
        directory,
        entries=(DirectoryEntry("info.rehu", FileKind.FOREIGN_RECORD, FileType.RECORD),),
        foreign_directory_record="info.rehu",
    )
    view = FilesView(model)
    qtbot.addWidget(view)
    view.show()
    settle(qtbot, view)

    assert view.summary == "0 folders, 1 file"


def test_a_record_this_build_cannot_read_is_said_rather_than_hidden(
    qtbot: QtBot, model: RehuDocumentModel, mocker: MockerFixture
) -> None:
    """The folder is still the folder, so it is still listed -- with every checksum cell empty and the
    reason named, which is honest: this build knows nothing about any of these files.

    **Test steps:**

    * make the record read raise
    * verify the rows are drawn and the summary names the failure
    """
    mocker.patch(
        "rehuco_agent.documents.files_rows.load_checksum_record",
        side_effect=ChecksumRecordError("version 9 is newer than this build"),
    )
    view = FilesView(model)
    qtbot.addWidget(view)
    view.show()
    settle(qtbot, view)

    assert "lesson01.mp4" in drawn(view)
    assert "newer than this build" in view.summary


def test_a_read_landing_after_the_document_lost_its_path_says_nowhere(
    qtbot: QtBot, view: FilesView, model: RehuDocumentModel, listing: Any
) -> None:
    """The one window in which a landed read can be about a folder the document no longer has: the
    listing was started while there was a path and lands after there is not. The header is written from
    the record's own folder, so with no record there is no relative place to name -- and naming the last
    one would be a heading pointing at a resource this document is no longer.

    **Test steps:**

    * hold the listing and start a read
    * clear the document's path while that read is still out
    * release it, and verify the header names nowhere rather than the folder it was about
    """
    from threading import Event  # pylint: disable=import-outside-toplevel

    release = Event()
    quick = listing.side_effect

    def held(_self: object, directory: Path) -> DirectoryListing:
        release.wait(timeout=5)
        return quick(_self, directory)

    listing.side_effect = held
    view.refresh_action.trigger()

    model.path = None

    release.set()
    qtbot.waitUntil(lambda: view.path_label == "", timeout=TIMEOUT)

    assert view.path_label == ""


def test_the_rows_this_resource_cannot_speak_for_are_refused(view: FilesView) -> None:
    """The document already on screen, and the two kinds belonging to a resource this one cannot speak
    for -- the refusals `test_files_rows` establishes, reaching the view's own indexes.

    **Test steps:**

    * verify the own record and the neighbour's screenshot are disabled while the rest are not
    """
    assert not enabled(view, "info.rehu")
    assert not enabled(view, "other00.jpg")
    assert enabled(view, "other.rehu")
    assert enabled(view, "info00.jpg")
    assert enabled(view, "lesson01.mp4")


# endregion


# region Where it will and will not go


def test_a_double_click_walks_into_a_subfolder_and_back_out(qtbot: QtBot, view: FilesView) -> None:
    """The two halves of navigating: a folder row goes in, and the ``..`` row it grows comes back.

    **Test steps:**

    * activate the subfolder row, and verify the browser moved and offers a way up
    * activate the parent row, and verify it is back at the root
    """
    view.activate(row_of(view, "sub"))
    settle(qtbot, view)

    assert view.directory == SUB
    assert view.path_label == f"{DIRECTORY.name}/sub"
    assert view.up_action.isEnabled()
    assert drawn(view) == [PARENT_ROW_NAME, "deeper.mp4"]

    view.activate(row_of(view, PARENT_ROW_NAME))
    settle(qtbot, view)

    assert view.directory == DIRECTORY
    assert not view.up_action.isEnabled()


def test_the_root_refuses_to_go_above_itself(qtbot: QtBot, view: FilesView) -> None:
    """The browser is confined to the resource's own folder: going up would leave the resource, and a
    general file manager is not what this is.

    **Test steps:**

    * verify the root has no parent row and a disabled up action
    * trigger the up action anyway, and verify the browser has not moved
    """
    assert PARENT_ROW_NAME not in drawn(view)
    assert not view.up_action.isEnabled()

    view.up_action.trigger()
    settle(qtbot, view)

    assert view.directory == DIRECTORY


def test_home_goes_back_to_the_resources_own_folder(qtbot: QtBot, view: FilesView) -> None:
    """The longest jump the browser offers, and the only one that is a single click from any depth.

    **Test steps:**

    * walk into the subfolder
    * trigger Home
    * verify the browser is at the resource's own folder and has re-read it
    """
    view.activate(row_of(view, "sub"))
    settle(qtbot, view)
    assert view.directory == SUB

    view.home_action.trigger()
    settle(qtbot, view)

    assert view.directory == DIRECTORY
    assert view.path_label == DIRECTORY.name
    assert "lesson01.mp4" in drawn(view)


def test_home_and_up_are_offered_together(qtbot: QtBot, view: FilesView) -> None:
    """The pair takes one condition: both lead back towards the resource's own folder, so at the root
    neither has anywhere to go.

    **Test steps:**

    * verify both are disabled at the root
    * walk into the subfolder and verify both are enabled
    """
    assert not view.home_action.isEnabled()
    assert not view.up_action.isEnabled()

    view.activate(row_of(view, "sub"))
    settle(qtbot, view)

    assert view.home_action.isEnabled()
    assert view.up_action.isEnabled()


def test_home_and_up_follow_the_target_before_the_read_lands(qtbot: QtBot, view: FilesView, listing: Any) -> None:
    """Where the browser is pointed is known the moment it is pointed there, so the pair changes state
    then -- not when the listing arrives. On a share that takes seconds to answer, a Home that stayed
    live until then invited a second click that only re-read the same folder.

    **Test steps:**

    * hold the listing so no read can land
    * walk into the subfolder and verify both are enabled at once
    * trigger Home and verify both are disabled at once, the read still held
    * release the read and verify nothing about the pair changes when it lands
    """
    from threading import Event  # pylint: disable=import-outside-toplevel

    release = Event()
    quick = listing.side_effect

    def held(_self: object, directory: Path) -> DirectoryListing:
        release.wait(timeout=5)
        return quick(_self, directory)

    listing.side_effect = held

    view.activate(row_of(view, "sub"))
    assert view.home_action.isEnabled()
    assert view.up_action.isEnabled()

    view.home_action.trigger()
    assert not view.home_action.isEnabled()
    assert not view.up_action.isEnabled()

    release.set()
    settle(qtbot, view)

    assert view.directory == DIRECTORY
    assert not view.home_action.isEnabled()
    assert not view.up_action.isEnabled()


def test_home_at_the_root_moves_nothing(qtbot: QtBot, view: FilesView) -> None:
    """The action is disabled there, so this only guards a stale trigger -- and a re-read of the folder
    already shown is not a move.

    **Test steps:**

    * trigger Home at the root
    * verify the browser has not moved
    """
    view.home_action.trigger()
    settle(qtbot, view)

    assert view.directory == DIRECTORY


def test_up_at_the_root_moves_nothing(qtbot: QtBot, view: FilesView) -> None:
    """Home's twin guard. The action is disabled at the root, so the only trigger that can arrive there
    is a stale one -- a click already in flight when the read that landed at the root disabled it -- and
    walking out of the resource's own folder is the one move this browser never makes.

    **Test steps:**

    * deliver a trigger to the up action at the root, past its enablement
    * verify the browser has not moved
    """
    view.up_action.triggered.emit()
    settle(qtbot, view)

    assert view.directory == DIRECTORY


def test_a_document_with_no_folder_offers_neither_jump(qtbot: QtBot) -> None:
    """There is nowhere to go home *to*, which is the second half of the pair's one condition.

    **Test steps:**

    * build a browser over a path-less model
    * verify Home and Up are both disabled
    """
    view = FilesView(RehuDocumentModel(RehuDocument({}, None)))
    qtbot.addWidget(view)
    view.show()

    assert not view.home_action.isEnabled()
    assert not view.up_action.isEnabled()


def test_the_up_action_is_the_parent_rows_act_on_a_button(qtbot: QtBot, view: FilesView) -> None:
    """Two affordances, one move -- a reader who has walked in looks for either.

    **Test steps:**

    * walk into the subfolder and use the toolbar action to come back
    """
    view.activate(row_of(view, "sub"))
    settle(qtbot, view)

    view.up_action.trigger()
    settle(qtbot, view)

    assert view.directory == DIRECTORY


def test_the_document_moving_re_scopes_the_browser(qtbot: QtBot, view: FilesView, model: RehuDocumentModel) -> None:
    """A rename or a convert moves the folder this is a view *of* (#52's landmine, for a folder), so a
    subfolder of the old one is not somewhere to stay.

    **Test steps:**

    * walk into the subfolder
    * move the document's path
    * verify the browser is back at the new resource's own folder
    """
    view.activate(row_of(view, "sub"))
    settle(qtbot, view)

    moved = Path("/fake/library/renamed") / "info.rehu"
    model.path = moved
    settle(qtbot, view)

    assert view.directory == moved.parent


# endregion


# region What a double-click does


def test_another_resources_record_is_reported_rather_than_opened(qtbot: QtBot, view: FilesView) -> None:
    """Opening a resource is the window's act -- it resolves, reveals and remembers -- so the browser
    reports and the relay carries it up (#266).

    **Test steps:**

    * activate the neighbour's record
    * verify its path was reported
    """
    with qtbot.waitSignal(view.record_activated, timeout=TIMEOUT) as reported:
        view.activate(row_of(view, "other.rehu"))

    assert reported.args == [DIRECTORY / "other.rehu"]


def test_an_image_opens_against_every_image_in_the_folder(qtbot: QtBot, view: FilesView) -> None:
    """**Curation is ignored on purpose**: this is a view of the folder, so a screenshot someone curated
    out -- and a neighbour's -- are both here and both worth looking at from here
    ([[data-model#image-meanings]]).

    **Test steps:**

    * activate one of the resource's screenshots
    * verify the whole folder's image set was reported, the neighbour's included, starting at the
      clicked one
    """
    with qtbot.waitSignal(view.images_activated, timeout=TIMEOUT) as reported:
        view.activate(row_of(view, "info00.jpg"))

    images, clicked = reported.args or (None, None)
    assert clicked == DIRECTORY / "info00.jpg"
    assert images == [DIRECTORY / "info00.jpg", DIRECTORY / "info01.jpg", DIRECTORY / "other00.jpg"]


def test_the_checksum_record_enqueues_this_documents_verify(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The one row that acts on the document rather than reporting: it calls the *Verify All* the
    document's own toolbar carries, so there is one definition of what that checks.

    **Test steps:**

    * build a browser handed a verify
    * activate the checksum record's row
    * verify the call was made
    """
    verified: list[bool] = []
    view = FilesView(model, verify=lambda: verified.append(True))
    qtbot.addWidget(view)
    view.show()
    settle(qtbot, view)

    view.activate(row_of(view, "info.checksum"))

    assert verified == [True]


def test_a_document_with_no_queue_leaves_the_checksum_row_inert(qtbot: QtBot, view: FilesView) -> None:
    """A widget built with no queue has no verify to offer, and the row does nothing rather than
    raising -- the same reason the document's own checksum toolbar pair is absent there.

    **Test steps:**

    * activate the checksum record's row on a browser built with no verify
    * verify nothing happened and the browser did not move
    """
    view.activate(row_of(view, "info.checksum"))
    settle(qtbot, view)

    assert view.directory == DIRECTORY


def test_anything_else_goes_to_the_systems_default_handler(view: FilesView, mocker: MockerFixture) -> None:
    """The only sensible thing to do with a video, and the one route that does not involve this app
    pretending to open it.

    **Test steps:**

    * activate a content row that is not an image
    * verify the file's URL was handed to the desktop services
    """
    opened = mocker.patch.object(QDesktopServices, "openUrl")

    view.activate(row_of(view, "lesson01.mp4"))

    # compared as a Path, not as text: QUrl spells a local file with forward slashes on every platform
    url = opened.call_args.args[0]
    assert isinstance(url, QUrl)
    # pylint cannot see past the patched signal to the QUrl the isinstance above has just established
    assert Path(url.toLocalFile()) == DIRECTORY / "lesson01.mp4"  # pylint: disable=no-member


def test_a_disabled_row_cannot_be_activated(view: FilesView, mocker: MockerFixture) -> None:
    """The refusal lives in the model's flags rather than as a check in each activation branch, so
    there is no path by which another resource's screenshot opens from here.

    **Test steps:**

    * activate the neighbour's screenshot row and the own record's row
    * verify neither reported anything and nothing was handed to the system
    """
    opened = mocker.patch.object(QDesktopServices, "openUrl")
    reported: list[object] = []
    view.record_activated.connect(reported.append)
    view.images_activated.connect(lambda *args: reported.append(args))

    view.activate(row_of(view, "other00.jpg"))
    view.activate(row_of(view, "info.rehu"))

    assert not reported
    opened.assert_not_called()


def test_the_row_behind_every_index_is_reachable(view: FilesView) -> None:
    """What the delegate reads to pick a glyph, and what an activation dispatches on -- served under its
    own role so neither has to map an index back to ask what a row is.

    **Test steps:**

    * read the role off a drawn index
    * verify it is the row itself
    """
    row = view.proxy.index(row_of(view, "lesson01.mp4"), NAME_COLUMN).data(FilesTableModel.ROW_ROLE)

    assert isinstance(row, FileRow)
    assert row.path == DIRECTORY / "lesson01.mp4"


# endregion
