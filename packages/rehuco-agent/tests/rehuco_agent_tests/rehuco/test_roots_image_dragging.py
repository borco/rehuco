"""Tests for dragging an image out of the Roots view -- a row of the column, or the picture in the details pane (#395).

The docks, the in-memory cache and the real folders are :mod:`test_catalog_docks`' own fixtures, imported by name, as
:mod:`test_roots_lightbox_actions` does.
"""

import os
from pathlib import Path
from typing import Final

from PySide6.QtCore import QEvent, QModelIndex, QPersistentModelIndex, QPoint, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractItemView, QApplication, QWidget
from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco.roots_column_view import RootsColumnView
from rehuco_agent.rehuco.roots_preview import RootsPreview
from rehuco_agent.rehuco.scaled_image import ScaledImage
from rehuco_agent.settings.persistent_settings import staging_folder

from rehuco_agent_tests.fields.widgets.test_image_export_gestures import mouse

from .test_catalog_docks import (  # noqa: F401  # pylint: disable=unused-import
    REHUCO_PATH,
    CatalogDocks,
    fixture_database,
    fixture_dock,
    fixture_folders,
    fixture_queue,
    fixture_served,
    open_root_folder,
)
from .test_roots_lightbox_actions import add_pack_files

pytestmark = mark.usefixtures("served", "real_path_stat", "staging_folder_exists")

ID: Final = "0f8fad5b-d9cb-469f-a165-70867728950e"


@fixture
def staging_folder_exists() -> None:
    """Create the staging folder with ``os.makedirs``: the dock fixtures patch ``Path.mkdir``, which staging uses."""
    os.makedirs(staging_folder(), exist_ok=True)


def column_of(view: RootsColumnView, index: QModelIndex) -> QAbstractItemView:
    """The column that lists a row.

    :param view: the column view.
    :param index: the row.
    :returns: its column.
    """
    columns = view.findChildren(QAbstractItemView)
    return next(column for column in columns if column.model() is not None and column.rootIndex() == index.parent())


