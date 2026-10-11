"""Tests for what the Images dock does with a drop of its own record's screenshots (#395).

Dragging a screenshot out of a record's strip, editor or lightbox and back onto its own Images dock would add a
numbered copy of an image the set already holds. The dock declines that, and acquires everything else -- an image
out of the pack, another record's screenshot even from the same folder, a file from anywhere -- as before. The dock,
its drop helpers are :mod:`test_document_widget`' own, imported by name.
"""

import os
from pathlib import Path

from PySide6.QtCore import QByteArray, QMimeData, QPoint, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent
from PySide6.QtWidgets import QApplication
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.document_widget import DocumentWidget
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields.widgets.image_export import ORIGINAL_FILE_MIME
from rehuco_core import RehuDocument

from .test_document_widget import (
    EDITOR_IMAGES_TAB,
    LOG_DOCUMENT_PATH,
    drag_onto_images_dock,
    image_bytes_mime_data,
    images_dock,
    local_file_mime_data,
)

FOLDER = LOG_DOCUMENT_PATH.parent
OWN = FOLDER / "logged-resource01.jpg"
"""One of the record's own screenshots, as its scanner lists them."""

OTHER_RECORDS = FOLDER / "other-record01.jpg"
"""A screenshot of another record, in the same folder."""

STAGED = Path("/fake/cache/staged/rehu-id__a.jpg")


@fixture(name="saved_model")
def fixture_saved_model() -> RehuDocumentModel:
    """A view-model bound to a path, so the record has a folder its screenshots can sit in."""
    return RehuDocumentModel(
        RehuDocument({"type": "Tutorial", "sources": [{"title": "Foo", "primary": True}]}, LOG_DOCUMENT_PATH)
    )


@fixture(name="saved_widget")
def fixture_saved_widget(qtbot: QtBot, saved_model: RehuDocumentModel) -> DocumentWidget:
    """A widget over that model, registered for teardown."""
    widget = DocumentWidget(saved_model)
    qtbot.addWidget(widget)
    return widget


def list_screenshots(saved_model: RehuDocumentModel, mocker: MockerFixture, *files: Path) -> None:
    """Make the record's scanner list ``files`` as its screenshots.

    :param saved_model: the document's model.
    :param mocker: pytest-mock fixture.
    :param files: the screenshots.
    """
    assert saved_model.image_scanner is not None
    mocker.patch.object(saved_model.image_scanner, "files", return_value=list(files))


def our_drag(original: Path | None, *, with_pixels: bool = False) -> QMimeData:
    """What a drag out of this app carries: a staged copy's URL, the original's path, and optionally the pixels.

    :param original: the file the image really is; ``None`` for an image with none (an archive member).
    :param with_pixels: whether it also carries image bytes, as it does.
    :returns: the mime data.
    """
    data = QMimeData()
    data.setUrls([QUrl.fromLocalFile(str(STAGED))])
    if original is not None:
        data.setData(ORIGINAL_FILE_MIME, str(original).encode())
    if with_pixels:
        data.setData("image/png", QByteArray(b"\x89PNG\r\n\x1a\n"))
    return data


def test_a_screenshot_of_this_record_dragged_from_a_file_manager_is_declined(
    saved_widget: DocumentWidget, saved_model: RehuDocumentModel, qtbot: QtBot, mocker: MockerFixture
) -> None:
    """The file itself is one of the record's screenshots, so dropping it would only duplicate it.

    **Test steps:**

    * list one screenshot for the record and drag that very file onto its Images dock
    * verify the drag was refused at the enter and nothing was acquired
    """
    list_screenshots(saved_model, mocker, OWN)
    acquire = mocker.patch.object(saved_widget.sub_docks._DocumentSubDocks__image_downloads, "acquire_local")  # type: ignore[attr-defined]  # pylint: disable=protected-access

    assert drag_onto_images_dock(saved_widget, qtbot, local_file_mime_data(OWN)) == (False, False)

    acquire.assert_not_called()


def test_a_screenshot_of_this_record_dragged_out_of_the_app_is_declined_by_its_original(
    saved_widget: DocumentWidget, saved_model: RehuDocumentModel, qtbot: QtBot, mocker: MockerFixture
) -> None:
    """A drag out of this app carries a staged copy, so the dock reads the original's path instead -- pixels or not.

    **Test steps:**

    * list one screenshot and drag its staged copy, naming it as the original, with its pixels
    * verify it was refused and nothing was acquired from the pixels either
    """
    list_screenshots(saved_model, mocker, OWN)
    acquire = mocker.patch.object(saved_widget.sub_docks._DocumentSubDocks__image_downloads, "acquire_local")  # type: ignore[attr-defined]  # pylint: disable=protected-access

    assert drag_onto_images_dock(saved_widget, qtbot, our_drag(OWN, with_pixels=True)) == (False, False)

    acquire.assert_not_called()


