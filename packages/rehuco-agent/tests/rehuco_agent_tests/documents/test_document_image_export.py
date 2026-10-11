"""Tests for how a document hands its one image exporter to everything that takes an image out of the app (#485).

The exporter's own behaviour is covered with the widgets that use it; these cover the wiring only the document owns:
the viewer a document opens stages under the document's id, the Content Images grid is built holding the document's
exporter, and a type switch that rebuilds the form hands it over again.
"""

from pathlib import Path

from PySide6.QtGui import QGuiApplication, QImage
from pytest import mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.document_widget import DocumentWidget
from rehuco_agent.documents.files_view import FilesView
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields.fields_form import FieldsForm
from rehuco_core import RehuDocument

from .test_document_widget import (  # noqa: F401  # pylint: disable=unused-import
    content_images_view,
    files_dock,
    fixture_refimages_model,
    fixture_refimages_widget,
)

__EXPORTER = "_DocumentSubDocks__image_exporter"


@mark.usefixtures("real_path_stat", "clipboard")
def test_copying_from_a_viewer_the_document_opened_stages_the_image_under_the_documents_id(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """Copy in a lightbox a document opens puts a staged copy named by the document's id on the clipboard -- the
    origin the document reports and the exporter the lightbox was given are the same ones.

    **Test steps:**

    * over a document in a real folder holding a picture, open a folder viewer from the Files sub-dock
    * trigger the viewer's Copy
    * verify the clipboard holds the staged file named by the document's id and the picture's name
    """
    folder = tmp_path / "Pack"
    folder.mkdir()
    picture = folder / "a.png"
    image = QImage(8, 6, QImage.Format.Format_RGB32)
    assert image.save(str(picture))
    document = RehuDocument.new(folder / "info.rehu")
    widget = DocumentWidget(RehuDocumentModel(document))
    qtbot.addWidget(widget)
    view = files_dock(widget).widget()
    assert isinstance(view, FilesView)
    view.images_activated.emit([picture], picture)
    viewer = widget.sub_docks._DocumentSubDocks__image_viewer  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert viewer is not None
    assert viewer.copy_action is not None

    viewer.copy_action.trigger()

    held = QGuiApplication.clipboard().mimeData()
    assert held is not None
    assert document.id
    assert [Path(url.toLocalFile()).name for url in held.urls()] == [f"rehu-{document.id}__a.png"]


def test_the_content_images_grid_is_built_with_the_documents_exporter(refimages_widget: DocumentWidget) -> None:
    """The grid takes images out through the document's exporter, so what it drags and copies is named like what its
    lightbox and its strip hand over.

    **Test steps:**

    * build a widget over a reference pack
    * verify its Content Images grid holds the very exporter the sub-docks do
    """
    grid = content_images_view(refimages_widget)

    exporter = getattr(refimages_widget.sub_docks, __EXPORTER, None)
    assert exporter is not None
    assert grid._ContentImagesView__exporter is exporter  # type: ignore[attr-defined]  # pylint: disable=protected-access


def test_a_type_switch_hands_the_rebuilt_form_the_exporter_again(
    refimages_widget: DocumentWidget, refimages_model: RehuDocumentModel, mocker: MockerFixture
) -> None:
    """A switch rebuilds the form, whose fresh fields are built after the owner hands over the exporter -- so the
    hand-over runs again, with the same exporter, before they are.

    **Test steps:**

    * spy on the form's hand-over and switch the document's type
    * verify it ran again, with the sub-docks' exporter
    """
    handed = mocker.spy(FieldsForm, "connect_image_export")
    exporter = getattr(refimages_widget.sub_docks, __EXPORTER)

    refimages_model.resource_type = "tutorial"

    assert handed.call_count == 1
    assert handed.call_args.args[1] is exporter
