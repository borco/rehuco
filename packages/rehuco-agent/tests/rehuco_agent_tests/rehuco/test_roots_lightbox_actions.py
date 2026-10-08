"""Tests for what the Roots view offers for an image or a zip, and what a double-click does (#456).

The docks, the in-memory cache and the real folders are :mod:`test_catalog_docks`' own fixtures, imported by name.
"""

from pathlib import Path

from borco_pyside.widgets import MessageBanner
from PySide6.QtCore import QModelIndex, Qt, QUrl
from PySide6.QtWidgets import QLabel
from pytest import mark, param
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot

from .test_catalog_docks import (  # noqa: F401  # pylint: disable=unused-import
    REHUCO_PATH,
    CatalogDocks,
    child_names,
    fixture_database,
    fixture_dock,
    fixture_folders,
    fixture_queue,
    fixture_served,
    open_root_folder,
    pane_buttons,
    without_separators,
)


def add_pack_files(folders: Path) -> None:
    """Give the folders what the lightbox tests need.

    ``my folder`` holds ``pack.zip`` with its own ``pack.rehu``, ``loose.zip`` with no record and three pictures;
    ``alpha`` holds an ``info.rehu`` with ``inner.zip`` under it.

    :param folders: the first root's folder.
    """
    inside = folders / "my folder"
    (inside / "pack.zip").write_bytes(b"z")
    (inside / "pack.rehu").write_text("{}", encoding="utf-8")
    (inside / "loose.zip").write_bytes(b"z")
    for name in ("b.png", "a.jpg", "c.png"):
        (inside / name).write_bytes(b"x")
    (folders / "alpha" / "info.rehu").write_text("{}", encoding="utf-8")
    (folders / "alpha" / "inner.zip").write_bytes(b"z")


def banner_text(dock: CatalogDocks) -> str:
    """Everything the Roots panel's banner says.

    :param dock: the catalog's docks.
    :returns: its labels' texts, joined.
    """
    banner = dock.roots.findChild(MessageBanner)
    assert banner is not None
    return " ".join(label.text() for label in banner.findChildren(QLabel))


@mark.usefixtures("served")
def test_a_pack_archive_opens_in_the_lightbox_and_offers_the_external_app_and_its_rehu(
    mocker: MockerFixture, qtbot: QtBot, dock: CatalogDocks, folders: Path
) -> None:
    """The lightbox is the default of a zip the cache knows as reference images; the system's application and the
    zip's own rehu follow, in the menu and in the buttons.

    **Test steps:**

    * make ``pack.zip`` a reference pack through its own ``pack.rehu``, and double-click it
    * verify the menu, the buttons and their default, and that the lightbox was asked for the zip
    """
    add_pack_files(folders)
    dock.catalog.open_rehuco(REHUCO_PATH)
    mocker.patch.object(dock.catalog, "resource_type", return_value="ReferenceImages")
    opened = mocker.patch.object(dock.roots.lightbox, "open_archive")
    pack = open_root_folder(qtbot, dock, "my folder", "pack.zip")
    roots = dock.roots

    assert without_separators(roots.roots_context_actions(pack))[:3] == [
        roots.open_lightbox_action,
        roots.open_file_action,
        roots.open_companion_action,
    ]
    assert roots.open_file_action.text() == "Open in external app"
    assert pane_buttons(dock, pack)[:3] == [
        roots.open_lightbox_action,
        roots.open_file_action,
        roots.open_explorer_action,
    ]
    assert roots.open_lightbox_action.font().bold() and not roots.open_file_action.font().bold()

    roots.roots_view.doubleClicked.emit(pack)

    opened.assert_called_once_with(folders / "my folder" / "pack.zip")


@mark.usefixtures("served")
def test_a_pack_through_its_folders_record_offers_no_associated_rehu_of_its_own(
    mocker: MockerFixture, qtbot: QtBot, dock: CatalogDocks, folders: Path
) -> None:
    """A zip under an ``info.rehu`` is the same record as its folder's, so neither Open associated rehu nor Create is
    offered for it.

    **Test steps:**

    * make ``alpha/inner.zip`` a reference pack through ``alpha/info.rehu``
    * verify its menu has the lightbox and the external app, and neither the open nor the create entry
    """
    add_pack_files(folders)
    dock.catalog.open_rehuco(REHUCO_PATH)
    mocker.patch.object(dock.catalog, "resource_type", return_value="reference_images")
    inner = open_root_folder(qtbot, dock, "alpha", "inner.zip")
    roots = dock.roots

    menu = without_separators(roots.roots_context_actions(inner))

    assert menu[:2] == [roots.open_lightbox_action, roots.open_file_action]
    assert roots.open_companion_action not in menu and roots.create_companion_action not in menu


