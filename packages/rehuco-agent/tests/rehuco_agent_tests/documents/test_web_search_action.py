"""Tests for WebSearchAction and its place on the document toolbar (#388)."""

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import QApplication, QToolBar
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.document_widget import DocumentWidget
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.documents.web_search_action import EMPTY_TOOLTIP, WebSearchAction
from rehuco_agent.settings.web_search_settings import DEFAULT_ENGINES, SearchEngine, WebSearchSettings
from rehuco_core import RehuDocument, TaskQueue

SLUG = "SomePublisher - SomeTitle - SomeAuthor (300+) [2025]"
LIBRARY = Path("/library")
DOCUMENT = {"type": "Tutorial", "sources": [{"title": "Unrelated Title", "primary": True}]}
QUERY = "SomePublisher SomeTitle SomeAuthor 300+ 2025"


@fixture(name="model")
def fixture_model() -> RehuDocumentModel:
    """A directory-scoped document whose folder is named :data:`SLUG`, with a different title."""
    return RehuDocumentModel(RehuDocument(DOCUMENT, LIBRARY / SLUG / "info.rehu"))


@fixture(name="settings")
def fixture_settings() -> WebSearchSettings:
    """Unloaded engine settings: the shipped list, nothing chosen."""
    return WebSearchSettings()


@fixture(name="search")
def fixture_search(qapp: QApplication, model: RehuDocumentModel, settings: WebSearchSettings) -> WebSearchAction:
    """The action over :data:`SLUG`; a `QAction` needs the application to exist."""
    del qapp
    return WebSearchAction(model, settings)


def search_action_of(widget: DocumentWidget) -> tuple[QToolBar, QAction]:
    """The document toolbar and its Search the Web action.

    :param widget: the document widget.
    :returns: the toolbar and the action on it.
    """
    toolbar = widget.findChildren(QToolBar)[0]
    return toolbar, next(action for action in toolbar.actions() if action.text() == "Search the Web")


def test_the_tooltip_names_the_query_and_the_action_is_enabled(search: WebSearchAction) -> None:
    """The tooltip shows what a click will search for.

    **Test steps:**

    * build the action over a document whose folder and title differ
    * verify it is enabled and its tooltip carries the query
    """
    assert search.query == QUERY
    assert search.action.isEnabled()
    assert search.action.toolTip() == f"Search the web for: {QUERY}"


def test_triggering_opens_the_chosen_engine_with_the_encoded_query(
    mocker: MockerFixture, search: WebSearchAction, settings: WebSearchSettings
) -> None:
    """A click opens the chosen engine's URL, with the query encoded into the template.

    **Test steps:**

    * mock ``QDesktopServices.openUrl``
    * trigger with the default engine, then make another engine the active one and trigger again
    * verify both URLs
    """
    opened = mocker.patch.object(QDesktopServices, "openUrl")
    search.action.trigger()
    settings.engines = (
        DEFAULT_ENGINES[0]._replace(active=False),
        SearchEngine("Mine", "https://example.com/find?q={query}", active=True),
    )
    search.action.trigger()
    assert [call.args[0] for call in opened.call_args_list] == [
        QUrl("https://www.google.com/search?q=SomePublisher+SomeTitle+SomeAuthor+300%2B+2025"),
        QUrl("https://example.com/find?q=SomePublisher+SomeTitle+SomeAuthor+300%2B+2025"),
    ]


def test_searching_with_nothing_to_search_for_opens_nothing(mocker: MockerFixture, qapp: QApplication) -> None:
    """The action is disabled then, and a direct call is still a no-op.

    **Test steps:**

    * mock ``QDesktopServices.openUrl`` and build the action over a path-less document
    * call ``search`` and verify no URL was opened
    """
    del qapp
    opened = mocker.patch.object(QDesktopServices, "openUrl")
    WebSearchAction(RehuDocumentModel(RehuDocument(DOCUMENT)), WebSearchSettings()).search()
    opened.assert_not_called()


def test_a_file_scoped_document_searches_its_stem() -> None:
    """A standalone ``foo.rehu`` is named by its stem, not by its folder.

    **Test steps:**

    * build the action over ``/library/Books/My (Great) Pack.rehu``
    * verify the query is the stem's words
    """
    model = RehuDocumentModel(RehuDocument(DOCUMENT, LIBRARY / "Books" / "My (Great) Pack.rehu"))
    assert WebSearchAction(model, WebSearchSettings()).query == "My Great Pack"


def test_a_document_without_a_location_disables_the_action_until_it_gets_one(
    search: WebSearchAction,
) -> None:
    """The title plays no part: a path-less document has nothing to search for, and gaining a path
    (a first save, a rename) enables the action and updates the tooltip.

    **Test steps:**

    * build the action over a path-less document with a title and verify it is disabled
    * give it a path and verify the tooltip follows
    * give it a punctuation-only folder name and verify it is disabled again
    """
    model = RehuDocumentModel(RehuDocument(DOCUMENT))
    pathless = WebSearchAction(model, WebSearchSettings())
    assert not pathless.action.isEnabled()
    assert pathless.action.toolTip() == EMPTY_TOOLTIP
    model.path = LIBRARY / "New (Slug)" / "info.rehu"
    assert pathless.action.isEnabled()
    assert pathless.action.toolTip() == "Search the web for: New Slug"
    model.path = LIBRARY / " - () " / "info.rehu"
    assert not pathless.action.isEnabled()
    assert search.action.isEnabled()


def test_it_stays_enabled_on_a_locked_document(qtbot: QtBot) -> None:
    """Reading the location changes nothing, so a locked document keeps the action.

    **Test steps:**

    * build a widget over a legacy, locked document
    * verify the action is enabled
    """
    model = RehuDocumentModel(RehuDocument(DOCUMENT, LIBRARY / SLUG / "info.tc", legacy_tc=True))
    widget = DocumentWidget(model)
    qtbot.addWidget(widget)
    assert model.locked
    assert search_action_of(widget)[1].isEnabled()


def test_it_is_the_last_action_before_the_dock_toggles_separator(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The action's position is the rule: immediately before the separator, with and without the
    checksum actions before it.

    **Test steps:**

    * build a widget with no queue, then one with a queue
    * verify the action's successor on the toolbar is a separator, and its predecessor is Generate when
      the checksum actions exist
    """
    plain = DocumentWidget(model)
    qtbot.addWidget(plain)
    toolbar, action = search_action_of(plain)
    assert toolbar.actions()[toolbar.actions().index(action) + 1].isSeparator()

    queue = TaskQueue()
    checked = DocumentWidget(
        RehuDocumentModel(RehuDocument({"type": "Tutorial", "sources": [{"title": "T"}]})), task_queue=queue
    )
    qtbot.addWidget(checked)
    try:
        toolbar, action = search_action_of(checked)
        actions = toolbar.actions()
        assert actions[actions.index(action) + 1].isSeparator()
        assert checked.checksum_actions is not None
        assert actions[actions.index(action) - 1] is checked.checksum_actions.generate_action
    finally:
        checked.detach()
        queue.shutdown()