def test_a_screenshot_of_another_record_in_the_same_folder_is_acquired(
    saved_widget: DocumentWidget, saved_model: RehuDocumentModel, qtbot: QtBot, mocker: MockerFixture
) -> None:
    """Dropping ``info01.jpg`` of one record on the ``foo.rehu`` beside it makes ``foo``'s own copy: it is not one of
    *this* record's screenshots.

    **Test steps:**

    * list one screenshot for the record and drag another record's, from the same folder, out of the app
    * verify it was accepted and its staged copy acquired
    """
    list_screenshots(saved_model, mocker, OWN)
    acquire = mocker.patch.object(saved_widget.sub_docks._DocumentSubDocks__image_downloads, "acquire_local")  # type: ignore[attr-defined]  # pylint: disable=protected-access

    assert drag_onto_images_dock(saved_widget, qtbot, our_drag(OTHER_RECORDS)) == (True, True)

    acquire.assert_called_once_with([STAGED])


def test_an_image_out_of_the_pack_is_acquired(
    saved_widget: DocumentWidget, saved_model: RehuDocumentModel, qtbot: QtBot, mocker: MockerFixture
) -> None:
    """An archive member has no file of its own, so nothing names an original and the staged copy is acquired --
    the pack's images are a source of screenshots when the originals are gone.

    **Test steps:**

    * list one screenshot and drag an image with no original out of the app
    * verify it was accepted and acquired
    """
    list_screenshots(saved_model, mocker, OWN)
    acquire = mocker.patch.object(saved_widget.sub_docks._DocumentSubDocks__image_downloads, "acquire_local")  # type: ignore[attr-defined]  # pylint: disable=protected-access

    assert drag_onto_images_dock(saved_widget, qtbot, our_drag(None)) == (True, True)

    acquire.assert_called_once_with([STAGED])


def test_a_mixed_file_drop_acquires_what_is_not_already_a_screenshot(
    saved_widget: DocumentWidget, saved_model: RehuDocumentModel, qtbot: QtBot, mocker: MockerFixture
) -> None:
    """Several files, one of them the record's own screenshot: the others are acquired and that one left out.

    **Test steps:**

    * list one screenshot and drop it together with a file from elsewhere
    * verify the drop was accepted and only the other file acquired
    """
    list_screenshots(saved_model, mocker, OWN)
    acquire = mocker.patch.object(saved_widget.sub_docks._DocumentSubDocks__image_downloads, "acquire_local")  # type: ignore[attr-defined]  # pylint: disable=protected-access
    elsewhere = Path("/fake/elsewhere/dropped.jpg")

    assert drag_onto_images_dock(saved_widget, qtbot, local_file_mime_data(OWN, elsewhere)) == (True, True)

    acquire.assert_called_once_with([elsewhere])


def test_the_guard_is_decided_for_each_drag_as_it_enters(
    saved_widget: DocumentWidget, saved_model: RehuDocumentModel, qtbot: QtBot, mocker: MockerFixture
) -> None:
    """A screenshot added since the last drag counts at the next one, and one that is gone no longer does.

    **Test steps:**

    * drag a file while it is not a screenshot, then again once the scanner lists it, then once it no longer does
    * verify accepted, refused, accepted
    """
    acquire = mocker.patch.object(saved_widget.sub_docks._DocumentSubDocks__image_downloads, "acquire_local")  # type: ignore[attr-defined]  # pylint: disable=protected-access
    results = []
    for listed in ((), (OWN,), ()):
        list_screenshots(saved_model, mocker, *listed)
        results.append(drag_onto_images_dock(saved_widget, qtbot, local_file_mime_data(OWN)))

    assert results == [(True, True), (False, False), (True, True)]
    assert acquire.call_count == 2


