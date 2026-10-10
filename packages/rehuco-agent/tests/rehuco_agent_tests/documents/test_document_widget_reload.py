"""Tests for what a document's docks do when its file is read again or changes on disk (#487)."""

from pathlib import Path

from PySide6.QtWidgets import QLabel
from pytest import mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.content_images import content_images_model
from rehuco_agent.documents.document_sub_docks import CHANGED_ON_DISK_MESSAGE
from rehuco_agent.documents.document_widget import DocumentWidget
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel

from .test_document_widget import (  # noqa: F401  # pylint: disable=unused-import
    WAIT_TIMEOUT_MS,
    banner,
    content_images_dock,
    content_images_view,
    fixture_refimages_model,
    fixture_refimages_widget,
)


def banner_text(widget: DocumentWidget) -> str:
    """Everything the document's banner says."""
    return " ".join(label.text() for label in banner(widget).findChildren(QLabel))


def test_a_file_changed_under_unsaved_edits_is_said_on_the_banner(
    refimages_widget: DocumentWidget, refimages_model: RehuDocumentModel
) -> None:
    """The model leaves the edits alone and raises the flag; the banner says what Revert and Save would do (#487).

    **Test steps:**

    * raise the model's changed-on-disk flag, then lower it
    * verify the banner says it, then no longer does
    """
    refimages_model.changed_on_disk = True
    assert "changed outside the app" in banner_text(refimages_widget)
    assert CHANGED_ON_DISK_MESSAGE.startswith("This file was changed outside the app")

    refimages_model.changed_on_disk = False
    assert "changed outside the app" not in banner_text(refimages_widget)


@mark.usefixtures("real_path_stat")
def test_a_reload_reads_the_content_images_again(
    refimages_widget: DocumentWidget,
    refimages_model: RehuDocumentModel,
    mocker: MockerFixture,
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    """A revert is how a zip changed outside the app is picked up, and the open dock follows without its own Refresh.

    **Test steps:**

    * save the pack to a real file and show the dock, and wait for its first enumeration
    * revert the document
    * verify the content images were enumerated again
    """
    enumeration = mocker.patch.object(content_images_model, "enumerate_content_images", return_value=[])
    path = tmp_path / "info.rehu"
    refimages_model.document.save(path)
    refimages_model.path = path
    content_images_dock(refimages_widget).toggleView(True)
    qtbot.waitUntil(lambda: content_images_view(refimages_widget).layout_table is not None)
    qtbot.waitUntil(lambda: enumeration.call_count == 1, timeout=WAIT_TIMEOUT_MS)

    refimages_model.revert()

    qtbot.waitUntil(lambda: enumeration.call_count == 2, timeout=WAIT_TIMEOUT_MS)


@mark.usefixtures("real_path_stat")
def test_a_load_of_another_file_reads_the_content_images_once(
    refimages_widget: DocumentWidget,
    refimages_model: RehuDocumentModel,
    mocker: MockerFixture,
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    """A preview moving to another pack changes the path and reloads in one go: every archive is opened once.

    **Test steps:**

    * save the pack to a real file, and a second pack beside it; show the dock and wait for its first enumeration
    * load the second pack in the model, as the preview does
    * verify one more enumeration, not two
    """
    enumeration = mocker.patch.object(content_images_model, "enumerate_content_images", return_value=[])
    first, second = tmp_path / "a" / "info.rehu", tmp_path / "b" / "info.rehu"
    for path in (first, second):
        path.parent.mkdir()
        refimages_model.document.save(path)
    refimages_model.path = first
    content_images_dock(refimages_widget).toggleView(True)
    qtbot.waitUntil(lambda: content_images_view(refimages_widget).layout_table is not None)
    qtbot.waitUntil(lambda: enumeration.call_count == 1, timeout=WAIT_TIMEOUT_MS)

    refimages_model.load(second)
    qtbot.wait(100)

    assert enumeration.call_count == 2
