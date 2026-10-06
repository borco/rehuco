"""Tests for DocumentSubDocks as a host other than `DocumentWidget` uses it (#380): built into a bare
manager, torn down, and rebuilt there for another document.

Everything the sub-docks do inside a document -- the dock set, the toolbar, the banner, layouts -- is
covered through `DocumentWidget` in ``test_document_widget.py``; these tests cover what only a reusable
host needs: that a teardown leaves the host as it found it and lets go of the model, and that the
default layouts follow the namespace the host names.
"""

from pathlib import Path
from typing import Final

import PySide6QtAds as QtAds
from borco_pyside.qtads import QtAdsFocusTracker
from borco_pyside.widgets import MessageBanner
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.app_logging import shared_log_bridge
from rehuco_agent.dock_maximize import attach_maximize_handler
from rehuco_agent.documents.document_fields import EDITOR_MAIN_TAB
from rehuco_agent.documents.document_sub_docks import CONTENT_IMAGES_DOCK_NAME, DocumentSubDocks, SubDockHost
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.settings.default_layout_settings import (
    shared_default_layout_settings,
    shared_default_layout_settings_in,
)
from rehuco_core import TUTORIAL_PLUGIN, RehuDocument

from rehuco_agent_tests.qt_connections import flush_deferred_deletes, receivers

DOCUMENT_PATH: Final = Path("/fake/info.rehu")
SCREENSHOT: Final = Path("/fake/info00.jpg")

OWN_NAMESPACE: Final = "rehuco_layout"
"""A layout namespace other than the Documents dock's, as the Root Catalog dock will name one (#381)."""


# region Sample classes
class BareHost(QWidget):
    """A host that is not a `DocumentWidget`: a banner over a manager, in a plain widget, with the
    manager's focus tracker and maximize toggle -- what the Root Catalog dock lends (#381)."""

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        self.banner: Final = MessageBanner(self)
        layout.addWidget(self.banner)
        self.dock_manager: Final = QtAds.CDockManager(self)
        layout.addWidget(self.dock_manager)
        self.lent: Final = SubDockHost(
            self,
            self.dock_manager,
            QtAdsFocusTracker(self.dock_manager),
            attach_maximize_handler(self.dock_manager),
            self.banner,
        )


# endregion


# region fixtures
@fixture
def host(qtbot: QtBot) -> BareHost:
    """A bare host, registered for teardown."""
    host = BareHost()
    qtbot.addWidget(host)
    return host


@fixture
def model() -> RehuDocumentModel:
    """A tutorial's view-model, with a path -- so its log surface is attached under one (#200)."""
    return RehuDocumentModel(
        RehuDocument({"type": "Tutorial", "sources": [{"title": "Foo", "primary": True}]}, DOCUMENT_PATH)
    )


@fixture
def other_model() -> RehuDocumentModel:
    """A reference pack's view-model -- a type whose dock set differs from a tutorial's (#320)."""
    return RehuDocumentModel(RehuDocument({"type": "ReferenceImages", "sources": [{"title": "Pack", "primary": True}]}))


# endregion


# region DocumentSubDocks tests
def test_a_teardown_takes_every_dock_and_action_back_out_of_the_host(
    host: BareHost, other_model: RehuDocumentModel
) -> None:
    """A teardown leaves the host as it found it: no dock in its manager -- the type's own included --
    no action on its widget, no row on its banner.

    **Test steps:**

    * build sub-docks into a bare host over a path-less reference pack -- a type dock of its own and no
      log scope -- and fail a rename, so the banner has a row
    * verify the manager, the widget and the banner each gained something
    * tear down and run the deferred deletes
    * verify the manager has no docks, the widget no actions, and the banner no rows
    """
    sub_docks = DocumentSubDocks(other_model, host.lent)
    other_model.rename_error = "could not rename"
    assert host.dock_manager.dockWidgetsMap()
    assert host.actions()
    assert host.banner.findChildren(QLabel)

    sub_docks.teardown()
    flush_deferred_deletes()

    assert not host.dock_manager.dockWidgetsMap()
    assert not host.actions()
    assert not host.banner.findChildren(QLabel)


def test_a_teardown_lets_go_of_every_model_connection(host: BareHost, model: RehuDocumentModel) -> None:
    """Nothing the sub-docks connected to the model survives a teardown -- the model may outlive them,
    held by a registry or a Documents dock (#375).

    **Test steps:**

    * count the model's receivers per signal
    * build sub-docks over it, open a hidden dock, tear down and run the deferred deletes
    * verify every signal is back to its count before the build
    """
    before = receivers(model)
    sub_docks = DocumentSubDocks(model, host.lent)
    sub_docks.toggle_action(EDITOR_MAIN_TAB).trigger()

    sub_docks.teardown()
    flush_deferred_deletes()

    assert receivers(model) == before


def test_a_teardown_detaches_the_log_surface_from_its_scope(
    mocker: MockerFixture, host: BareHost, model: RehuDocumentModel
) -> None:
    """A teardown takes the document's log surface off the bridge it was attached to under the
    document's path (#200), which would otherwise keep feeding a surface no dock shows.

    **Test steps:**

    * build sub-docks over a model with a path, spying on the log surface's detach
    * tear down
    * verify the surface was detached from the shared bridge
    """
    sub_docks = DocumentSubDocks(model, host.lent)
    detach_from = mocker.spy(sub_docks.log_widget, "detach_from")

    sub_docks.teardown()

    detach_from.assert_called_once_with(shared_log_bridge())