def press_and_move(widget: QWidget, start: QPoint) -> None:
    """Press the left button and move well past the drag distance.

    :param widget: the widget under the pointer.
    :param start: where the press lands.
    """
    QTest.mousePress(widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    far = start + QPoint(0, 3 * QApplication.startDragDistance())
    QApplication.sendEvent(
        widget, mouse(QEvent.Type.MouseMove, far, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
    )
    QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)


def staged_names(drag_class: object) -> list[str]:
    """The file names the patched drag was handed, in order.

    :param drag_class: the patched ``QDrag``.
    :returns: the names.
    """
    names = []
    for call in drag_class.return_value.setMimeData.call_args_list:  # type: ignore[attr-defined]
        (mime,) = call.args
        names.append(Path(mime.urls()[0].toLocalFile()).name)
    return names


def test_dragging_an_image_row_out_of_a_column_exports_it(
    mocker: MockerFixture, qtbot: QtBot, dock: CatalogDocks, folders: Path
) -> None:
    """A press on an image's row that moves the drag distance drags that file out as a copy; no record manages it
    here, so it is named by its folder.

    **Test steps:**

    * open a folder holding pictures and an archive, and press-and-move one picture's row
    * verify one copy drag carrying that picture, named by its folder and its own name
    """
    add_pack_files(folders)
    dock.catalog.open_rehuco(REHUCO_PATH)
    drag_class = mocker.patch("rehuco_agent.fields.widgets.image_export.QDrag")
    image = open_root_folder(qtbot, dock, "my folder", "b.png")
    column = column_of(dock.roots.roots_view, image)

    press_and_move(column.viewport(), column.visualRect(image).center())

    drag_class.return_value.exec.assert_called_once_with(Qt.DropAction.CopyAction)
    assert staged_names(drag_class) == ["rehu-my folder__b.png"]


def test_a_row_that_is_not_an_image_or_a_press_that_barely_moves_drags_nothing(
    mocker: MockerFixture, qtbot: QtBot, dock: CatalogDocks, folders: Path
) -> None:
    """Folders and archives are not dragged out, and neither is an image pressed and let go.

    **Test steps:**

    * press-and-move an archive's row, then press-and-release a picture's
    * verify no drag was built
    """
    add_pack_files(folders)
    dock.catalog.open_rehuco(REHUCO_PATH)
    drag_class = mocker.patch("rehuco_agent.fields.widgets.image_export.QDrag")
    archive = open_root_folder(qtbot, dock, "my folder", "loose.zip")
    column = column_of(dock.roots.roots_view, archive)
    image = next(
        dock.roots.roots_model.index(row, 0, archive.parent())
        for row in range(dock.roots.roots_model.rowCount(archive.parent()))
        if dock.roots.roots_model.index(row, 0, archive.parent()).data() == "b.png"
    )

    press_and_move(column.viewport(), column.visualRect(archive).center())
    QTest.mouseClick(
        column.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, column.visualRect(image).center()
    )

    drag_class.assert_not_called()


def test_an_image_the_cache_knows_a_record_for_is_named_by_that_records_id(
    mocker: MockerFixture, qtbot: QtBot, dock: CatalogDocks, folders: Path
) -> None:
    """An image under a folder's ``info.rehu`` is named by the id the catalog holds for that record, its path
    relative to the record's folder.

    **Test steps:**

    * put a picture under ``alpha``, whose record the cache gives an id, and drag its row
    * verify the staged name carries the id
    """
    add_pack_files(folders)
    (folders / "alpha" / "pic.png").write_bytes(b"x")
    dock.catalog.open_rehuco(REHUCO_PATH)
    mocker.patch.object(dock.catalog, "resource_uuid", return_value=ID)
    drag_class = mocker.patch("rehuco_agent.fields.widgets.image_export.QDrag")
    image = open_root_folder(qtbot, dock, "alpha", "pic.png")
    column = column_of(dock.roots.roots_view, image)

    press_and_move(column.viewport(), column.visualRect(image).center())

    assert staged_names(drag_class) == [f"rehu-{ID}__pic.png"]


def test_dragging_the_picture_in_the_details_pane_exports_that_image(
    mocker: MockerFixture, qtbot: QtBot, dock: CatalogDocks, folders: Path
) -> None:
    """The details pane shows the selected picture; a press-and-move on it drags that file out like its row.

    **Test steps:**

    * give a folder a real picture, select it and wait for the pane to show it
    * press-and-move the pane's picture
    * verify one copy drag carrying that picture
    """
    add_pack_files(folders)
    image = QImage(30, 20, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.darkGreen)
    assert image.save(str(folders / "my folder" / "b.png"))
    dock.catalog.open_rehuco(REHUCO_PATH)
    drag_class = mocker.patch("rehuco_agent.fields.widgets.image_export.QDrag")
    row = open_root_folder(qtbot, dock, "my folder", "b.png")
    dock.roots.roots_view.setCurrentIndex(row)
    preview = dock.roots.findChild(RootsPreview)
    assert isinstance(preview, RootsPreview)
    qtbot.waitUntil(lambda: preview.image is not None)
    label = preview.findChild(ScaledImage)
    assert isinstance(label, ScaledImage)

    press_and_move(label, QPoint(3, 3))

    drag_class.return_value.exec.assert_called_once_with(Qt.DropAction.CopyAction)
    assert staged_names(drag_class) == ["rehu-my folder__b.png"]
    (shown,) = drag_class.return_value.setPixmap.call_args.args
    assert isinstance(shown, QPixmap) and not shown.isNull()


def test_a_row_that_is_gone_or_a_picture_that_is_gone_drags_nothing(
    mocker: MockerFixture, qtbot: QtBot, dock: CatalogDocks, folders: Path
) -> None:
    """An image row removed between the press and the move comes back invalid, and a details pane whose picture was
    cleared in the meantime has none to drag: either is turned away.

    **Test steps:**

    * report an invalid row as dragged
    * report a drag of the details pane while it shows no picture
    * verify no drag was built
    """
    add_pack_files(folders)
    dock.catalog.open_rehuco(REHUCO_PATH)
    drag_class = mocker.patch("rehuco_agent.fields.widgets.image_export.QDrag")
    open_root_folder(qtbot, dock, "my folder")
    widget = QWidget()
    qtbot.addWidget(widget)
    preview = dock.roots.findChild(RootsPreview)
    assert isinstance(preview, RootsPreview)

    dock.roots.roots_view.image_drag_requested.emit(QModelIndex(), widget, QPixmap())
    preview._RootsPreview__on_image_drag(QPersistentModelIndex())  # type: ignore[attr-defined]  # pylint: disable=protected-access

    drag_class.assert_not_called()
