"""Tests for a tutorial's tree dock in its document's sub-docks: where it sits, how it follows the player, and what a
double-click in it does (#572, [[plugins#video-tree]])."""

# astroid reads the sub-docks' name-to-dock dict's values as signals, and every call on a dock then fails
# pylint: disable=no-member

import cbor2
import PySide6QtAds as QtAds
from borco_pyside.theming import themed_svg_icon
from PySide6.QtWidgets import QToolBar, QToolButton
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.document_fields import VIEWER_DESCRIPTION_TAB
from rehuco_agent.documents.document_sub_docks import (
    TREE_DOCK_MIN_HEIGHT,
    TREE_DOCK_NAME,
    TREE_DOCK_TITLE,
    TREE_ICON_RESOURCE,
)
from rehuco_agent.documents.document_widget import DocumentWidget
from rehuco_agent.documents.player_view import PlayerView
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.documents.video_tree_view import VideoTreeView
from rehuco_core import RehuDocument

from .test_document_sub_docks_player import fixture_pack, player_dock  # noqa: F401  # pylint: disable=unused-import
from .test_document_widget import layout_dock_entries


@fixture(name="model")
def fixture_model() -> RehuDocumentModel:
    """A view-model over a tutorial.

    :returns: the model.
    """
    return RehuDocumentModel(RehuDocument({"type": "Tutorial", "sources": [{"title": "Foo", "primary": True}]}))


@fixture(name="widget")
def fixture_widget(qtbot: QtBot, model: RehuDocumentModel) -> DocumentWidget:
    """A tutorial's document widget.

    :param qtbot: pytest-qt fixture.
    :param model: the document.
    :returns: the widget.
    """
    widget = DocumentWidget(model)
    qtbot.addWidget(widget)
    return widget


def tree_dock(widget: DocumentWidget) -> QtAds.CDockWidget:
    """A document's tree dock.

    :param widget: the document's widget.
    :returns: the dock.
    """
    dock = widget.sub_docks._DocumentSubDocks__type_docks[TREE_DOCK_NAME]  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert dock is not None
    return dock


def tree_view(widget: DocumentWidget) -> VideoTreeView:
    """A document's tree view.

    :param widget: the document's widget.
    :returns: the view.
    """
    view = tree_dock(widget).widget()
    assert isinstance(view, VideoTreeView)
    return view


def toolbar_of(widget: DocumentWidget) -> QToolBar:
    """A document's toolbar.

    :param widget: the document's widget.
    :returns: the toolbar.
    """
    return widget.findChildren(QToolBar)[0]


def test_a_tutorial_has_a_tree_dock_that_starts_hidden(widget: DocumentWidget) -> None:
    """**Test steps:**

    * build a tutorial's widget
    * verify the dock hosts a `VideoTreeView`, is named and titled, its toggle is unchecked, and it has a floor
    """
    dock = tree_dock(widget)

    assert isinstance(dock.widget(), VideoTreeView)
    assert dock.objectName() == TREE_DOCK_NAME
    assert dock.windowTitle() == TREE_DOCK_TITLE
    assert dock.toggleViewAction().isChecked() is False
    assert dock.widget().parentWidget() is dock
    assert dock.minimumSizeHint().height() == TREE_DOCK_MIN_HEIGHT


def test_the_tree_toggle_follows_the_players_with_its_own_icon(widget: DocumentWidget) -> None:
    """**Test steps:**

    * verify the toolbar carries the tree's toggle right after the player's
    * verify the toggle's icon was built from the tree's own icon
    """
    action = tree_dock(widget).toggleViewAction()
    actions = toolbar_of(widget).actions()

    assert actions.index(action) == actions.index(player_dock(widget).toggleViewAction()) + 1
    assert action.icon().cacheKey() == themed_svg_icon(TREE_ICON_RESOURCE).cacheKey()


def test_the_trees_row_actions_are_on_its_title_bar(widget: DocumentWidget) -> None:
    """**Test steps:**

    * verify the dock's title-bar actions are the view's Favorite, Viewed and Forget
    """
    assert tree_dock(widget).titleBarActions() == tree_view(widget).title_bar_actions


