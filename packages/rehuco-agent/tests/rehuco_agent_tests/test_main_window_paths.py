"""Tests for the paths the main window opens: kept as the user reached them, a mapped drive letter included (#511).

``Path.resolve`` follows a mapped drive to the share behind it, and the two spellings are not the same place to the
rest of the app. Every test here stands a resolve in that maps the working directory's drive to a share, so an open
that still resolves lands under the share and fails.
"""

from pathlib import Path
from typing import Final

from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.main_window import MainWindow
from rehuco_agent.rehuco import BrowsersDock, RootCatalog
from rehuco_core.access import ResourceKey

from .test_main_window import mock_persistent_settings  # noqa: F401  # pylint: disable=unused-import

pytestmark = mark.usefixtures("stub_settings_pages", "stub_sub_docks")
"""Every window here is built over stub settings pages, and every document it opens over stub sub-docks (#545), but
where a test asks for the real ones (``real_settings_pages``, ``real_sub_docks``)."""

SHARE: Final = Path("//nas/share")
"""Where the stand-in resolve says the working directory's drive really is."""


def mapped(path: Path) -> Path:
    """``path`` as a resolve following a mapped drive would spell it.

    :param path: any path.
    :returns: the same place, under :data:`SHARE`.
    """
    absolute = path.absolute()
    return SHARE / absolute.relative_to(absolute.anchor)


@fixture(name="window")
def fixture_window(mocker: MockerFixture, qtbot: QtBot) -> MainWindow:
    """A window built as usual, after which every resolve follows the mapped drive.

    :param mocker: pytest-mock fixture.
    :param qtbot: pytest-qt fixture.
    :returns: the window.
    """
    window = MainWindow()
    qtbot.addWidget(window)
    mocker.patch.object(Path, "resolve", autospec=True, side_effect=lambda self, strict=False: mapped(self))
    return window


def catalog_of(window: MainWindow) -> RootCatalog:
    """The window's Root Catalog.

    :param window: the window.
    :returns: its catalog.
    """
    return window._MainWindow__root_catalog  # type: ignore[attr-defined]  # pylint: disable=protected-access


def test_the_stand_in_resolve_moves_a_path_to_the_share(window: MainWindow) -> None:
    """The premise of every test here: a resolve lands elsewhere than the path as given.

    **Test steps:**

    * resolve a relative path
    * verify it is under the share, and not where the path made absolute is
    """
    del window

    assert Path("a.rehu").resolve() == mapped(Path("a.rehu"))
    assert Path("a.rehu").resolve() != Path.cwd() / "a.rehu"


def test_documents_folders_and_archives_open_as_given(mocker: MockerFixture, window: MainWindow) -> None:
    """A document, a folder, an archive and a preview are each opened at the path made absolute, never resolved.

    **Test steps:**

    * stand in for the documents dock's opens, and open a relative path of each kind, and show one in the preview
    * verify each reached the dock under the working directory's drive
    """
    dock = "rehuco_agent.main_window.DocumentsDock"
    open_document = mocker.patch(f"{dock}.open_document")
    open_folder = mocker.patch(f"{dock}.open_folder")
    open_archive = mocker.patch(f"{dock}.open_archive")
    show_in_preview = mocker.patch(f"{dock}.show_in_preview")

    window.open_file("a.rehu")
    window.open_folder("a_folder")
    window.open_archive("a.zip")
    window.show_in_preview("b.rehu")

    open_document.assert_called_once_with(ResourceKey(Path.cwd() / "a.rehu"))
    open_folder.assert_called_once_with(ResourceKey(Path.cwd() / "a_folder"))
    open_archive.assert_called_once_with(ResourceKey(Path.cwd() / "a.zip"))
    show_in_preview.assert_called_once_with(ResourceKey(Path.cwd() / "b.rehu"))


def test_a_selection_is_previewed_as_the_catalog_spelled_it(mocker: MockerFixture, window: MainWindow) -> None:
    """A resource selected in a browser is previewed under its root's own spelling, which the catalog lists it by --
    not the share a resolve would follow its drive to.

    **Test steps:**

    * stand in for the documents dock's preview, and hand the window a selection's key under the working directory
    * verify the preview got that key as it was
    """
    show_in_preview = mocker.patch("rehuco_agent.main_window.DocumentsDock.show_in_preview")

    window._MainWindow__show_selection_in_preview(  # type: ignore[attr-defined]  # pylint: disable=protected-access
        ResourceKey(Path.cwd() / "pack" / "info.rehu")
    )

    show_in_preview.assert_called_once_with(ResourceKey(Path.cwd() / "pack" / "info.rehu"))


def test_a_rehuco_opens_and_is_remembered_as_given(mocker: MockerFixture, window: MainWindow) -> None:
    """A ``.rehuco`` is opened and remembered under the path made absolute.

    **Test steps:**

    * stand in for the catalog's open, and open a relative ``.rehuco``
    * verify the catalog got, and the recents hold, the path under the working directory's drive
    """
    open_rehuco = mocker.patch.object(catalog_of(window), "open_rehuco", return_value=True)

    assert window.open_rehuco_path("home.rehuco")

    open_rehuco.assert_called_once_with(Path.cwd() / "home.rehuco")
    assert window._MainWindow__rehuco_settings.newest_first() == [Path.cwd() / "home.rehuco"]  # type: ignore[attr-defined]  # pylint: disable=protected-access


def test_a_new_rehuco_is_made_where_it_was_named(mocker: MockerFixture, window: MainWindow) -> None:
    """A new ``.rehuco`` is made at the path the dialog named, made absolute.

    **Test steps:**

    * have the save dialog name a relative path, and stand in for the catalog's ``new_rehuco``
    * trigger *New Root Catalog*
    * verify the catalog got the path under the working directory's drive
    """
    mocker.patch("rehuco_agent.main_window.QFileDialog.getSaveFileName", return_value=("home.rehuco", ""))
    new_rehuco = mocker.patch.object(catalog_of(window), "new_rehuco", return_value=True)

    window._MainWindow__ui.new_rehuco_action.trigger()  # type: ignore[attr-defined]  # pylint: disable=protected-access

    new_rehuco.assert_called_once_with(Path.cwd() / "home.rehuco")


def test_a_refused_open_is_said_in_the_status_bar(window: MainWindow) -> None:
    """A browser that cannot open a resource -- its root out of reach -- says why where the reader looks.

    **Test steps:**

    * have the Browsers dock refuse an open with a reason
    * verify the status bar shows the reason
    """
    dock = window._MainWindow__browsers_dock  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert isinstance(dock, BrowsersDock)

    dock.open_refused.emit("The root is out of reach.")

    assert window.statusBar().currentMessage() == "The root is out of reach."
