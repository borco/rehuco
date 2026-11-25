"""Tests for an asset's License dock in its document's sub-docks (#688, [[assets#licenses]]): which types have it, where
it sits, what shows it, and that its mode survives in the layout."""

# astroid reads the sub-docks' name-to-dock dict's values as signals, and every call on a dock then fails
# pylint: disable=no-member,protected-access

from pathlib import Path
from typing import Final

import PySide6QtAds as QtAds
from borco_pyside.theming import themed_svg_icon
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QToolBar
from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.document_sub_docks import (
    LICENSE_DOCK_MIN_HEIGHT,
    LICENSE_DOCK_NAME,
    LICENSE_DOCK_TITLE,
    LICENSE_ICON_RESOURCE,
    type_dock_names,
)
from rehuco_agent.documents.document_widget import DocumentWidget
from rehuco_agent.documents.files_view import FilesView
from rehuco_agent.documents.license_panel import LicensePanel
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_core import ASSET_PLUGIN, TUTORIAL_PLUGIN, RehuDocument

from .test_document_widget import docks_carrying
from .test_rehu_document_model_conflict import opened, write_record

pytestmark = mark.usefixtures("real_path_stat")

SIDECAR: Final = Path.cwd() / "fake" / "info.rehuterms"


def widget_over(qtbot: QtBot, model: RehuDocumentModel) -> DocumentWidget:
    """A document's widget.

    :param qtbot: pytest-qt fixture.
    :param model: the document.
    :returns: the widget.
    """
    widget = DocumentWidget(model)
    qtbot.addWidget(widget)
    return widget


def license_dock(widget: DocumentWidget) -> QtAds.CDockWidget:
    """A document's License dock.

    :param widget: the document's widget.
    :returns: the dock.
    """
    dock = widget.sub_docks._DocumentSubDocks__type_docks[LICENSE_DOCK_NAME]  # type: ignore[attr-defined]
    assert dock is not None
    return dock


def license_panel(widget: DocumentWidget) -> LicensePanel:
    """A document's License panel.

    :param widget: the document's widget.
    :returns: the panel.
    """
    panel = license_dock(widget).widget()
    assert isinstance(panel, LicensePanel)
    return panel


@fixture(name="asset")
def fixture_asset(qtbot: QtBot) -> DocumentWidget:
    """An asset's document widget, over no file.

    :param qtbot: pytest-qt fixture.
    :returns: the widget.
    """
    return widget_over(qtbot, RehuDocumentModel(RehuDocument({"type": "Asset", "sources": [{"title": "Rocks"}]})))


@fixture(name="tutorial")
def fixture_tutorial(qtbot: QtBot) -> DocumentWidget:
    """A tutorial's document widget, over no file.

    :param qtbot: pytest-qt fixture.
    :returns: the widget.
    """
    return widget_over(qtbot, RehuDocumentModel(RehuDocument({"type": "Tutorial", "sources": [{"title": "Foo"}]})))


def test_an_asset_has_a_license_dock_that_starts_hidden(asset: DocumentWidget) -> None:
    """**Test steps:**

    * build an asset's widget
    * verify the dock hosts a `LicensePanel`, is named and titled, its toggle is unchecked, and it has a floor
    """
    dock = license_dock(asset)

    assert isinstance(dock.widget(), LicensePanel)
    assert dock.objectName() == LICENSE_DOCK_NAME
    assert dock.windowTitle() == LICENSE_DOCK_TITLE
    assert dock.toggleViewAction().isChecked() is False
    assert dock.minimumSizeHint().height() == LICENSE_DOCK_MIN_HEIGHT


def test_the_license_toggle_is_on_the_toolbar_with_its_own_icon_and_edit_is_on_the_title_bar(
    asset: DocumentWidget,
) -> None:
    """**Test steps:**

    * verify the toolbar carries the dock's toggle, drawn from the license icon
    * verify the dock's title-bar actions are the panel's
    """
    dock = license_dock(asset)

    assert dock.toggleViewAction() in asset.findChildren(QToolBar)[0].actions()
    assert dock.toggleViewAction().icon().cacheKey() == themed_svg_icon(LICENSE_ICON_RESOURCE).cacheKey()
    assert dock.titleBarActions() == license_panel(asset).title_bar_actions


