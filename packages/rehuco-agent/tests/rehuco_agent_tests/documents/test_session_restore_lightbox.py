"""Tests for a maximized lightbox across a restart, each of the four sets it opens against
([[plugins#session-restore]], #576).

The documents and their strips are ``test_document_widget``'s; what is tested is what is remembered, and when a
remembered view opens.
"""

# the sub-docks' sets are fed through their name-mangled members, as test_document_widget does
# pylint: disable=protected-access

import json
from pathlib import Path
from typing import Final

from PySide6.QtGui import QImage
from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.content_images.content_images_model import ArchiveImageSource
from rehuco_agent.documents.document_widget import DocumentWidget
from rehuco_agent.documents.latest_runner import LatestRunner
from rehuco_agent.documents.maximized_restore import folder_images, relative_key, resolve_key
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields.widgets.curating_image_lightbox import CuratingImageLightbox
from rehuco_agent.fields.widgets.image_lightbox import ImageLightbox
from rehuco_agent.fields.widgets.overlay_surface import OverlayMode
from rehuco_agent.settings.image_viewer_settings import shared_image_viewer_settings
from rehuco_agent.settings.maximized_view import (
    CONTENT_SET,
    CURATED_SET,
    CURATING_SET,
    FOLDER_SET,
    LIGHTBOX_KIND,
    PLAYER_KIND,
    MaximizedView,
)
from rehuco_core import ContentImageEntry, RehuDocument

from .test_document_widget import (  # noqa: F401  # pylint: disable=unused-import
    SCREENSHOT_DIRECTORY,
    SCREENSHOTS,
    ScreenshotFolder,
    activate_screenshot,
    content_images_view,
    curating_editor,
    fixture_refimages_model,
    fixture_refimages_widget,
    loadable_lightbox_image,
    open_curating,
)

TIMEOUT: Final = 5000
FOLDER: Final = SCREENSHOT_DIRECTORY.absolute()
RECORD: Final = FOLDER / "info.rehu"
IMAGES: Final = [FOLDER / path.name for path in SCREENSHOTS]
"""The screenshots, in the folder of a record with a path: what a remembered key is relative to."""


@fixture(name="widget")
def fixture_widget(qtbot: QtBot) -> DocumentWidget:
    """A document in the folder :data:`IMAGES` are in.

    :param qtbot: pytest-qt fixture.
    :returns: the document's widget.
    """
    widget = DocumentWidget(RehuDocumentModel(RehuDocument({"type": "Tutorial"}, RECORD)))
    qtbot.addWidget(widget)
    return widget


def curated(widget: DocumentWidget, images: list[Path]) -> None:
    """Say what the document's curated set is, as its strip does.

    :param widget: the document.
    :param images: the set.
    """
    widget.sub_docks._DocumentSubDocks__on_curated_images_changed(images)  # type: ignore[attr-defined]


def open_viewer(widget: DocumentWidget) -> ImageLightbox | None:
    """The document's open lightbox.

    :param widget: the document.
    :returns: it, or ``None``.
    """
    return widget.sub_docks._DocumentSubDocks__image_viewer  # type: ignore[attr-defined]


def curated_view(key: str = "info01.jpg", *, info: bool = True, strip: bool = False) -> MaximizedView:
    """A session's view over the curated set.

    :param key: its image, relative to the record's folder.
    :param info: whether its info was shown.
    :param strip: whether its row was shown.
    :returns: the view.
    """
    return MaximizedView(LIGHTBOX_KIND, key, OverlayMode.DOCUMENT_OVERLAY.value, CURATED_SET, info, strip)