def test_a_drag_over_the_dock_reuses_the_screenshots_read_when_it_entered(
    saved_widget: DocumentWidget, saved_model: RehuDocumentModel, qtbot: QtBot, mocker: MockerFixture
) -> None:
    """Moving over the dock does not read the folder again: the verdict of the enter stands for the whole drag.

    The enter goes through Qt's dispatch as every drop here does; the moves go to the installed filter by hand, because
    a synthetic ``DragMove`` sent with ``QApplication.sendEvent`` after an ignored enter is dropped inside
    ``QApplication.notify`` before it reaches any event filter, the application's included (probed, 2026-10-11).

    **Test steps:**

    * list one screenshot and drag it onto the dock, then move over the dock twice
    * make the scanner list nothing between the moves
    * verify the scanner was read once, and the file was refused at the enter and at both moves
    """
    assert saved_model.image_scanner is not None
    scanner_files = mocker.patch.object(saved_model.image_scanner, "files", return_value=[OWN])
    saved_widget.show()
    qtbot.waitExposed(saved_widget)
    saved_widget.toggle_action(EDITOR_IMAGES_TAB).trigger()
    dock = images_dock(saved_widget)
    drop_filter = saved_widget.sub_docks._DocumentSubDocks__image_drop_filter  # type: ignore[attr-defined]  # pylint: disable=protected-access
    data = local_file_mime_data(OWN)

    enter = QDragEnterEvent(
        QPoint(), Qt.DropAction.CopyAction, data, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier
    )
    QApplication.sendEvent(dock, enter)
    scanner_files.return_value = []
    moves = []
    for _ in range(2):
        move = QDragMoveEvent(
            QPoint(), Qt.DropAction.CopyAction, data, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier
        )
        assert drop_filter.eventFilter(dock, move)
        moves.append(move.isAccepted())

    assert (enter.isAccepted(), moves) == (False, [False, False])
    assert scanner_files.call_count == 1


def test_a_drop_that_carries_only_pixels_is_acquired_as_pixels(
    saved_widget: DocumentWidget, saved_model: RehuDocumentModel, qtbot: QtBot, mocker: MockerFixture
) -> None:
    """With no file and no original to compare, nothing can say it is one of the record's own: the bytes are taken.

    **Test steps:**

    * list one screenshot and drop a bare image payload
    * verify it was accepted and acquired once
    """
    list_screenshots(saved_model, mocker, OWN)
    acquire = mocker.patch.object(saved_widget.sub_docks._DocumentSubDocks__image_downloads, "acquire_local")  # type: ignore[attr-defined]  # pylint: disable=protected-access

    assert drag_onto_images_dock(saved_widget, qtbot, image_bytes_mime_data()) == (True, True)

    acquire.assert_called_once()


def test_a_staged_copy_carrying_pixels_but_no_original_is_acquired_by_its_file_alone(
    saved_widget: DocumentWidget, saved_model: RehuDocumentModel, qtbot: QtBot, mocker: MockerFixture
) -> None:
    """An archive member dragged out of the app carries its pixels as well as its staged file, and is acquired once,
    as the file: the pixels beside a file are not a second image.

    **Test steps:**

    * list one screenshot and drop a staged copy with pixels and no original
    * verify the staged file alone was acquired, once
    """
    list_screenshots(saved_model, mocker, OWN)
    acquire = mocker.patch.object(saved_widget.sub_docks._DocumentSubDocks__image_downloads, "acquire_local")  # type: ignore[attr-defined]  # pylint: disable=protected-access

    assert drag_onto_images_dock(saved_widget, qtbot, our_drag(None, with_pixels=True)) == (True, True)

    acquire.assert_called_once_with([STAGED])


def test_a_screenshot_through_another_spelling_of_its_path_is_declined_only_where_paths_fold_case(
    saved_widget: DocumentWidget, saved_model: RehuDocumentModel, qtbot: QtBot, mocker: MockerFixture
) -> None:
    """Paths are compared as the file system compares them: the same name in capitals is the same file on Windows and
    another file on a case-sensitive system, where it is acquired.

    **Test steps:**

    * list one screenshot and drag the same path with its name in capitals, naming it as the original
    * verify it was refused where the platform folds case, and accepted where it does not
    """
    list_screenshots(saved_model, mocker, OWN)
    acquire = mocker.patch.object(saved_widget.sub_docks._DocumentSubDocks__image_downloads, "acquire_local")  # type: ignore[attr-defined]  # pylint: disable=protected-access
    shouted = FOLDER / OWN.name.upper()
    folds = os.path.normcase(str(shouted)) == os.path.normcase(str(OWN))

    result = drag_onto_images_dock(saved_widget, qtbot, our_drag(shouted))

    assert result == ((False, False) if folds else (True, True))
    assert acquire.call_count == (0 if folds else 1)