def test_a_reference_pack_has_no_tree(
    widget: DocumentWidget,
    pack: DocumentWidget,  # noqa: F811
) -> None:
    """**Test steps:**

    * build a tutorial's and a reference pack's widgets
    * verify only the tutorial built a tree, and the pack's toolbar carries no toggle titled for it
    """
    assert isinstance(tree_view(widget), VideoTreeView)
    assert pack.sub_docks._DocumentSubDocks__tree_view is None  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert TREE_DOCK_TITLE not in [action.text() for action in toolbar_of(pack).actions()]


def test_a_layout_that_never_names_the_tree_puts_it_back_hidden(widget: DocumentWidget) -> None:
    """**Test steps:**

    * save the widget's state with the tree open, then drop its entry from the layout
    * restore it
    * verify it restored, the tree is hidden, and it sits in the Description View's area
    """
    tree_dock(widget).toggleView(True)
    payload = cbor2.loads(widget.save_state())
    for entry in layout_dock_entries(payload["dock_manager"]):
        if entry["name"] == TREE_DOCK_NAME:
            entry["name"] = "no such dock"

    assert widget.restore_state(cbor2.dumps(payload)) is True

    description = widget.sub_docks._DocumentSubDocks__viewer_docks[VIEWER_DESCRIPTION_TAB]  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert tree_dock(widget).toggleViewAction().isChecked() is False
    assert tree_dock(widget).dockAreaWidget() is description.dockAreaWidget()  # pylint: disable=no-member


def test_a_video_double_clicked_in_the_tree_is_played_with_its_position_and_the_player_shown(
    widget: DocumentWidget, mocker: MockerFixture
) -> None:
    """**Test steps:**

    * have the tree report a video, then a bookmark with a time
    * verify the player dock was shown and made current
    * verify the player was told to jump to each, the bookmark with its time
    """
    jump = mocker.patch.object(PlayerView, "jump")
    dock = player_dock(widget)

    tree_view(widget).video_activated.emit("02.mp4", None)
    tree_view(widget).video_activated.emit("03.mp4", 65.0)

    assert dock.toggleViewAction().isChecked() is True
    assert dock.isCurrentTab() is True  # type: ignore[attr-defined]
    assert [tuple(item.args) for item in jump.call_args_list] == [("02.mp4", None), ("03.mp4", 65.0)]


def test_the_tree_marks_the_video_the_player_selects(widget: DocumentWidget) -> None:
    """**Test steps:**

    * have the player report a selected video, then none
    * verify the tree's marker follows
    """
    player = player_dock(widget).widget()
    assert isinstance(player, PlayerView)
    tree = tree_view(widget).tree

    player.video_changed.emit("a.mp4")
    assert tree.current_key == "a.mp4"

    player.video_changed.emit(None)
    assert tree.current_key is None


def test_a_type_switch_away_takes_the_tree_with_it(widget: DocumentWidget, model: RehuDocumentModel) -> None:
    """**Test steps:**

    * switch the tutorial to a reference pack
    * verify the tree and its toggle are gone
    * switch back and verify a new tree was built, hidden
    """
    toggle = tree_dock(widget).toggleViewAction()

    model.resource_type = "reference_images"

    assert widget.sub_docks._DocumentSubDocks__tree_view is None  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert toggle not in toolbar_of(widget).actions()

    model.resource_type = "tutorial"

    assert tree_dock(widget).toggleViewAction().isChecked() is False
    assert isinstance(tree_dock(widget).widget(), VideoTreeView)


def test_the_title_bar_shows_only_the_actions_that_apply(widget: DocumentWidget, qtbot: QtBot) -> None:
    """QtAds' buttons do not follow their actions' visibility on their own (#572).

    **Test steps:**

    * show the tree dock with nothing selected
    * verify no action's button is shown on its title bar
    * aim the actions at a present video and verify Favorite and Viewed show and Forget does not
    """
    widget.show()
    dock = tree_dock(widget)
    dock.toggleView(True)
    qtbot.waitUntil(lambda: dock.dockAreaWidget() is not None and dock.isCurrentTab())  # type: ignore[attr-defined]
    actions = tree_view(widget).row_actions

    def shown() -> list[str]:
        area = dock.dockAreaWidget()
        assert area is not None
        buttons = area.titleBar().findChildren(QToolButton)
        return [b.defaultAction().text() for b in buttons if b.defaultAction() in actions.actions and not b.isHidden()]

    assert shown() == []

    actions.show_for("a.mp4", missing=False)
    assert shown() == ["Favorite", "Viewed"]

    actions.show_for("gone.mp4", missing=True)
    assert shown() == ["Favorite", "Viewed", "Forget"]