def test_capturing_a_lightbox_says_where_it_was_and_closes_it(widget: DocumentWidget, mocker: MockerFixture) -> None:
    """What is remembered is the image, the set, the surface and what it showed; the docks are then measured with it
    gone.

    **Test steps:**

    * open a screenshot, and hide its row and show its info
    * capture, and verify each field
    * verify the viewer closed
    """
    loadable_lightbox_image(mocker)
    curated(widget, IMAGES)
    activate_screenshot(widget, IMAGES[1])
    viewer = open_viewer(widget)
    assert viewer is not None
    viewer.set_strip_visible(False)
    viewer.set_info_visible(True)

    view = widget.capture_maximized()

    assert view == MaximizedView(LIGHTBOX_KIND, "info01.jpg", viewer.mode.value, CURATED_SET, True, False)
    assert open_viewer(widget) is None


def test_a_curated_lightbox_comes_back_on_its_image_surface_info_and_row(
    widget: DocumentWidget, mocker: MockerFixture
) -> None:
    """The view opens over the set as it is, taking its info and row over the settings'.

    **Test steps:**

    * set the settings to the opposite of the view, and restore it over a known set
    * verify a read-only viewer is on its image, with its info, its row and its surface, and that it was reported
    """
    loadable_lightbox_image(mocker)
    curated(widget, IMAGES)
    settings = shared_image_viewer_settings()
    settings.lightbox_info_visible = False
    settings.strip_visible = True
    reported: list[object] = []
    widget.maximized_restored.connect(reported.append)

    widget.restore_maximized(curated_view())

    viewer = open_viewer(widget)
    assert viewer is not None
    assert type(viewer) is ImageLightbox  # pylint: disable=unidiomatic-typecheck
    assert viewer.current_index == 1
    assert viewer.info_visible is True
    assert viewer.strip_visible is False
    assert viewer.mode is OverlayMode.DOCUMENT_OVERLAY
    assert reported == [viewer]


def test_a_lightbox_waits_for_its_set_and_a_key_no_longer_in_it_restores_nothing(
    widget: DocumentWidget, mocker: MockerFixture
) -> None:
    """An empty set says nothing yet; a set without the image says it is gone.

    **Test steps:**

    * restore a view with no screenshots known, and verify nothing opens and it is still what is remembered
    * say the set is there without its image, and verify nothing opens and nothing is remembered
    """
    loadable_lightbox_image(mocker)
    curated(widget, [])
    widget.restore_maximized(curated_view())

    assert open_viewer(widget) is None
    assert widget.capture_maximized() == curated_view()

    curated(widget, [IMAGES[0]])

    assert open_viewer(widget) is None
    assert widget.capture_maximized() is None


def test_a_lightbox_opens_when_its_set_arrives(widget: DocumentWidget, mocker: MockerFixture) -> None:
    """Whichever comes first, the view or the set, the view opens.

    **Test steps:**

    * restore a view with no screenshots known
    * say the set is there, and verify the viewer opens on its image
    """
    loadable_lightbox_image(mocker)
    curated(widget, [])
    widget.restore_maximized(curated_view())

    curated(widget, IMAGES)

    viewer = open_viewer(widget)
    assert viewer is not None
    assert viewer.current_index == 1


def test_opening_a_lightbox_overtakes_the_one_remembered(widget: DocumentWidget, mocker: MockerFixture) -> None:
    """The reader's own screenshot wins, and the remembered one does not open over it later.

    **Test steps:**

    * restore a view with no screenshots known
    * open another screenshot, then say the set is there
    * verify the viewer stays on the reader's
    """
    loadable_lightbox_image(mocker)
    curated(widget, [])
    widget.restore_maximized(curated_view())

    activate_screenshot(widget, IMAGES[0])
    viewer = open_viewer(widget)
    curated(widget, [IMAGES[1]])

    assert open_viewer(widget) is viewer