@mark.usefixtures("served")
@mark.parametrize("known", [param("tutorial", id="another-type"), param(None, id="not-scanned")])
def test_an_archive_that_is_no_known_pack_opens_externally_by_default(
    mocker: MockerFixture, qtbot: QtBot, dock: CatalogDocks, folders: Path, known: str | None
) -> None:
    """A zip of another type, or whose record the cache has not scanned, keeps the system's application as its
    default and never starts the lightbox.

    **Test steps:**

    * ask for ``pack.zip`` while the cache says another type, then nothing, and for ``loose.zip`` that no record
      manages
    * verify the default, the menu and that a double-click opens externally
    """
    add_pack_files(folders)
    dock.catalog.open_rehuco(REHUCO_PATH)
    mocker.patch.object(dock.catalog, "resource_type", return_value=known)
    opener = mocker.patch("rehuco_agent.rehuco.roots_panel.QDesktopServices.openUrl")
    lightbox = mocker.patch.object(dock.roots.lightbox, "open_archive")
    pack = open_root_folder(qtbot, dock, "my folder", "pack.zip")
    unmanaged = open_root_folder(qtbot, dock, "my folder", "loose.zip")
    roots = dock.roots

    assert without_separators(roots.roots_context_actions(pack))[:2] == [
        roots.open_file_action,
        roots.open_companion_action,
    ]
    assert without_separators(roots.roots_context_actions(unmanaged))[:2] == [
        roots.open_file_action,
        roots.create_companion_action,
    ]
    roots.roots_view.doubleClicked.emit(pack)

    opener.assert_called_once_with(QUrl.fromLocalFile(str(folders / "my folder" / "pack.zip")))
    lightbox.assert_not_called()


@mark.usefixtures("served")
def test_an_image_opens_in_the_lightbox_with_the_images_beside_it(
    mocker: MockerFixture, qtbot: QtBot, dock: CatalogDocks, folders: Path
) -> None:
    """A double-click on a picture shows the folder's pictures in the order the column lists them, starting on it --
    never the videos and archives among them.

    **Test steps:**

    * double-click ``b.png`` of a folder holding three pictures, two archives and a record
    * verify the lightbox was given the three pictures in the column's order, on the second
    """
    add_pack_files(folders)
    dock.catalog.open_rehuco(REHUCO_PATH)
    opened = mocker.patch.object(dock.roots.lightbox, "open_images")
    image = open_root_folder(qtbot, dock, "my folder", "b.png")
    roots = dock.roots
    listed = [name for name in child_names(dock, image.parent()) if name.endswith((".png", ".jpg"))]

    assert without_separators(roots.roots_context_actions(image))[:2] == [
        roots.open_lightbox_action,
        roots.open_file_action,
    ]
    roots.roots_view.doubleClicked.emit(image)

    opened.assert_called_once_with([folders / "my folder" / name for name in listed], listed.index("b.png"))
    assert sorted(listed) == ["a.jpg", "b.png", "c.png"]


@mark.usefixtures("served")
@mark.parametrize(
    ("held", "external"),
    [
        param(Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier, True, id="ctrl-alt"),
        param(Qt.KeyboardModifier.ControlModifier, False, id="ctrl"),
        param(Qt.KeyboardModifier.ShiftModifier, False, id="shift"),
        param(Qt.KeyboardModifier.AltModifier, False, id="alt"),
    ],
)
def test_ctrl_alt_double_click_hands_an_image_or_a_zip_to_the_system(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    mocker: MockerFixture,
    qtbot: QtBot,
    dock: CatalogDocks,
    folders: Path,
    held: Qt.KeyboardModifier,
    external: bool,  # noqa: FBT001
) -> None:
    """Both keys together mean the system's application; Ctrl and Shift alone stay the lightbox's choice of surface.

    **Test steps:**

    * double-click a picture and a pack with the keys held
    * verify each opened externally when both Ctrl and Alt were down, and in the lightbox otherwise
    """
    add_pack_files(folders)
    dock.catalog.open_rehuco(REHUCO_PATH)
    mocker.patch.object(dock.catalog, "resource_type", return_value="ReferenceImages")
    mocker.patch("rehuco_agent.rehuco.roots_opening.QApplication.keyboardModifiers", return_value=held)
    opener = mocker.patch("rehuco_agent.rehuco.roots_panel.QDesktopServices.openUrl")
    archives = mocker.patch.object(dock.roots.lightbox, "open_archive")
    images = mocker.patch.object(dock.roots.lightbox, "open_images")
    image = open_root_folder(qtbot, dock, "my folder", "b.png")
    pack = open_root_folder(qtbot, dock, "my folder", "pack.zip")

    for row in (image, pack):
        dock.roots.roots_view.doubleClicked.emit(row)

    assert opener.call_count == (2 if external else 0)
    assert (archives.call_count, images.call_count) == ((0, 0) if external else (1, 1))


@mark.usefixtures("served")
def test_a_notice_from_the_lightbox_shows_on_the_banner_until_the_selection_moves(
    qtbot: QtBot, dock: CatalogDocks, folders: Path
) -> None:
    """A pack with no images says so where the user is looking, and the notice goes with the next selection.

    **Test steps:**

    * have the lightbox report a notice, then select another row
    * verify the banner shows it, and no longer after the move
    """
    add_pack_files(folders)
    dock.catalog.open_rehuco(REHUCO_PATH)
    image = open_root_folder(qtbot, dock, "my folder", "b.png")

    dock.roots.lightbox.nothing_to_show.emit("pack.zip holds no images.")
    assert "pack.zip holds no images." in banner_text(dock)

    first: QModelIndex = image.siblingAtRow(0)
    dock.roots.roots_view.setCurrentIndex(first)
    assert "pack.zip holds no images." not in banner_text(dock)
