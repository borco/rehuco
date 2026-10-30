"""Tests for the one set of actions on a tutorial's video (#572, [[plugins#video-tree]], [[plugins#files-subdock]]).

The document is a mock: what is tested is which actions show for which row, how they are ticked and which call each
makes; the document's own writes are tested where they live.
"""

from unittest.mock import Mock

from pytest import fixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.documents.video_row_actions import VideoRowActions
from rehuco_core import ProgressEntry


@fixture(name="model")
def fixture_model() -> Mock:
    """A document that knows no video.

    :returns: the mock.
    """
    model = Mock(spec=RehuDocumentModel)
    model.progress_of.return_value = None
    model.is_favorite.return_value = False
    return model


@fixture(name="actions")
def fixture_actions(qtbot: QtBot, model: Mock) -> VideoRowActions:
    """The actions over the mock.

    :param qtbot: pytest-qt fixture.
    :param model: the document.
    :returns: the actions.
    """
    del qtbot
    return VideoRowActions(model)


def shown(actions: VideoRowActions) -> list[str]:
    """The actions that apply now.

    :param actions: the set.
    :returns: their texts, in order.
    """
    return [action.text() for action in actions.actions if action.isVisible()]


def test_nothing_shows_for_a_row_that_is_no_video(actions: VideoRowActions) -> None:
    """**Test steps:**

    * aim the actions at no video
    * verify none shows
    """
    actions.show_for(None, missing=False)

    assert shown(actions) == []
    assert actions.any_visible is False


def test_a_present_video_offers_favorite_and_viewed_and_a_missing_one_forget_too(actions: VideoRowActions) -> None:
    """**Test steps:**

    * aim the actions at a present video, then a missing one
    * verify the first offers Favorite and Viewed and the second Forget as well
    """
    actions.show_for("a.mp4", missing=False)
    assert shown(actions) == ["Favorite", "Viewed"]
    assert actions.any_visible is True

    actions.show_for("a.mp4", missing=True)
    assert shown(actions) == ["Favorite", "Viewed", "Forget"]


def test_the_toggles_are_ticked_as_the_video_is(actions: VideoRowActions, model: Mock) -> None:
    """**Test steps:**

    * aim at a starred, viewed video and verify both are ticked
    * aim at one that is neither and verify both are not
    """
    model.is_favorite.return_value = True
    model.progress_of.return_value = ProgressEntry(10.0, 100.0, True, 0)
    actions.show_for("a.mp4", missing=False)
    assert (actions.favorite_action.isChecked(), actions.viewed_action.isChecked()) == (True, True)

    model.is_favorite.return_value = False
    model.progress_of.return_value = None
    actions.show_for("b.mp4", missing=False)
    assert (actions.favorite_action.isChecked(), actions.viewed_action.isChecked()) == (False, False)


def test_favorite_stars_and_unstars_the_video(actions: VideoRowActions, model: Mock) -> None:
    """**Test steps:**

    * trigger Favorite twice
    * verify the document was told to star the video, then to unstar it
    """
    actions.show_for("a.mp4", missing=False)

    actions.favorite_action.trigger()
    actions.favorite_action.trigger()

    assert [call.kwargs for call in model.record_notes.call_args_list] == [
        {"favorites": {"a.mp4": True}},
        {"favorites": {"a.mp4": False}},
    ]


def test_viewed_records_the_flag_at_the_position_the_video_was_left(actions: VideoRowActions, model: Mock) -> None:
    """**Test steps:**

    * trigger Viewed on a video left at 30 seconds, then on one never opened
    * verify the first keeps its position and the second starts at zero
    """
    model.progress_of.return_value = ProgressEntry(30.0, 100.0, False, 0)
    actions.show_for("a.mp4", missing=False)
    actions.viewed_action.trigger()
    model.record_progress.assert_called_once_with("a.mp4", 30.0, None, viewed=True)

    model.progress_of.return_value = None
    model.record_progress.reset_mock()
    actions.show_for("b.mp4", missing=False)
    actions.viewed_action.trigger()
    model.record_progress.assert_called_once_with("b.mp4", 0.0, None, viewed=True)


def test_forget_forgets_the_missing_video(actions: VideoRowActions, model: Mock) -> None:
    """**Test steps:**

    * trigger Forget on a missing video
    * verify the document forgot it
    """
    actions.show_for("gone.mp4", missing=True)

    actions.forget_action.trigger()

    model.forget_progress.assert_called_once_with("gone.mp4")


def test_forget_refuses_a_present_video_whatever_surface_triggered_it(actions: VideoRowActions, model: Mock) -> None:
    """A title-bar button may be clicked where the action is hidden; the one destructive command still checks.

    **Test steps:**

    * aim the actions at a present video and trigger the hidden Forget
    * verify the document forgot nothing
    """
    actions.show_for("a.mp4", missing=False)

    actions.forget_action.trigger()

    model.forget_progress.assert_not_called()