def test_a_curating_lightbox_comes_back_with_its_actions(widget: DocumentWidget, mocker: MockerFixture) -> None:
    """The lightbox of the images editor comes back as that one, its requests going to the editor.

    **Test steps:**

    * give the editor rows, open a curating viewer on the second and capture it
    * restore the view
    * verify it is a curating viewer on that row, again connected to the editor
    """
    selector = curating_editor(widget, mocker, ScreenshotFolder(["info00.jpg", "info01.jpg"], ["cover.jpg"]), [])
    # the helper's rows are in a folder of its own, not the record's
    mocker.patch.object(widget.sub_docks, "_DocumentSubDocks__record_folder", return_value=SCREENSHOT_DIRECTORY)
    open_curating(selector, widget, 1)

    view = widget.capture_maximized()

    assert view is not None
    assert (view.source, view.key) == (CURATING_SET, "info01.jpg")
    assert open_viewer(widget) is None

    widget.restore_maximized(view)

    restored = open_viewer(widget)
    assert isinstance(restored, CuratingImageLightbox)
    assert restored.current_index == 1
    assert widget.sub_docks._DocumentSubDocks__curation_selector is selector  # type: ignore[attr-defined]


def test_a_content_lightbox_comes_back_on_its_member(refimages_widget: DocumentWidget, mocker: MockerFixture) -> None:
    """An archive member is named by its tier-0 key, and waits for the pack to be enumerated.

    **Test steps:**

    * open a content image and capture it, and verify the set and that the key reads back
    * empty the pack, and restore the view, and verify nothing opens
    * enumerate the pack, and verify the viewer is on that member
    """
    entries = [ContentImageEntry(Path("/fake/refimages/pack.zip"), f"{index}.png", 0, 0) for index in range(3)]
    sub_docks = refimages_widget.sub_docks
    content_model = sub_docks._DocumentSubDocks__content_images_model  # type: ignore[attr-defined]
    content_model.set_entries(entries, Path("/fake/refimages"))
    mocker.patch.object(ArchiveImageSource, "load", side_effect=lambda *_: QImage(20, 10, QImage.Format.Format_RGB32))
    content_images_view(refimages_widget).image_activated.emit(2)

    view = refimages_widget.capture_maximized()

    assert view is not None
    assert view.source == CONTENT_SET
    assert tuple(json.loads(view.key)) == entries[2].key

    content_model.set_entries([], Path("/fake/refimages"))
    refimages_widget.restore_maximized(view)
    assert open_viewer(refimages_widget) is None

    content_model.set_entries(entries, Path("/fake/refimages"))

    viewer = open_viewer(refimages_widget)
    assert viewer is not None
    assert viewer.current_key == entries[2].key


@mark.usefixtures("real_path_stat")
def test_a_folder_lightbox_lists_its_folder_itself(qtbot: QtBot, tmp_path: Path, mocker: MockerFixture) -> None:
    """A hidden Files dock has not read the folder, so the view asks for it, off the GUI thread, and curation plays no
    part.

    **Test steps:**

    * build a document in a folder holding images in a subfolder, and restore a view of one of them
    * verify the viewer opens over that folder's images, by name, on that image
    """
    folder = tmp_path / "shots"
    folder.mkdir()
    for name in ("b.png", "A.png", "c.txt"):
        (folder / name).write_bytes(b"x")
    loadable_lightbox_image(mocker)
    widget = DocumentWidget(RehuDocumentModel(RehuDocument({"type": "Tutorial"}, tmp_path / "info.rehu")))
    qtbot.addWidget(widget)

    widget.restore_maximized(
        MaximizedView(LIGHTBOX_KIND, "shots/b.png", OverlayMode.DOCUMENT_OVERLAY.value, FOLDER_SET)
    )

    qtbot.waitUntil(lambda: open_viewer(widget) is not None, timeout=TIMEOUT)
    viewer = open_viewer(widget)
    assert viewer is not None
    assert [viewer.source.key(index) for index in range(len(viewer.source))] == [folder / "A.png", folder / "b.png"]
    assert viewer.current_index == 1
    view = widget.capture_maximized()
    assert view is not None
    assert (view.key, view.source) == ("shots/b.png", FOLDER_SET)