def test_only_an_asset_declares_the_license_dock(tutorial: DocumentWidget) -> None:
    """**Test steps:**

    * verify the declaration names the dock for the asset type alone
    * verify a tutorial built none
    """
    assert type_dock_names(ASSET_PLUGIN.key) == {LICENSE_DOCK_NAME}
    assert LICENSE_DOCK_NAME not in type_dock_names(TUTORIAL_PLUGIN.key)
    assert tutorial.sub_docks._DocumentSubDocks__license_panel is None  # type: ignore[attr-defined]
    assert tutorial.sub_docks._DocumentSubDocks__license_dock is None  # type: ignore[attr-defined]


def test_a_type_switch_builds_and_removes_the_dock_with_the_type(asset: DocumentWidget) -> None:
    """**Test steps:**

    * switch the asset to a tutorial and verify the dock and its panel are gone, the panel let go of
    * switch back and verify a new one is built
    """
    sub_docks = asset.sub_docks
    model = sub_docks.model
    first = license_panel(asset)

    model.resource_type = "tutorial"

    assert LICENSE_DOCK_NAME not in sub_docks._DocumentSubDocks__type_docks  # type: ignore[attr-defined]
    assert sub_docks._DocumentSubDocks__license_panel is None  # type: ignore[attr-defined]
    model.resource_type = "asset"
    assert license_panel(asset) is not first


def test_a_double_clicked_license_row_shows_the_dock_in_view_mode(qtbot: QtBot, tmp_path: Path) -> None:
    """**Test steps:**

    * open an asset over a real record, put the panel in edit mode and report the license row activated from the
      Files sub-dock
    * verify the dock is shown and current, and the panel reads rather than edits
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Pack")
    asset = widget_over(qtbot, opened(path))
    asset.model.resource_type = "asset"
    panel = license_panel(asset)
    panel.set_editing(True)
    assert panel.editing
    files = asset.sub_docks._DocumentSubDocks__files_dock.widget()  # type: ignore[attr-defined]
    assert isinstance(files, FilesView)

    files.license_activated.emit(path.with_suffix(".rehuterms"))

    dock = license_dock(asset)
    assert dock.toggleViewAction().isChecked() is True
    assert dock.isCurrentTab() is True  # type: ignore[attr-defined]
    assert panel.editing is False


def test_a_record_of_a_type_with_no_license_dock_hands_its_sidecar_to_the_system(
    tutorial: DocumentWidget, mocker: MockerFixture
) -> None:
    """**Test steps:**

    * report the license row activated on a tutorial, which has no such dock
    * verify the file was handed to the desktop services
    """
    opened_url = mocker.patch.object(QDesktopServices, "openUrl")
    files = tutorial.sub_docks._DocumentSubDocks__files_dock.widget()  # type: ignore[attr-defined]

    files.license_activated.emit(SIDECAR)

    url = opened_url.call_args.args[0]
    assert isinstance(url, QUrl)
    assert Path(url.toLocalFile()) == SIDECAR


def test_the_mode_is_kept_in_the_layout_and_restored_into_another_document(qtbot: QtBot, tmp_path: Path) -> None:
    """Whether the dock shows the editors is kept with the dock, as the notes' is.

    **Test steps:**

    * open an asset over a real record, put its panel in edit mode and save the document's state
    * verify the license dock's entry carries the panel's state
    * restore it into the widget of another record and verify its panel edits
    """
    first_path = tmp_path / "first" / "info.rehu"
    second_path = tmp_path / "second" / "info.rehu"
    for path in (first_path, second_path):
        path.parent.mkdir()
        write_record(path, "Pack")
    first = widget_over(qtbot, opened(first_path))
    second = widget_over(qtbot, opened(second_path))
    first.model.resource_type = "asset"
    second.model.resource_type = "asset"
    license_panel(first).set_editing(True)

    state = first.sub_docks.save_state()
    restored = second.sub_docks.restore_state(state)

    assert docks_carrying(state, "LicensePanel") == [LICENSE_DOCK_NAME]
    assert restored
    assert license_panel(second).editing


def test_closing_the_document_lets_the_panel_go_of_it(asset: DocumentWidget, mocker: MockerFixture) -> None:
    """**Test steps:**

    * detach the document's sub-docks
    * verify the panel was detached
    """
    detach = mocker.spy(LicensePanel, "detach")

    asset.sub_docks.detach()

    detach.assert_called_once()