def test_a_teardown_closes_an_open_image_viewer(host: BareHost, model: RehuDocumentModel) -> None:
    """A teardown closes the document's maximized image viewer (#160): it is parented to the host, which
    outlives the sub-docks, so nothing else would.

    **Test steps:**

    * build sub-docks and open a screenshot maximized
    * tear down
    * verify the viewer is hidden
    """
    sub_docks = DocumentSubDocks(model, host.lent)
    sub_docks._DocumentSubDocks__on_image_activated(SCREENSHOT)  # type: ignore[attr-defined]  # pylint: disable=protected-access
    viewer = sub_docks._DocumentSubDocks__image_viewer  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert viewer is not None

    sub_docks.teardown()

    assert viewer.isHidden()


def test_a_model_change_after_teardown_reaches_nothing_torn_down(host: BareHost, model: RehuDocumentModel) -> None:
    """A teardown severs the model at once, not when the deferred deletes run: an edit made in between
    reaches nothing of the torn-down sub-docks.

    **Test steps:**

    * build sub-docks over a clean model and keep their Save action
    * tear down, then edit the model before the deferred deletes run
    * verify the kept Save action stayed disabled
    """
    sub_docks = DocumentSubDocks(model, host.lent)
    save_action = sub_docks.save_action

    sub_docks.teardown()
    model.title = "Edited"

    assert save_action.isEnabled() is False


def test_a_kept_revert_action_reverts_nothing_after_teardown(
    mocker: MockerFixture, host: BareHost, model: RehuDocumentModel
) -> None:
    """The Revert action outlives a teardown until its deferred delete, and must not reach the model in that
    gap -- a preview dock has moved on to another document by then (#39).

    **Test steps:**

    * stand in for the model's revert, build sub-docks over it and keep their Revert action, enabled
    * tear down, then trigger the kept action before the deferred deletes run
    * verify the model was not reverted
    """
    revert = mocker.patch.object(model, "revert")
    sub_docks = DocumentSubDocks(model, host.lent)
    revert_action = sub_docks.revert_action
    revert_action.setEnabled(True)

    sub_docks.teardown()
    revert_action.trigger()

    revert.assert_not_called()


def test_a_rebuild_in_the_same_manager_binds_only_the_new_document(
    host: BareHost, model: RehuDocumentModel, other_model: RehuDocumentModel
) -> None:
    """The same manager hosts another document's sub-docks after a teardown -- the Root Catalog dock's
    current resource changing (#381) -- with the new type's dock set and nothing of the old model.

    **Test steps:**

    * build sub-docks over a tutorial, tear down, run the deferred deletes
    * build sub-docks over a reference pack in the same host
    * verify the manager holds the pack's Content Images dock, and only one dock per name
    * edit the tutorial and verify the pack's Save action stayed disabled
    """
    DocumentSubDocks(model, host.lent).teardown()
    flush_deferred_deletes()

    rebuilt = DocumentSubDocks(other_model, host.lent)
    model.title = "Edited"

    names = [dock.objectName() for dock in host.dock_manager.dockWidgetsMap().values()]
    assert CONTENT_IMAGES_DOCK_NAME in names
    assert len(names) == len(set(names))
    assert rebuilt.model is other_model
    assert rebuilt.save_action.isEnabled() is False


def test_a_layout_namespace_keeps_its_own_default_layouts(host: BareHost, model: RehuDocumentModel) -> None:
    """Sub-docks built under a namespace of their own save and reset their type's default there, and
    never touch the Documents dock's defaults (#380).

    **Test steps:**

    * seed a Documents default for the tutorial type
    * build sub-docks under another namespace and save their layout as the tutorial default
    * verify it landed under that namespace and the Documents default is unchanged
    * reset it and verify only that namespace's default was cleared
    """
    documents = shared_default_layout_settings()
    documents.states[TUTORIAL_PLUGIN.key] = b"documents blob"  # pylint: disable=unsupported-assignment-operation
    sub_docks = DocumentSubDocks(model, host.lent, layout_namespace=OWN_NAMESPACE)
    own = shared_default_layout_settings_in(OWN_NAMESPACE)

    sub_docks._DocumentSubDocks__save_default_layout_action.trigger()  # type: ignore[attr-defined]  # pylint: disable=protected-access

    assert own.states == {TUTORIAL_PLUGIN.key: sub_docks.save_layout_state()}
    assert documents.states == {TUTORIAL_PLUGIN.key: b"documents blob"}

    sub_docks._DocumentSubDocks__reset_default_layout_action.trigger()  # type: ignore[attr-defined]  # pylint: disable=protected-access

    assert not own.states
    assert documents.states == {TUTORIAL_PLUGIN.key: b"documents blob"}


def test_the_closed_dock_size_workaround_runs_in_a_bare_host(host: BareHost, model: RehuDocumentModel) -> None:
    """A dock toggled off and on in a host that is not a `DocumentWidget` still stashes and restores its
    splitter sizes ([[packaging-deployment#qml-regression]]).

    **Test steps:**

    * build sub-docks into a bare host
    * show the Main Editor (a document opens as a reader, #299), hide it, show it again
    * verify it is shown and its sizes were stashed under its name
    """
    sub_docks = DocumentSubDocks(model, host.lent)
    toggle = sub_docks.toggle_action(EDITOR_MAIN_TAB)

    toggle.trigger()
    toggle.trigger()
    toggle.trigger()

    assert toggle.isChecked() is True
    stashed = sub_docks._DocumentSubDocks__stashed_sizes  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert "editor:Main Editor" in stashed


# endregion