def test_a_view_that_would_leave_the_folder_restores_nothing(tmp_path: Path) -> None:
    """A hand-damaged key stays inside the record's folder.

    **Test steps:**

    * resolve keys that climb out or name another place
    * verify none resolves, and that a plain one does and round-trips
    """
    for key in (
        "../x.png",
        "/etc/x.png",
        "C:/x.png",
        ".." + chr(92) + "x.png",
        chr(92) * 2 + "srv" + chr(92) + "x.png",
    ):
        assert resolve_key(key, tmp_path) is None
    assert resolve_key("a/b.png", None) is None
    assert resolve_key("a/b.png", tmp_path) == tmp_path / "a" / "b.png"
    assert relative_key(tmp_path / "a" / "b.png", tmp_path) == "a/b.png"
    assert relative_key(tmp_path.parent / "b.png", tmp_path) is None
    assert relative_key(tmp_path / "b.png", None) is None


@mark.usefixtures("real_path_stat")
def test_listing_a_folder_keeps_only_its_images_by_name(tmp_path: Path) -> None:
    """**Test steps:**

    * make a folder of images, another file and a folder named as an image
    * verify its images are listed by name, whatever their case
    """
    for name in ("b.png", "A.JPG", "note.txt"):
        (tmp_path / name).write_bytes(b"x")
    (tmp_path / "folder.png").mkdir()

    assert folder_images(tmp_path) == [tmp_path / "A.JPG", tmp_path / "b.png"]


def test_an_image_outside_the_records_folder_is_not_remembered(widget: DocumentWidget, mocker: MockerFixture) -> None:
    """A key is relative to the record's folder, so an image elsewhere has none.

    **Test steps:**

    * open a screenshot outside the record's folder
    * capture, and verify nothing is remembered and the viewer closed
    """
    loadable_lightbox_image(mocker)
    activate_screenshot(widget, Path("/elsewhere/info00.jpg"))

    assert widget.capture_maximized() is None
    assert open_viewer(widget) is None


def test_a_view_of_another_record_is_let_go(widget: DocumentWidget, mocker: MockerFixture) -> None:
    """A preview moving on before the view opened must not open the last record's picture over the next one.

    **Test steps:**

    * restore a view waiting for its set, then make the document another record
    * say the set is there, and verify nothing opens and nothing is remembered
    """
    loadable_lightbox_image(mocker)
    curated(widget, [])
    widget.restore_maximized(curated_view())
    mocker.patch.object(type(widget.model), "key", new_callable=mocker.PropertyMock, return_value=None)

    curated(widget, IMAGES)

    assert open_viewer(widget) is None
    assert widget.capture_maximized() is None


def test_a_curating_view_whose_row_is_gone_restores_nothing(widget: DocumentWidget, mocker: MockerFixture) -> None:
    """**Test steps:**

    * give the editor rows without the view's image, and restore the view
    * verify nothing opens and nothing is remembered
    """
    curating_editor(widget, mocker, ScreenshotFolder(["info00.jpg"]), [])
    mocker.patch.object(widget.sub_docks, "_DocumentSubDocks__record_folder", return_value=SCREENSHOT_DIRECTORY)

    widget.restore_maximized(MaximizedView(LIGHTBOX_KIND, "gone.jpg", OverlayMode.DOCUMENT_OVERLAY.value, CURATING_SET))

    assert open_viewer(widget) is None
    assert widget.capture_maximized() is None


def test_a_content_view_on_a_document_with_no_content_images_restores_nothing(widget: DocumentWidget) -> None:
    """A record whose type changed since has no dock to open it from.

    **Test steps:**

    * restore a content view on a tutorial
    * verify nothing opens and nothing is remembered
    """
    widget.restore_maximized(MaximizedView(LIGHTBOX_KIND, "[]", OverlayMode.DOCUMENT_OVERLAY.value, CONTENT_SET))

    assert open_viewer(widget) is None
    assert widget.capture_maximized() is None


@mark.parametrize("key", ["not json", "3", '["gone.zip", "x.png", 0, 0]'])
def test_a_content_key_not_in_the_pack_restores_nothing(refimages_widget: DocumentWidget, key: str) -> None:
    """A member gone since, and a key damaged by hand, cost only the view.

    **Test steps:**

    * enumerate a pack, and restore a view of the key
    * verify nothing opens and nothing is remembered
    """
    entries = [ContentImageEntry(Path("/fake/refimages/pack.zip"), "a.png", 0, 0)]
    content_model = refimages_widget.sub_docks._DocumentSubDocks__content_images_model  # type: ignore[attr-defined]
    content_model.set_entries(entries, Path("/fake/refimages"))

    refimages_widget.restore_maximized(
        MaximizedView(LIGHTBOX_KIND, key, OverlayMode.DOCUMENT_OVERLAY.value, CONTENT_SET)
    )

    assert open_viewer(refimages_widget) is None
    assert refimages_widget.capture_maximized() is None


def test_a_content_view_reads_the_pack_itself_when_its_dock_is_closed_and_only_once(
    refimages_widget: DocumentWidget, mocker: MockerFixture
) -> None:
    """A closed dock reads nothing, and the view cannot wait for it; an empty answer is not asked for again and again.

    **Test steps:**

    * spy on the pack's reading, with its dock closed and the pack empty, and restore a content view
    * say the pack is still empty
    * verify the pack was read once
    """
    model = refimages_widget.sub_docks._DocumentSubDocks__content_images_model  # type: ignore[attr-defined]
    refresh = mocker.patch.object(model, "refresh")

    refimages_widget.restore_maximized(
        MaximizedView(LIGHTBOX_KIND, "[]", OverlayMode.DOCUMENT_OVERLAY.value, CONTENT_SET)
    )
    model.set_entries([], None)

    refresh.assert_called_once()


@mark.usefixtures("real_path_stat")
def test_a_folder_view_asks_for_its_folder_once(qtbot: QtBot, tmp_path: Path, mocker: MockerFixture) -> None:
    """Any set changing asks the held view again, which has already asked.

    **Test steps:**

    * restore a folder view, and say the curated set changed while its listing is out
    * verify the folder was listed once, and the view opened
    """
    (tmp_path / "b.png").write_bytes(b"x")
    loadable_lightbox_image(mocker)
    start = mocker.spy(LatestRunner, "start")
    widget = DocumentWidget(RehuDocumentModel(RehuDocument({"type": "Tutorial"}, tmp_path / "info.rehu")))
    qtbot.addWidget(widget)
    start.reset_mock()

    widget.restore_maximized(MaximizedView(LIGHTBOX_KIND, "b.png", OverlayMode.DOCUMENT_OVERLAY.value, FOLDER_SET))
    curated(widget, [])

    assert start.call_count == 1
    qtbot.waitUntil(lambda: open_viewer(widget) is not None, timeout=TIMEOUT)


@mark.usefixtures("real_path_stat")
def test_a_folder_gone_or_out_of_reach_restores_nothing(qtbot: QtBot, tmp_path: Path) -> None:
    """A folder that cannot be listed costs only the view, and a key that would leave the record's asks for nothing.

    **Test steps:**

    * restore a view of a folder that does not exist, and wait for its answer
    * restore one climbing out, and verify neither opened and nothing is remembered
    """
    widget = DocumentWidget(RehuDocumentModel(RehuDocument({"type": "Tutorial"}, tmp_path / "info.rehu")))
    qtbot.addWidget(widget)
    mode = OverlayMode.DOCUMENT_OVERLAY.value

    widget.restore_maximized(MaximizedView(LIGHTBOX_KIND, "gone/b.png", mode, FOLDER_SET))
    held = widget.sub_docks
    qtbot.waitUntil(lambda: held._DocumentSubDocks__held_view is None, timeout=TIMEOUT)  # type: ignore[attr-defined]

    widget.restore_maximized(MaximizedView(LIGHTBOX_KIND, "../b.png", mode, FOLDER_SET))

    assert open_viewer(widget) is None
    assert widget.capture_maximized() is None


@mark.usefixtures("real_path_stat")
def test_a_folder_answer_arriving_after_the_reader_moved_on_is_dropped(
    qtbot: QtBot, tmp_path: Path, mocker: MockerFixture
) -> None:
    """The reader's own screenshot overtakes a listing still out.

    **Test steps:**

    * restore a folder view, and open a screenshot before its listing answers
    * let the answer land, and verify the viewer is still the reader's
    """
    (tmp_path / "b.png").write_bytes(b"x")
    loadable_lightbox_image(mocker)
    widget = DocumentWidget(RehuDocumentModel(RehuDocument({"type": "Tutorial"}, tmp_path / "info.rehu")))
    qtbot.addWidget(widget)
    lister = widget.sub_docks._DocumentSubDocks__held_folder_lister  # type: ignore[attr-defined]
    answered: list[object] = []
    lister.read.connect(lambda *args: answered.append(args))
    widget.restore_maximized(MaximizedView(LIGHTBOX_KIND, "b.png", OverlayMode.DOCUMENT_OVERLAY.value, FOLDER_SET))

    activate_screenshot(widget, tmp_path / "a.png")
    viewer = open_viewer(widget)
    qtbot.waitUntil(lambda: bool(answered), timeout=TIMEOUT)

    assert open_viewer(widget) is viewer


def test_a_player_view_on_a_document_with_no_player_restores_nothing(refimages_widget: DocumentWidget) -> None:
    """**Test steps:**

    * restore a player view on a reference pack
    * verify nothing is remembered
    """
    refimages_widget.restore_maximized(MaximizedView(PLAYER_KIND, "a.mp4", OverlayMode.DOCUMENT_OVERLAY.value))

    assert refimages_widget.capture_maximized() is None


def test_a_curating_view_waits_for_the_editor_to_have_its_rows(widget: DocumentWidget, mocker: MockerFixture) -> None:
    """The editor's rows can arrive after the view: it is the set of a view held, like any other.

    **Test steps:**

    * restore a curating view over an editor with no rows, and verify nothing opens and it is still remembered
    * give the editor rows, and verify the view opens on its image
    """
    folder = ScreenshotFolder([])
    selector = curating_editor(widget, mocker, folder, [])
    mocker.patch.object(widget.sub_docks, "_DocumentSubDocks__record_folder", return_value=SCREENSHOT_DIRECTORY)
    view = MaximizedView(LIGHTBOX_KIND, "info01.jpg", OverlayMode.DOCUMENT_OVERLAY.value, CURATING_SET)

    widget.restore_maximized(view)

    assert open_viewer(widget) is None

    folder.names.extend(["info00.jpg", "info01.jpg"])
    folder.ids.update({"info00.jpg": 0, "info01.jpg": 1})
    selector.set_screenshots(folder.screenshots(), [])

    viewer = open_viewer(widget)
    assert isinstance(viewer, CuratingImageLightbox)
    assert viewer.current_index == 1


def test_tearing_a_document_down_lets_go_of_a_view_still_waiting(
    qtbot: QtBot, tmp_path: Path, mocker: MockerFixture
) -> None:
    """A folder's answer arriving after the sub-docks were torn down opens nothing over the document shown since.

    **Test steps:**

    * hold a folder view whose listing is out, and tear the sub-docks down
    * verify the listing was let go of, and nothing is held
    """
    discard = mocker.spy(LatestRunner, "discard")
    widget = DocumentWidget(RehuDocumentModel(RehuDocument({"type": "Tutorial"}, tmp_path / "info.rehu")))
    qtbot.addWidget(widget)
    sub_docks = widget.sub_docks
    sub_docks.restore_maximized(MaximizedView(LIGHTBOX_KIND, "b.png", OverlayMode.DOCUMENT_OVERLAY.value, FOLDER_SET))
    discard.reset_mock()

    sub_docks.teardown()

    assert sub_docks._DocumentSubDocks__held_view is None  # type: ignore[attr-defined]
    assert discard.call_count >= 1
    sub_docks.setParent(None)
