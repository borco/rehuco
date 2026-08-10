"""Tests for SettingsDialog: the filterable category tree + per-category stacked page shell."""

from typing import Any

from borco_pyside.widgets import WrappingCheckBox
from PySide6.QtCore import QModelIndex
from PySide6.QtWidgets import QAbstractScrollArea, QFrame, QLabel, QLineEdit, QScrollArea, QVBoxLayout, QWidget
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.document_dock import DIRTY_DOCK_MARKER
from rehuco_agent.settings.settings_dialog_settings import SettingsDialogSettings
from rehuco_agent.settings.ui import settings_dialog
from rehuco_agent.settings.ui.settings_dialog import SettingsDialog


# region fixtures
# Mirrors test_descriptions_page.py's (and conftest.py's) FakeSettings exactly -- kept as a
# separate copy rather than a shared import, matching this codebase's settings-test convention.
# pylint: disable=duplicate-code
class FakeSettings:  # pylint: disable=invalid-name,missing-function-docstring,redefined-builtin
    """A minimal in-memory stand-in for the ``QSettings`` group/value API (see
    ``test_markdown_rendering_settings.py`` for the full rationale)."""

    def __init__(self) -> None:
        self.__data: dict[str, Any] = {}
        self.__group = ""

    def beginGroup(self, name: str) -> None:  # noqa: N802
        self.__group = f"{name}/"

    def endGroup(self) -> None:  # noqa: N802
        self.__group = ""

    def setValue(self, key: str, value: Any) -> None:  # noqa: N802
        self.__data[self.__group + key] = value

    def value(self, key: str, default: Any = None, type: Any = None) -> Any:  # noqa: A002, N802
        del type
        return self.__data.get(self.__group + key, default)


# pylint: enable=duplicate-code


@fixture(autouse=True)
def fake_persistent_settings(mocker: MockerFixture) -> FakeSettings:
    """Stand in for ``persistent_settings()`` so the dialog's toggle save/load never touch real
    storage (overriding conftest's own default for this module, #76).

    :returns: the in-memory stand-in the dialog loads its toggles from and saves them to.
    """
    fake = FakeSettings()
    mocker.patch.object(settings_dialog, "persistent_settings", return_value=fake)
    return fake


# endregion


# region Sample classes
class FakePage(QWidget):
    """A minimal `SettingsPage` stand-in for exercising `SettingsDialog` without a real page.

    Builds one top-level ``QFrame`` per entry in ``groups`` (each holding a ``QLabel`` for every
    term), so the dialog's introspecting `SettingsFrameFilter` has real frames to show/hide.
    """

    def __init__(self, title: str, groups: list[list[str]] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__title = title
        self.dirty = False
        self.save_calls = 0
        self.drop_calls = 0
        self.frames: list[QFrame] = []
        # one per frame, so a test can make a specific frame's SettingsFrameFilter.dirty_frames()
        # baseline diverge without the page as a whole knowing anything about it (#77)
        self.edits: list[QLineEdit] = []

        # kept as an attribute, not a local: a test staging a filling block sets its stretch here, the
        # way a real page's controller does, and QWidget.layout() answers the untyped base class
        self.main_layout = QVBoxLayout(self)
        layout = self.main_layout
        for terms in groups or []:
            frame = QFrame(self)
            frame_layout = QVBoxLayout(frame)
            for term in terms:
                frame_layout.addWidget(QLabel(term, frame))
            edit = QLineEdit(frame)
            frame_layout.addWidget(edit)
            layout.addWidget(frame)
            self.frames.append(frame)
            self.edits.append(edit)

    @property
    def title(self) -> str:
        """This page's category-tree label."""
        return self.__title

    def is_dirty(self) -> bool:
        """Whatever :attr:`dirty` was last set to -- ``False`` unless a test opts in."""
        return self.dirty

    def save_changes(self) -> None:
        """Record that a save was requested, and settle -- the same as a real page's is_dirty()
        reporting clean once its staged edits match what was just saved."""
        self.save_calls += 1
        self.dirty = False

    def drop_changes(self) -> None:
        """Record that a drop was requested, and settle -- the same as a real page's is_dirty()
        reporting clean once its edits are reverted."""
        self.drop_calls += 1
        self.dirty = False


# endregion


def dialog_ui(dialog: SettingsDialog) -> object:
    """Read the dialog's private ``.ui`` object, for reaching its tree/stack/toolbar in tests.

    :param dialog: the dialog to inspect.
    :returns: the generated ``Ui_SettingsDialog`` instance.
    """
    return dialog._SettingsDialog__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access


def auto_apply_check_box(dialog: SettingsDialog) -> WrappingCheckBox:
    """The dialog's auto-apply toggle (#77).

    Not part of ``Ui_SettingsDialog``: a ``QToolBar`` can't host a plain widget from Designer, so this
    one is built and added to the toolbar in code (see `SettingsDialog.__init__`) rather than promoted
    in the ``.ui``.

    :param dialog: the dialog to inspect.
    :returns: the auto-apply checkbox.
    """
    return dialog._SettingsDialog__auto_apply_check_box  # type: ignore[attr-defined]  # pylint: disable=protected-access


def refresh_dirty_state(dialog: SettingsDialog) -> None:
    """Force the dialog to recompute every dirty-derived bit of UI (badges, frame highlights,
    Apply/Reset enablement) (#77).

    Real usage never needs this call directly: it happens on every show and on a short poll tick
    while the dialog is visible (`SettingsDialog.showEvent`/``__poll_dirty_state``). Tests mutate a
    `FakePage`'s ``dirty`` flag straight through, with no signal of its own to ride in on, so this is
    what stands in for "some time has passed and a poll tick already ran."

    :param dialog: the dialog to refresh.
    """
    dialog._SettingsDialog__refresh_dirty_ui()  # type: ignore[attr-defined]  # pylint: disable=protected-access


def poll_dirty_state(dialog: SettingsDialog) -> None:
    """Run one tick of the dialog's dirty-state poll, as its own timer would (#77).

    Unlike :func:`refresh_dirty_state`, this also auto-applies any page found dirty while the
    dialog's auto-apply checkbox is on -- exercising that path without waiting on the real
    :class:`~PySide6.QtCore.QTimer` or a real show event.

    :param dialog: the dialog to tick.
    """
    dialog._SettingsDialog__poll_dirty_state()  # type: ignore[attr-defined]  # pylint: disable=protected-access


def page_scroll_areas(dialog: SettingsDialog) -> list[QScrollArea]:
    """Every scroll area in the stack, in order -- one per page, plus one per group column (#229, #230).

    The stack also holds the plain no-match blank page, which is not a scroll area and is skipped here
    (#230).

    :param dialog: the dialog whose stack to read.
    :returns: the scroll areas, in stack order.
    """
    stack = dialog_ui(dialog).page_stack  # type: ignore[attr-defined]
    widgets = [stack.widget(index) for index in range(stack.count())]
    return [widget for widget in widgets if isinstance(widget, QScrollArea)]


def stacked_pages(dialog: SettingsDialog) -> list[QWidget]:
    """Every registered page, in stack order, read out of the scroll area it is shown through (#229).

    A group's own column is a scroll area too, but holds a container rather than a registered page, so
    only the areas whose widget is a page are read (#230).

    :param dialog: the dialog whose stack to read.
    :returns: the pages themselves, not the scroll areas holding them.
    """
    pages = [area.widget() for area in page_scroll_areas(dialog)]
    return [page for page in pages if page is not None and hasattr(page, "title")]


def current_page(dialog: SettingsDialog) -> QWidget | None:
    """The page currently shown, read out of the scroll area it is shown through (#229).

    :param dialog: the dialog whose stack to read.
    :returns: the shown page, or ``None`` while the stack is empty or showing the no-match blank (#230).
    """
    area = dialog_ui(dialog).page_stack.currentWidget()  # type: ignore[attr-defined]
    return area.widget() if isinstance(area, QScrollArea) else None


def showing_blank_page(dialog: SettingsDialog) -> bool:
    """Whether the stack is showing the blank page it puts up when the filter matches nothing (#230).

    :param dialog: the dialog whose stack to read.
    :returns: whether the right-hand side is blank.
    """
    return not isinstance(dialog_ui(dialog).page_stack.currentWidget(), QScrollArea)  # type: ignore[attr-defined]


def enclosing_scroll_areas(widget: QWidget, stop: QWidget) -> list[QAbstractScrollArea]:
    """Every scroll area between ``widget`` and ``stop``, innermost first (#229).

    :param widget: the widget to walk up from; itself included if it is a scroll area.
    :param stop: the ancestor to stop at, excluded from the walk.
    :returns: the scroll areas found, in the order met going up.
    """
    areas: list[QAbstractScrollArea] = []
    current: QWidget | None = widget
    while current is not None and current is not stop:
        if isinstance(current, QAbstractScrollArea):
            areas.append(current)
        current = current.parentWidget()
    return areas


def visible_index(dialog: SettingsDialog, title: str) -> QModelIndex:
    """The visible tree index of the row titled ``title``, searching groups' children too (#76).

    :param dialog: the dialog whose tree to search.
    :param title: the row's title -- a page's, or a group's.
    :returns: that row's index in the tree's (filtered) proxy model.
    :raises AssertionError: if no visible row has that title (e.g. filtered out).
    """
    model = dialog_ui(dialog).category_tree.model()  # type: ignore[attr-defined]

    def search(parent: QModelIndex) -> QModelIndex | None:
        for row in range(model.rowCount(parent)):
            index = model.index(row, 0, parent)
            if model.data(index) == title:
                return index
            if (found := search(index)) is not None:
                return found
        return None

    index = search(QModelIndex())
    if index is None:
        raise AssertionError(f"no visible row titled {title!r}")
    return index


def visible_titles(dialog: SettingsDialog) -> list[str]:
    """Every visible row's title, groups included, in tree order (#76).

    :param dialog: the dialog whose tree to read.
    :returns: the titles, each group followed by its own visible pages'.
    """
    model = dialog_ui(dialog).category_tree.model()  # type: ignore[attr-defined]

    def walk(parent: QModelIndex) -> list[str]:
        titles: list[str] = []
        for row in range(model.rowCount(parent)):
            index = model.index(row, 0, parent)
            titles.append(model.data(index))
            titles.extend(walk(index))
        return titles

    return walk(QModelIndex())


def select_page(dialog: SettingsDialog, title: str) -> None:
    """Select the tree row for the page titled ``title``.

    :param dialog: the dialog whose tree to select in.
    :param title: the page's title, as passed to :meth:`SettingsDialog.add_page`'s page.
    :raises AssertionError: if no visible row has that title (e.g. filtered out).
    """
    tree = dialog_ui(dialog).category_tree  # type: ignore[attr-defined]
    tree.setCurrentIndex(visible_index(dialog, title))


def select_group(dialog: SettingsDialog, title: str) -> None:
    """Select the tree row for the group titled ``title`` (#230).

    :param dialog: the dialog whose tree to select in.
    :param title: the group's title, as passed to :meth:`SettingsDialog.add_page`'s ``group``.
    """
    dialog_ui(dialog).category_tree.setCurrentIndex(visible_index(dialog, title))  # type: ignore[attr-defined]


def shown_group_container(dialog: SettingsDialog) -> QWidget:
    """The container widget of whichever group's stacked column the page stack is currently showing (#230).

    :param dialog: the dialog whose stack to read.
    :returns: the currently-shown scroll area's content widget.
    """
    area = dialog_ui(dialog).page_stack.currentWidget()  # type: ignore[attr-defined]
    return area.widget()


def stacked_group_widgets(dialog: SettingsDialog) -> list[QWidget]:
    """Every widget in the currently-shown group's column, in order -- headings and blocks alike (#230).

    :param dialog: the dialog whose stack to read.
    :returns: the column's widgets, the trailing stretch (no widget of its own) left out.
    """
    layout = shown_group_container(dialog).layout()
    assert layout is not None
    widgets = [layout.itemAt(index) for index in range(layout.count())]
    return [widget for item in widgets if item is not None and (widget := item.widget()) is not None]


def stacked_group_blocks(dialog: SettingsDialog) -> list[QWidget]:
    """The blocks stacked inside the currently-shown group's column, in order (#230).

    A group column takes each page's blocks, never the page widget itself, so what it holds are the
    pages' top-level frames -- the headings (plain ``QLabel``s, :meth:`stacked_group_headings`) are
    filtered out here.

    :param dialog: the dialog whose stack to read.
    :returns: the blocks, in the order they appear in the column.
    """
    return [widget for widget in stacked_group_widgets(dialog) if not isinstance(widget, QLabel)]


def visible_stacked_group_blocks(dialog: SettingsDialog) -> list[QWidget]:
    """The blocks the currently-shown group column is actually showing, in order (#230).

    :param dialog: the dialog whose stack to read.
    :returns: the blocks the live filter left visible.
    """
    container = shown_group_container(dialog)
    return [block for block in stacked_group_blocks(dialog) if block.isVisibleTo(container)]


def group_headings_by_text(dialog: SettingsDialog) -> dict[str, QLabel]:
    """The currently-shown group column's heading labels, keyed by their text (#230).

    :param dialog: the dialog whose stack to read.
    :returns: each heading label, by the page title it carries.
    """
    return {widget.text(): widget for widget in stacked_group_widgets(dialog) if isinstance(widget, QLabel)}


def stacked_group_headings(dialog: SettingsDialog) -> list[str]:
    """The heading labels' text inside the currently-shown group's column, in order (#230).

    :param dialog: the dialog whose stack to read.
    :returns: each heading's text, in the order it appears in the column.
    """
    return [widget.text() for widget in stacked_group_widgets(dialog) if isinstance(widget, QLabel)]


def test_add_page_creates_a_tree_row_and_stacked_page(qtbot: QtBot) -> None:
    """Adding a page gives it both a category-tree row and a page in the stacked widget.

    **Test steps:**

    * add one page
    * verify the tree shows exactly one row with its title, and the stack holds its widget
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    page = FakePage("Registry")

    dialog.add_page(page)

    ui = dialog_ui(dialog)
    model = ui.category_tree.model()  # type: ignore[attr-defined]
    assert model.rowCount() == 1
    assert model.data(model.index(0, 0)) == "Registry"
    assert len(page_scroll_areas(dialog)) == 1
    assert stacked_pages(dialog) == [page]


def test_first_added_page_becomes_the_initially_selected_one(qtbot: QtBot) -> None:
    """The very first page added is auto-selected, showing it in the stack immediately.

    **Test steps:**

    * add a page
    * verify the stack's current widget is that page, with no explicit selection needed
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    page = FakePage("Registry")

    dialog.add_page(page)

    assert current_page(dialog) is page


def test_the_first_added_page_is_selected_even_when_grouped(qtbot: QtBot) -> None:
    """A grouped first page is still auto-selected -- its group's own stacked-view scroll area (#230)
    also occupies a page-stack slot, so "first page" can't be told from ``page_stack.count() == 1``.

    **Test steps:**

    * add a page under a group, as the very first page registered
    * verify the stack's current widget is that page, not the group's (empty-of-selection) column
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    page = FakePage("Descriptions")

    dialog.add_page(page, group="Editors")

    assert current_page(dialog) is page


def test_selecting_a_tree_row_switches_the_stacked_page(qtbot: QtBot) -> None:
    """Selecting a different category's row brings its page to the front of the stack.

    **Test steps:**

    * add two pages (the first is auto-selected)
    * select the second page's tree row
    * verify the stack now shows the second page
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    first = FakePage("Registry")
    second = FakePage("Markdown Rendering")
    dialog.add_page(first)
    dialog.add_page(second)

    select_page(dialog, "Markdown Rendering")

    assert current_page(dialog) is second


def test_empty_filter_shows_every_page(qtbot: QtBot) -> None:
    """With no filter text, every registered page's row is visible.

    **Test steps:**

    * add two pages
    * verify the tree shows both rows
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    dialog.add_page(FakePage("Registry"))
    dialog.add_page(FakePage("Markdown Rendering"))

    assert dialog_ui(dialog).category_tree.model().rowCount() == 2  # type: ignore[attr-defined]


def test_filter_hides_a_page_whose_title_and_field_labels_dont_match(qtbot: QtBot) -> None:
    """Typing filter text hides pages whose title and field labels don't contain it.

    **Test steps:**

    * add two pages with distinct titles/field labels
    * type a filter matching only one of them
    * verify only the matching page's row remains visible
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    dialog.add_page(FakePage("Registry", [["Register", "Unregister"]]))
    dialog.add_page(FakePage("Markdown Rendering", [["Engine", "CSS"]]))

    dialog_ui(dialog).filter_edit.setText("regist")  # type: ignore[attr-defined]

    model = dialog_ui(dialog).category_tree.model()  # type: ignore[attr-defined]
    assert model.rowCount() == 1
    assert model.data(model.index(0, 0)) == "Registry"


def test_filter_matches_case_insensitively_against_field_labels(qtbot: QtBot) -> None:
    """The filter matches a page whose field label (not its title) contains the text, ignoring case.

    **Test steps:**

    * add a page whose title doesn't contain the filter text but whose field label does
    * type the filter in different case
    * verify the page's row is still shown
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    dialog.add_page(FakePage("Markdown Rendering", [["Maximum image width"]]))

    dialog_ui(dialog).filter_edit.setText("WIDTH")  # type: ignore[attr-defined]

    assert dialog_ui(dialog).category_tree.model().rowCount() == 1  # type: ignore[attr-defined]


def test_clearing_the_filter_shows_every_page_again(qtbot: QtBot) -> None:
    """Clearing the filter text restores every page's visibility.

    **Test steps:**

    * add two pages and filter down to one
    * clear the filter
    * verify both rows are visible again
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    dialog.add_page(FakePage("Registry", [["Register"]]))
    dialog.add_page(FakePage("Markdown Rendering", [["Engine"]]))
    dialog_ui(dialog).filter_edit.setText("regist")  # type: ignore[attr-defined]

    dialog_ui(dialog).filter_edit.setText("")  # type: ignore[attr-defined]

    assert dialog_ui(dialog).category_tree.model().rowCount() == 2  # type: ignore[attr-defined]


def test_apply_current_page_action_saves_only_the_selected_page(qtbot: QtBot) -> None:
    """Triggering "Apply" saves the currently-selected page and leaves the other untouched.

    **Test steps:**

    * add two pages, select the second
    * trigger ``apply_current_page_action``
    * verify only the second page's ``save_changes`` was called
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    first = FakePage("Registry")
    second = FakePage("Markdown Rendering")
    dialog.add_page(first)
    dialog.add_page(second)
    select_page(dialog, "Markdown Rendering")
    second.dirty = True
    refresh_dirty_state(dialog)

    dialog_ui(dialog).apply_current_page_action.trigger()  # type: ignore[attr-defined]

    assert first.save_calls == 0
    assert second.save_calls == 1


def test_apply_all_action_saves_every_page(qtbot: QtBot) -> None:
    """Triggering "Apply All" saves every registered page, not just the selected one.

    **Test steps:**

    * add two pages, select the first (the default)
    * trigger ``apply_all_action``
    * verify both pages' ``save_changes`` were called
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    first = FakePage("Registry")
    second = FakePage("Markdown Rendering")
    dialog.add_page(first)
    dialog.add_page(second)
    first.dirty = True
    second.dirty = True
    refresh_dirty_state(dialog)

    dialog_ui(dialog).apply_all_action.trigger()  # type: ignore[attr-defined]

    assert first.save_calls == 1
    assert second.save_calls == 1


def test_reset_current_page_action_drops_only_the_selected_page(qtbot: QtBot) -> None:
    """Triggering "Reset" discards only the currently-selected page's changes.

    **Test steps:**

    * add two pages, select the second
    * trigger ``reset_current_page_action``
    * verify only the second page's ``drop_changes`` was called
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    first = FakePage("Registry")
    second = FakePage("Markdown Rendering")
    dialog.add_page(first)
    dialog.add_page(second)
    select_page(dialog, "Markdown Rendering")
    second.dirty = True
    refresh_dirty_state(dialog)

    dialog_ui(dialog).reset_current_page_action.trigger()  # type: ignore[attr-defined]

    assert first.drop_calls == 0
    assert second.drop_calls == 1


def test_reset_all_action_drops_every_page(qtbot: QtBot) -> None:
    """Triggering "Reset All" discards every registered page's changes, not just the selected one.

    **Test steps:**

    * add two pages, select the first (the default)
    * trigger ``reset_all_action``
    * verify both pages' ``drop_changes`` were called
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    first = FakePage("Registry")
    second = FakePage("Markdown Rendering")
    dialog.add_page(first)
    dialog.add_page(second)
    first.dirty = True
    second.dirty = True
    refresh_dirty_state(dialog)

    dialog_ui(dialog).reset_all_action.trigger()  # type: ignore[attr-defined]

    assert first.drop_calls == 1
    assert second.drop_calls == 1


def test_clearing_the_tree_selection_leaves_the_stack_untouched(qtbot: QtBot) -> None:
    """Deselecting every tree row (no current page) doesn't change the stack or raise.

    **Test steps:**

    * add a page (auto-selected)
    * clear the tree's current index
    * verify the stack still shows the page (nothing to switch to, so it's left as-is)
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    page = FakePage("Registry")
    dialog.add_page(page)

    dialog_ui(dialog).category_tree.setCurrentIndex(QModelIndex())  # type: ignore[attr-defined]

    assert current_page(dialog) is page


def test_actions_are_no_ops_with_no_pages_registered(qtbot: QtBot) -> None:
    """Triggering any toolbar action with zero pages registered does nothing and doesn't raise.

    **Test steps:**

    * construct a dialog with no pages
    * trigger every toolbar action
    * verify none of it raises (nothing else observable to assert)
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    ui = dialog_ui(dialog)

    ui.apply_all_action.trigger()  # type: ignore[attr-defined]
    ui.apply_current_page_action.trigger()  # type: ignore[attr-defined]
    ui.reset_all_action.trigger()  # type: ignore[attr-defined]
    ui.reset_current_page_action.trigger()  # type: ignore[attr-defined]


def test_typing_filter_text_hides_the_current_pages_non_matching_frames(qtbot: QtBot) -> None:
    """Typing filter text drives the current page's frame-level filter (#67).

    **Test steps:**

    * add a page with two frames, then type text matching only the first
    * verify the matching frame stays shown and the other is hidden
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    page = FakePage("Registry", [["Register"], ["Check registration"]])
    dialog.add_page(page)

    dialog_ui(dialog).filter_edit.setText("register")  # type: ignore[attr-defined]

    register_frame, check_frame = page.frames
    assert register_frame.isVisibleTo(page) is True
    assert check_frame.isVisibleTo(page) is False


def test_toggling_show_full_page_reveals_the_whole_page_on_a_title_match(qtbot: QtBot) -> None:
    """Checking "show full page if title matches" re-runs the filter and reveals every frame (#67).

    **Test steps:**

    * add a page whose title matches the filter but whose second frame does not, and filter to it
    * check the toggle
    * verify the previously-hidden frame is now shown (whole page revealed)
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    page = FakePage("Registry", [["Register"], ["Check status"]])
    dialog.add_page(page)
    dialog_ui(dialog).filter_edit.setText("regist")  # type: ignore[attr-defined]
    assert page.frames[1].isVisibleTo(page) is False

    dialog_ui(dialog).show_full_page_check_box.set_checked(True)  # type: ignore[attr-defined]

    assert page.frames[1].isVisibleTo(page) is True


def test_selecting_a_page_applies_the_active_filter_to_it(qtbot: QtBot) -> None:
    """A page becoming current gets the live filter applied, so it isn't shown unfiltered (#67).

    **Test steps:**

    * add two pages, type a filter matching only one frame of the second, then select the second
    * verify the second page's non-matching frame is hidden on display
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    first = FakePage("Registry", [["Register"]])
    second = FakePage("Markdown Rendering", [["Engine"], ["Images"]])
    dialog.add_page(first)
    dialog.add_page(second)
    dialog_ui(dialog).filter_edit.setText("engine")  # type: ignore[attr-defined]

    select_page(dialog, "Markdown Rendering")

    engine_frame, image_frame = second.frames
    assert engine_frame.isVisibleTo(second) is True
    assert image_frame.isVisibleTo(second) is False


def test_adding_a_grouped_page_nests_its_row_under_a_group_row(qtbot: QtBot) -> None:
    """A page added with a ``group`` gets a leaf row under that group's own (page-less) row (#76).

    **Test steps:**

    * add one grouped page and one ungrouped page
    * verify the tree's top level holds the group row and the ungrouped page's row
    * verify the grouped page is the group row's only child
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)

    dialog.add_page(FakePage("Descriptions"), group="Editors")
    dialog.add_page(FakePage("System Integration"))

    model = dialog_ui(dialog).category_tree.model()  # type: ignore[attr-defined]
    assert [model.data(model.index(row, 0)) for row in range(model.rowCount())] == [
        "Editors",
        "System Integration",
    ]
    editors = visible_index(dialog, "Editors")
    assert model.rowCount(editors) == 1
    assert model.data(model.index(0, 0, editors)) == "Descriptions"


def test_pages_in_the_same_group_share_one_group_row(qtbot: QtBot) -> None:
    """A group's row is created once, on first use, and later pages join it (#76).

    **Test steps:**

    * add two pages naming the same group
    * verify the tree has a single top-level row holding both pages
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)

    dialog.add_page(FakePage("Descriptions"), group="Editors")
    dialog.add_page(FakePage("Tags"), group="Editors")

    model = dialog_ui(dialog).category_tree.model()  # type: ignore[attr-defined]
    assert model.rowCount() == 1
    assert visible_titles(dialog) == ["Editors", "Descriptions", "Tags"]


def test_selecting_a_grouped_page_switches_the_stacked_page(qtbot: QtBot) -> None:
    """A grouped page's leaf row drives the stack just like a top-level one (#76).

    **Test steps:**

    * add an ungrouped page (auto-selected) and a grouped one
    * select the grouped page's row
    * verify the stack shows it
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    first = FakePage("System Integration")
    grouped = FakePage("Descriptions")
    dialog.add_page(first)
    dialog.add_page(grouped, group="Editors")

    select_page(dialog, "Descriptions")

    assert current_page(dialog) is grouped


def test_selecting_a_group_with_one_page_shows_that_pages_frames(qtbot: QtBot) -> None:
    """Selecting a group holding a single page shows that page, frames included (#230).

    **Test steps:**

    * add one grouped page with a frame the live filter hides, then filter and select the group
    * verify the page is the one (and only) page stacked in the group's column, filtered as normal
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    page = FakePage("Descriptions", [["Engine"], ["Images"]])
    dialog.add_page(page, group="Editors")
    dialog_ui(dialog).filter_edit.setText("engine")  # type: ignore[attr-defined]

    select_group(dialog, "Editors")

    assert stacked_group_blocks(dialog) == page.frames
    assert visible_stacked_group_blocks(dialog) == [page.frames[0]]


def test_selecting_a_group_with_several_pages_stacks_them_in_tree_order(qtbot: QtBot) -> None:
    """Selecting a group with several pages shows all of them together, in tree order (#230).

    **Test steps:**

    * add two pages under one group, each with two blocks
    * select the group's own row
    * verify every block is stacked, in page order, each page's under its own title as a heading
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    first = FakePage("Descriptions", [["Engine"], ["Fonts"]])
    second = FakePage("Tags", [["Separator"], ["Casing"]])
    dialog.add_page(first, group="Editors")
    dialog.add_page(second, group="Editors")

    select_group(dialog, "Editors")

    assert stacked_group_blocks(dialog) == first.frames + second.frames
    assert stacked_group_headings(dialog) == ["Descriptions", "Tags"]


def test_reselecting_an_already_shown_group_does_not_duplicate_its_blocks(qtbot: QtBot) -> None:
    """Navigating away from a shown group and back rebuilds its column without leaving any block
    doubled up -- each is taken from wherever it is, never copied (#230).

    **Test steps:**

    * add two pages under one group and an unrelated top-level page, then select the group
    * select the top-level page, then select the group again
    * verify the group's column still holds each block exactly once, in the same order
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    first = FakePage("Descriptions", [["Engine"]])
    second = FakePage("Tags", [["Separator"]])
    other = FakePage("System Integration", [["Register"]])
    dialog.add_page(first, group="Editors")
    dialog.add_page(second, group="Editors")
    dialog.add_page(other)
    select_group(dialog, "Editors")

    select_page(dialog, "System Integration")
    select_group(dialog, "Editors")

    assert stacked_group_blocks(dialog) == first.frames + second.frames
    assert stacked_group_headings(dialog) == ["Descriptions", "Tags"]


def test_reselecting_a_group_after_visiting_one_of_its_leaves_keeps_tree_order(qtbot: QtBot) -> None:
    """A page pulled out of a group by selecting its own leaf row rejoins at its tree position when
    the group is reselected, not always at the end.

    Guards the defect this view shipped with: skipping already-homed pages when rebuilding the
    column left them in place while the rejoining page was appended after them regardless of its
    tree position, so selecting the *first* page's leaf row and then the group again pushed that
    page to the bottom of the column instead of back to the top (#230).

    **Test steps:**

    * add three pages under one group and select the group (stacking all their blocks)
    * select the first page's own leaf row, then select the group again
    * verify the column is back in tree order, not with the first page's block pushed to the end
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    first = FakePage("Descriptions", [["Engine"]])
    second = FakePage("Excluded Files", [["Patterns"]])
    third = FakePage("Images", [["Thumbnail"]])
    dialog.add_page(first, group="Plugins")
    dialog.add_page(second, group="Plugins")
    dialog.add_page(third, group="Plugins")
    select_group(dialog, "Plugins")

    select_page(dialog, "Descriptions")
    select_group(dialog, "Plugins")

    assert stacked_group_blocks(dialog) == first.frames + second.frames + third.frames
    assert stacked_group_headings(dialog) == ["Descriptions", "Excluded Files", "Images"]


def test_selecting_a_leaf_page_after_a_group_shows_it_alone_with_no_group_leftovers(qtbot: QtBot) -> None:
    """Selecting a leaf page after its group was shown displays only that page (#230).

    **Test steps:**

    * add two pages under one group, then select the group (stacking both)
    * select one page's own leaf row
    * verify the stack shows only that page -- not the group's stacked column
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    first = FakePage("Descriptions")
    second = FakePage("Tags")
    dialog.add_page(first, group="Editors")
    dialog.add_page(second, group="Editors")
    select_group(dialog, "Editors")

    select_page(dialog, "Descriptions")

    assert current_page(dialog) is first


def test_a_pages_state_survives_moving_from_a_group_view_to_a_leaf_view(qtbot: QtBot) -> None:
    """A page is re-parented between the group view and its own, never duplicated (#230).

    **Test steps:**

    * add a page under a group, select the group, then stand in for an in-progress edit on the page
    * select the page's own leaf row
    * verify the same page instance -- with that state intact -- is what's shown, not a copy
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    page = FakePage("Descriptions")
    dialog.add_page(page, group="Editors")
    select_group(dialog, "Editors")
    page.save_calls = 5  # stands in for an in-progress edit: state that must survive re-parenting

    select_page(dialog, "Descriptions")

    assert current_page(dialog) is page
    assert page.save_calls == 5


def test_apply_current_page_on_a_group_row_saves_every_page_under_it(qtbot: QtBot) -> None:
    """ "Apply" on a selected group row saves every page under it, not just one (#230).

    **Test steps:**

    * add two pages under one group and select the group's own row
    * trigger ``apply_current_page_action``
    * verify both pages' ``save_changes`` were called
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    first = FakePage("Descriptions")
    second = FakePage("Tags")
    dialog.add_page(first, group="Editors")
    dialog.add_page(second, group="Editors")
    select_group(dialog, "Editors")
    first.dirty = True
    second.dirty = True
    refresh_dirty_state(dialog)

    dialog_ui(dialog).apply_current_page_action.trigger()  # type: ignore[attr-defined]

    assert first.save_calls == 1
    assert second.save_calls == 1


def test_reset_current_page_on_a_group_row_drops_every_page_under_it(qtbot: QtBot) -> None:
    """ "Reset" on a selected group row drops every page under it, not just one (#230).

    **Test steps:**

    * add two pages under one group and select the group's own row
    * trigger ``reset_current_page_action``
    * verify both pages' ``drop_changes`` were called
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    first = FakePage("Descriptions")
    second = FakePage("Tags")
    dialog.add_page(first, group="Editors")
    dialog.add_page(second, group="Editors")
    select_group(dialog, "Editors")
    first.dirty = True
    second.dirty = True
    refresh_dirty_state(dialog)

    dialog_ui(dialog).reset_current_page_action.trigger()  # type: ignore[attr-defined]

    assert first.drop_calls == 1
    assert second.drop_calls == 1


def test_typing_filter_text_with_a_group_row_selected_filters_every_pages_blocks(qtbot: QtBot) -> None:
    """Filtering while a group is the current row filters the blocks of every page under it, not just
    one -- a filtered group column composes with the block filter (#230).

    **Test steps:**

    * add two pages, each with a block matching only one, under one group; select the group
    * type filter text matching only the first page's block
    * verify the column is left showing that block alone
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    first = FakePage("Descriptions", [["Engine"]])
    second = FakePage("Tags", [["Separator"]])
    dialog.add_page(first, group="Editors")
    dialog.add_page(second, group="Editors")
    select_group(dialog, "Editors")

    dialog_ui(dialog).filter_edit.setText("engine")  # type: ignore[attr-defined]

    assert visible_stacked_group_blocks(dialog) == [first.frames[0]]


def test_apply_all_action_saves_grouped_pages_too(qtbot: QtBot) -> None:
    """ "Apply All" reaches pages nested under a group, not just top-level ones (#76).

    **Test steps:**

    * add one grouped and one ungrouped page
    * trigger ``apply_all_action``
    * verify both pages' ``save_changes`` were called
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    grouped = FakePage("Descriptions")
    ungrouped = FakePage("System Integration")
    dialog.add_page(grouped, group="Editors")
    dialog.add_page(ungrouped)
    grouped.dirty = True
    ungrouped.dirty = True
    refresh_dirty_state(dialog)

    dialog_ui(dialog).apply_all_action.trigger()  # type: ignore[attr-defined]

    assert grouped.save_calls == 1
    assert ungrouped.save_calls == 1


def test_a_group_row_is_hidden_when_none_of_its_pages_match(qtbot: QtBot) -> None:
    """Filtering out every page of a group hides the group's own row with them (#76).

    **Test steps:**

    * add a grouped page and an ungrouped one
    * filter to text matching only the ungrouped page
    * verify neither the group row nor its page remains visible
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    dialog.add_page(FakePage("Descriptions", [["Engine"]]), group="Editors")
    dialog.add_page(FakePage("System Integration", [["Register"]]))

    dialog_ui(dialog).filter_edit.setText("regist")  # type: ignore[attr-defined]

    assert visible_titles(dialog) == ["System Integration"]


def test_a_group_row_stays_visible_when_one_of_its_pages_matches(qtbot: QtBot) -> None:
    """A group is shown exactly when a page under it is -- Qt hides a rejected parent's children,
    so the group must accept on its pages' behalf (#76).

    **Test steps:**

    * add two pages to one group, with distinct field labels
    * filter to text matching only the second page
    * verify the group row stays visible, with only the matching page under it
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    dialog.add_page(FakePage("Descriptions", [["Engine"]]), group="Editors")
    dialog.add_page(FakePage("Tags", [["Separator"]]), group="Editors")

    dialog_ui(dialog).filter_edit.setText("separator")  # type: ignore[attr-defined]

    assert visible_titles(dialog) == ["Editors", "Tags"]


def test_show_full_group_reveals_every_page_of_a_group_whose_title_matches(qtbot: QtBot) -> None:
    """With the toggle on, a group's own title matching shows every page under it (#76).

    **Test steps:**

    * add two pages to a group, neither matching "editors" on its own merits
    * check "show full group if title matches" and filter to the group's title
    * verify both pages are shown under the group
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    dialog.add_page(FakePage("Descriptions", [["Engine"]]), group="Editors")
    dialog.add_page(FakePage("Tags", [["Separator"]]), group="Editors")
    dialog_ui(dialog).show_full_group_check_box.set_checked(True)  # type: ignore[attr-defined]

    dialog_ui(dialog).filter_edit.setText("editors")  # type: ignore[attr-defined]

    assert visible_titles(dialog) == ["Editors", "Descriptions", "Tags"]


def test_a_group_title_match_shows_no_pages_while_show_full_group_is_off(qtbot: QtBot) -> None:
    """With the toggle off, filtering stays page-scoped: a group's title has no say (#76).

    **Test steps:**

    * add a page under a group, matching neither the filter text nor anything but its group's title
    * filter to the group's title, toggle left unchecked
    * verify nothing is shown -- not the page, and not the group row on its own
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    dialog.add_page(FakePage("Descriptions", [["Engine"]]), group="Editors")

    dialog_ui(dialog).filter_edit.setText("editors")  # type: ignore[attr-defined]

    assert visible_titles(dialog) == []


def test_a_page_matching_on_its_own_is_shown_whatever_the_group_toggle(qtbot: QtBot) -> None:
    """A page matching the filter itself is shown independent of the toggle and its group (#76).

    **Test steps:**

    * add a page under a group whose title doesn't match the filter
    * filter to the page's own field label, with the toggle off, then on
    * verify the page is shown either way
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    dialog.add_page(FakePage("Descriptions", [["Engine"]]), group="Editors")

    dialog_ui(dialog).filter_edit.setText("engine")  # type: ignore[attr-defined]
    assert visible_titles(dialog) == ["Editors", "Descriptions"]

    dialog_ui(dialog).show_full_group_check_box.set_checked(True)  # type: ignore[attr-defined]

    assert visible_titles(dialog) == ["Editors", "Descriptions"]


def test_show_full_group_does_not_reveal_another_groups_pages(qtbot: QtBot) -> None:
    """A group's title match reveals only its own pages, not another group's (#76).

    **Test steps:**

    * add a page under each of two groups, neither matching "editors" itself
    * check the toggle and filter to one group's title
    * verify only that group and its page are shown
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    dialog.add_page(FakePage("Descriptions", [["Engine"]]), group="Editors")
    dialog.add_page(FakePage("Themes", [["Palette"]]), group="Appearance")
    dialog_ui(dialog).show_full_group_check_box.set_checked(True)  # type: ignore[attr-defined]

    dialog_ui(dialog).filter_edit.setText("editors")  # type: ignore[attr-defined]

    assert visible_titles(dialog) == ["Editors", "Descriptions"]


def test_show_full_group_leaves_an_ungrouped_page_page_scoped(qtbot: QtBot) -> None:
    """A top-level page has no group to inherit a match from, toggle or not (#76).

    **Test steps:**

    * add an ungrouped page alongside a grouped one, and check the toggle
    * filter to the group's title
    * verify the ungrouped page is hidden and only the group's page is shown
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    dialog.add_page(FakePage("Descriptions", [["Engine"]]), group="Editors")
    dialog.add_page(FakePage("System Integration", [["Register"]]))
    dialog_ui(dialog).show_full_group_check_box.set_checked(True)  # type: ignore[attr-defined]

    dialog_ui(dialog).filter_edit.setText("editors")  # type: ignore[attr-defined]

    assert visible_titles(dialog) == ["Editors", "Descriptions"]


def test_save_filter_state_persists_the_filter_text_and_both_toggles(
    qtbot: QtBot, fake_persistent_settings: FakeSettings
) -> None:
    """:meth:`SettingsDialog.save_filter_state` writes the whole live filter state (#76).

    **Test steps:**

    * type filter text and check both "show full ..." boxes
    * call ``save_filter_state`` (what ``MainWindow.closeEvent`` does)
    * verify all three come back from a fresh `SettingsDialogSettings` loaded from the same storage
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    dialog_ui(dialog).filter_edit.setText("engine")  # type: ignore[attr-defined]
    dialog_ui(dialog).show_full_page_check_box.set_checked(True)  # type: ignore[attr-defined]
    dialog_ui(dialog).show_full_group_check_box.set_checked(True)  # type: ignore[attr-defined]

    dialog.save_filter_state()

    saved = SettingsDialogSettings()
    saved.load(fake_persistent_settings)  # type: ignore[arg-type]
    assert saved.filter_text == "engine"
    assert saved.show_full_page_on_title_match is True
    assert saved.show_full_group_on_title_match is True


def test_changing_the_filter_alone_persists_nothing(qtbot: QtBot, fake_persistent_settings: FakeSettings) -> None:
    """Filtering is not saved as it is typed -- only :meth:`SettingsDialog.save_filter_state` writes,
    so the filter box costs no ini write per keystroke (#76).

    **Test steps:**

    * type filter text and check a "show full ..." box, without saving
    * verify storage still holds neither
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)

    dialog_ui(dialog).filter_edit.setText("engine")  # type: ignore[attr-defined]
    dialog_ui(dialog).show_full_page_check_box.set_checked(True)  # type: ignore[attr-defined]

    saved = SettingsDialogSettings()
    saved.load(fake_persistent_settings)  # type: ignore[arg-type]
    assert saved.filter_text == ""
    assert saved.show_full_page_on_title_match is False


def test_save_filter_state_persists_a_cleared_filter(qtbot: QtBot, fake_persistent_settings: FakeSettings) -> None:
    """A filter cleared before the save is saved as cleared, not left at its old value (#76).

    **Test steps:**

    * save filter text, then build a dialog and clear its (restored) filter box
    * call ``save_filter_state``
    * verify the persisted filter text is now empty
    """
    SettingsDialogSettings(filter_text="engine").save(fake_persistent_settings)  # type: ignore[arg-type]
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)

    dialog_ui(dialog).filter_edit.setText("")  # type: ignore[attr-defined]
    dialog.save_filter_state()

    saved = SettingsDialogSettings()
    saved.load(fake_persistent_settings)  # type: ignore[arg-type]
    assert saved.filter_text == ""


def test_starts_with_the_persisted_filter_state(qtbot: QtBot, fake_persistent_settings: FakeSettings) -> None:
    """A freshly-built dialog restores the filter text and both toggles from storage (#76).

    **Test steps:**

    * save filter text and both toggles checked, then build a dialog
    * verify the filter box and both check boxes come up as saved
    """
    saved_settings = SettingsDialogSettings(
        filter_text="engine", show_full_page_on_title_match=True, show_full_group_on_title_match=True
    )
    saved_settings.save(fake_persistent_settings)  # type: ignore[arg-type]

    dialog = SettingsDialog()
    qtbot.addWidget(dialog)

    assert dialog_ui(dialog).filter_edit.text() == "engine"  # type: ignore[attr-defined]
    assert dialog_ui(dialog).show_full_page_check_box.is_checked() is True  # type: ignore[attr-defined]
    assert dialog_ui(dialog).show_full_group_check_box.is_checked() is True  # type: ignore[attr-defined]


def test_a_restored_filter_text_hides_non_matching_pages_from_the_start(
    qtbot: QtBot, fake_persistent_settings: FakeSettings
) -> None:
    """A restored filter text takes effect on the tree without being retyped -- the proxy is seeded
    from it, not only from a ``textChanged`` signal (#76).

    **Test steps:**

    * save filter text, then build a dialog and add a matching and a non-matching page
    * verify only the matching page's row is visible
    """
    SettingsDialogSettings(filter_text="regist").save(fake_persistent_settings)  # type: ignore[arg-type]
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)

    dialog.add_page(FakePage("System Integration", [["Register"]]))
    dialog.add_page(FakePage("Descriptions", [["Engine"]]), group="Editors")

    assert visible_titles(dialog) == ["System Integration"]


def test_a_page_added_under_a_group_while_a_filter_is_live_still_shows(
    qtbot: QtBot, fake_persistent_settings: FakeSettings
) -> None:
    """A group row is judged by its pages, so one added *after* the group was already filtered out
    (empty) must bring it back -- Qt re-tests only the inserted row, never its parent (#76).

    This is startup's own order with a restored filter: `MainWindow` registers its pages after the
    dialog has restored the filter, so without a re-filter the whole group would stay hidden.

    **Test steps:**

    * save filter text matching a page's field label, then build a dialog
    * add that page under a group whose own title doesn't match the filter
    * verify the group and its page are both shown
    """
    SettingsDialogSettings(filter_text="engine").save(fake_persistent_settings)  # type: ignore[arg-type]
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)

    dialog.add_page(FakePage("Descriptions", [["Engine"]]), group="Editors")

    assert visible_titles(dialog) == ["Editors", "Descriptions"]


def test_a_restored_filter_text_hides_the_first_pages_non_matching_frames(
    qtbot: QtBot, fake_persistent_settings: FakeSettings
) -> None:
    """The first page added -- which becomes current -- is frame-filtered by a restored filter,
    rather than showing unfiltered until the text is touched (#76).

    **Test steps:**

    * save filter text, then build a dialog and add a page with a matching and a non-matching frame
    * verify only the matching frame is shown
    """
    SettingsDialogSettings(filter_text="engine").save(fake_persistent_settings)  # type: ignore[arg-type]
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    page = FakePage("Descriptions", [["Engine"], ["Images"]])

    dialog.add_page(page)

    assert [frame.isVisibleTo(page) for frame in page.frames] == [True, False]


def test_a_restored_show_full_group_toggle_filters_group_aware_from_the_start(
    qtbot: QtBot, fake_persistent_settings: FakeSettings
) -> None:
    """A restored "show full group" toggle takes effect without being clicked -- the tree filter is
    seeded from it, not only from a ``toggled`` signal (#76).

    **Test steps:**

    * save "show full group if title matches" as checked, then build a dialog with a grouped page
    * filter to the group's title, which the page itself doesn't match
    * verify the page is shown, as it would be had the toggle been clicked
    """
    SettingsDialogSettings(show_full_group_on_title_match=True).save(fake_persistent_settings)  # type: ignore[arg-type]
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    dialog.add_page(FakePage("Descriptions", [["Engine"]]), group="Editors")

    dialog_ui(dialog).filter_edit.setText("editors")  # type: ignore[attr-defined]

    assert visible_titles(dialog) == ["Editors", "Descriptions"]


def test_a_restored_show_full_page_toggle_filters_frames_from_the_start(
    qtbot: QtBot, fake_persistent_settings: FakeSettings
) -> None:
    """A restored "show full page" toggle takes effect on the first filter, unclicked (#76).

    **Test steps:**

    * save "show full page if title matches" as checked, then build a dialog with a two-frame page
    * filter to the page's title, which its second frame doesn't match
    * verify both frames are shown (whole page revealed on the title match)
    """
    SettingsDialogSettings(show_full_page_on_title_match=True).save(fake_persistent_settings)  # type: ignore[arg-type]
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    page = FakePage("Descriptions", [["Engine"], ["Images"]])
    dialog.add_page(page)

    dialog_ui(dialog).filter_edit.setText("descript")  # type: ignore[attr-defined]

    assert page.frames[1].isVisibleTo(page) is True


def test_save_filter_state_persists_the_selected_pages_title(
    qtbot: QtBot, fake_persistent_settings: FakeSettings
) -> None:
    """:meth:`SettingsDialog.save_filter_state` stores the currently-shown page's title (#228).

    **Test steps:**

    * add two pages and select the second
    * call ``save_filter_state``
    * verify the second page's title comes back from a fresh `SettingsDialogSettings`
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    dialog.add_page(FakePage("Registry"))
    dialog.add_page(FakePage("Markdown Rendering"))
    select_page(dialog, "Markdown Rendering")

    dialog.save_filter_state()

    saved = SettingsDialogSettings()
    saved.load(fake_persistent_settings)  # type: ignore[arg-type]
    assert saved.selected_page_title == "Markdown Rendering"


def test_save_filter_state_with_a_group_row_selected_stores_the_groups_own_title(
    qtbot: QtBot, fake_persistent_settings: FakeSettings
) -> None:
    """A group row shows several pages at once (#230), so what's stored is the *group's* own title --
    not one of its pages', and not the previously-stored title left stale. Otherwise, restarting after
    selecting a group brought back whatever leaf page had been viewed before it, not the group.

    **Test steps:**

    * save a stale page title, then build a dialog with a grouped page and select the group's own row
    * call ``save_filter_state``
    * verify the group's own title is stored, replacing the stale one
    """
    SettingsDialogSettings(selected_page_title="Stale Page").save(fake_persistent_settings)  # type: ignore[arg-type]
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    dialog.add_page(FakePage("Descriptions"), group="Editors")
    select_group(dialog, "Editors")

    dialog.save_filter_state()

    saved = SettingsDialogSettings()
    saved.load(fake_persistent_settings)  # type: ignore[arg-type]
    assert saved.selected_page_title == "Editors"


def test_restore_selected_page_shows_the_page_matching_the_stored_title(
    qtbot: QtBot, fake_persistent_settings: FakeSettings
) -> None:
    """A stored title matching a registered page selects it (#228).

    **Test steps:**

    * save a page title, then build a dialog and register that page second
    * call ``restore_selected_page``
    * verify the stack now shows that page, and its tree row is the current one
    """
    saved_settings = SettingsDialogSettings(selected_page_title="Markdown Rendering")
    saved_settings.save(fake_persistent_settings)  # type: ignore[arg-type]
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    dialog.add_page(FakePage("Registry"))
    second = FakePage("Markdown Rendering")
    dialog.add_page(second)

    dialog.restore_selected_page()

    tree = dialog_ui(dialog).category_tree  # type: ignore[attr-defined]
    assert current_page(dialog) is second
    assert tree.currentIndex() == visible_index(dialog, "Markdown Rendering")


def test_restore_selected_page_shows_the_group_matching_the_stored_title(
    qtbot: QtBot, fake_persistent_settings: FakeSettings
) -> None:
    """A stored title matching a *group's* own title restores its stacked column, not one page (#230).

    **Test steps:**

    * save a group's title, then build a dialog with two pages under that group
    * call ``restore_selected_page``
    * verify the stack shows both pages' blocks stacked, and the group's tree row is the current one
    """
    saved_settings = SettingsDialogSettings(selected_page_title="Editors")
    saved_settings.save(fake_persistent_settings)  # type: ignore[arg-type]
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    first = FakePage("Descriptions", [["Engine"]])
    second = FakePage("Tags", [["Separator"]])
    dialog.add_page(first, group="Editors")
    dialog.add_page(second, group="Editors")

    dialog.restore_selected_page()

    tree = dialog_ui(dialog).category_tree  # type: ignore[attr-defined]
    assert stacked_group_blocks(dialog) == first.frames + second.frames
    assert tree.currentIndex() == visible_index(dialog, "Editors")


def test_a_restored_group_selection_survives_the_next_save(
    qtbot: QtBot, fake_persistent_settings: FakeSettings
) -> None:
    """Restoring a group and immediately saving again keeps storing the group's title, not a leaf's
    left over from before the restore (#230).

    **Test steps:**

    * save a group's title, build a dialog with a grouped page, and restore
    * call ``save_filter_state`` without touching anything
    * verify the stored title is still the group's
    """
    SettingsDialogSettings(selected_page_title="Editors").save(fake_persistent_settings)  # type: ignore[arg-type]
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    dialog.add_page(FakePage("Descriptions"), group="Editors")
    dialog.restore_selected_page()

    dialog.save_filter_state()

    saved = SettingsDialogSettings()
    saved.load(fake_persistent_settings)  # type: ignore[arg-type]
    assert saved.selected_page_title == "Editors"


def test_restore_selected_page_finds_a_grouped_pages_title_too(
    qtbot: QtBot, fake_persistent_settings: FakeSettings
) -> None:
    """A stored title is found among grouped pages, not only top-level ones (#228).

    **Test steps:**

    * save a grouped page's title, then build a dialog registering an ungrouped page first
    * call ``restore_selected_page``
    * verify the stack shows the grouped page
    """
    SettingsDialogSettings(selected_page_title="Descriptions").save(fake_persistent_settings)  # type: ignore[arg-type]
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    dialog.add_page(FakePage("System Integration"))
    grouped = FakePage("Descriptions")
    dialog.add_page(grouped, group="Editors")

    dialog.restore_selected_page()

    assert current_page(dialog) is grouped


def test_restore_selected_page_walks_past_a_group_whose_pages_all_miss(
    qtbot: QtBot, fake_persistent_settings: FakeSettings
) -> None:
    """A group is searched through and left behind, not read as the end of the search (#228).

    The mirror of the test above: there the first grouped page was the match, so nothing exercised
    passing over a grouped page, nor carrying on to the rows after the group.

    **Test steps:**

    * save a top-level page's title, then build a dialog registering a two-page group *first*
    * call ``restore_selected_page``
    * verify both grouped pages were passed over and the top-level page is the one shown
    """
    saved_settings = SettingsDialogSettings(selected_page_title="System Integration")
    saved_settings.save(fake_persistent_settings)  # type: ignore[arg-type]
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    dialog.add_page(FakePage("Descriptions"), group="Editors")
    dialog.add_page(FakePage("Images"), group="Editors")
    wanted = FakePage("System Integration")
    dialog.add_page(wanted)

    dialog.restore_selected_page()

    assert current_page(dialog) is wanted


def test_restore_selected_page_leaves_the_first_page_when_the_stored_title_matches_nothing(
    qtbot: QtBot, fake_persistent_settings: FakeSettings
) -> None:
    """A stored title matching no registered page leaves the first-added page selected (#228).

    **Test steps:**

    * save a title naming no page this platform registers, then build a dialog with two pages
    * call ``restore_selected_page``
    * verify the first-added page is still shown
    """
    SettingsDialogSettings(selected_page_title="Registry").save(fake_persistent_settings)  # type: ignore[arg-type]
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    first = FakePage("Identity")
    dialog.add_page(first)
    dialog.add_page(FakePage("Markdown Rendering"))

    dialog.restore_selected_page()

    assert current_page(dialog) is first


def test_restore_selected_page_leaves_the_first_page_when_nothing_was_ever_saved(qtbot: QtBot) -> None:
    """With no stored title at all, restoring is a no-op and the first-added page stays shown (#228).

    **Test steps:**

    * build a dialog (nothing saved) with two pages
    * call ``restore_selected_page``
    * verify the first-added page is still shown
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    first = FakePage("Registry")
    dialog.add_page(first)
    dialog.add_page(FakePage("Markdown Rendering"))

    dialog.restore_selected_page()

    assert current_page(dialog) is first


def test_restore_selected_page_shows_a_page_the_restored_filter_hides_from_the_tree(
    qtbot: QtBot, fake_persistent_settings: FakeSettings
) -> None:
    """A stored title whose page is filtered out by the restored filter text is still the page
    shown -- the stack and the tree are separate (#228).

    **Test steps:**

    * save a page title together with filter text that page doesn't match
    * build a dialog and register that page second (so it isn't the auto-selected first one)
    * call ``restore_selected_page``
    * verify the stack shows that page, even though its tree row stays hidden by the filter
    """
    saved_settings = SettingsDialogSettings(selected_page_title="Markdown Rendering", filter_text="regist")
    saved_settings.save(fake_persistent_settings)  # type: ignore[arg-type]
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    dialog.add_page(FakePage("Registry", [["Register"]]))
    second = FakePage("Markdown Rendering", [["Engine"]])
    dialog.add_page(second)

    dialog.restore_selected_page()

    assert current_page(dialog) is second
    assert "Markdown Rendering" not in visible_titles(dialog)


def test_a_restored_page_hidden_by_the_filter_survives_the_next_save(
    qtbot: QtBot, fake_persistent_settings: FakeSettings
) -> None:
    """Closing right after a filtered-out restore saves the *shown* page's title, so the restored
    selection is stable across restarts rather than decaying to whichever row the tree kept (#228).

    **Test steps:**

    * save a page title with filter text hiding that page's row, build a dialog, restore
    * call ``save_filter_state`` without touching anything
    * verify the stored title is still the restored page's
    """
    saved_settings = SettingsDialogSettings(selected_page_title="Markdown Rendering", filter_text="regist")
    saved_settings.save(fake_persistent_settings)  # type: ignore[arg-type]
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    dialog.add_page(FakePage("Registry", [["Register"]]))
    dialog.add_page(FakePage("Markdown Rendering", [["Engine"]]))
    dialog.restore_selected_page()

    dialog.save_filter_state()

    saved = SettingsDialogSettings()
    saved.load(fake_persistent_settings)  # type: ignore[arg-type]
    assert saved.selected_page_title == "Markdown Rendering"


def test_filtering_with_no_pages_registered_does_nothing(qtbot: QtBot) -> None:
    """Changing the filter or toggle with no pages registered is a no-op and doesn't raise (#67).

    **Test steps:**

    * construct a dialog with no pages
    * type filter text and toggle both "show full ... if title matches" checkboxes
    * verify none of it raises (there is no current page to filter)
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)

    dialog_ui(dialog).filter_edit.setText("anything")  # type: ignore[attr-defined]
    dialog_ui(dialog).show_full_page_check_box.set_checked(True)  # type: ignore[attr-defined]
    dialog_ui(dialog).show_full_group_check_box.set_checked(True)  # type: ignore[attr-defined]


def test_each_page_is_shown_through_a_widget_resizable_scroll_area_of_its_own(qtbot: QtBot) -> None:
    """A page scrolls, and it scrolls by its own height rather than the tallest page's (#229).

    One scroll area per page, not one around the stack: a ``QStackedWidget`` reports its tallest page's
    height as its own, so a shared one would scroll a two-row page by a long page's length.

    **Test steps:**

    * add two pages
    * verify each is held by its own widget-resizable scroll area inside the stack
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    first = FakePage("Registry")
    second = FakePage("Markdown Rendering")

    dialog.add_page(first)
    dialog.add_page(second)

    areas = page_scroll_areas(dialog)
    assert [area.widget() for area in areas] == [first, second]
    assert all(area.widgetResizable() for area in areas)


def test_the_chrome_around_the_pages_is_not_inside_a_scroll_area(qtbot: QtBot) -> None:
    """The toolbar and the filter box always stay reachable: a control the user cannot reach is a
    setting they cannot change (#229).

    **Test steps:**

    * build a dialog
    * verify neither the toolbar nor the filter edit reaches the dialog through a scroll area
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    ui = dialog_ui(dialog)

    for chrome in (ui.toolbar, ui.filter_edit):  # type: ignore[attr-defined]
        assert enclosing_scroll_areas(chrome, dialog) == []


def test_the_category_tree_is_not_nested_inside_another_scroll_area(qtbot: QtBot) -> None:
    """A ``QTreeView`` scrolls natively, so wrapping one gives two scrollbars and a tree that can be
    scrolled out of its own viewport (#229).

    **Test steps:**

    * build a dialog
    * verify exactly one scroll area sits between the tree's viewport and the splitter -- the tree
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    ui = dialog_ui(dialog)

    tree = ui.category_tree  # type: ignore[attr-defined]
    assert enclosing_scroll_areas(tree.viewport(), ui.splitter) == [tree]  # type: ignore[attr-defined]


def test_a_tall_page_leaves_the_dialog_free_to_shrink(qtbot: QtBot) -> None:
    """A page taller than the dialog no longer sets the dialog's minimum height (#229).

    Guards the defect this shell shipped with: the stack's minimum was the tallest page's, so the
    whole dialog refused to shrink and its host's own chrome -- the dock frame's "Restore on start"
    check box -- was pushed out of the visible rectangle rather than staying put.

    **Test steps:**

    * add a page whose minimum height is far beyond any reasonable dialog size
    * verify the dialog's minimum height stays well under it
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    page = FakePage("Registry")
    page.setMinimumHeight(2000)

    dialog.add_page(page)

    assert dialog.minimumSizeHint().height() < 400


def test_shrinking_the_dialog_scrolls_the_tall_page_and_moves_nothing_else(qtbot: QtBot) -> None:
    """Squeezed below its content's height, the dialog scrolls the page and nothing else (#229).

    **Test steps:**

    * add a very tall page and a short one, then shrink the dialog well below the tall one
    * verify the toolbar and the splitter are still wholly within the dialog, that the tall page has
      somewhere to scroll to, and that the short one has none
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    tall = FakePage("Registry")
    tall.setMinimumHeight(2000)
    dialog.add_page(tall)
    dialog.add_page(FakePage("Markdown Rendering"))
    ui = dialog_ui(dialog)
    dialog.show()

    dialog.resize(500, 300)
    ui.main_layout.activate()  # type: ignore[attr-defined]

    tall_area, short_area = page_scroll_areas(dialog)
    assert ui.toolbar.geometry().bottom() <= dialog.height()  # type: ignore[attr-defined]
    assert ui.splitter.geometry().bottom() <= dialog.height()  # type: ignore[attr-defined]
    assert tall_area.verticalScrollBar().maximum() > 0
    assert short_area.verticalScrollBar().maximum() == 0


def test_a_group_page_the_filter_empties_takes_its_heading_with_it(qtbot: QtBot) -> None:
    """A stacked page filtered down to no frames is hidden, heading and all (#230).

    Guards what the stacked view shipped with: the heading was inserted beside the page but never
    filtered with it, so a group filtered to one page still showed the others' titles standing over
    empty gaps -- a promise of settings that had filtered out.

    **Test steps:**

    * add two pages under one group, each with a block only one filter term matches, and select it
    * filter to a term only the second page's block carries
    * verify only that block is left showing, under its own heading, and the other heading is gone
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    first = FakePage("Descriptions", [["Engine"]])
    second = FakePage("Images", [["Thumbnail"]])
    dialog.add_page(first, group="Plugins")
    dialog.add_page(second, group="Plugins")
    select_group(dialog, "Plugins")

    dialog_ui(dialog).filter_edit.setText("thumbnail")  # type: ignore[attr-defined]

    container = shown_group_container(dialog)
    headings = group_headings_by_text(dialog)
    assert visible_stacked_group_blocks(dialog) == [second.frames[0]]
    assert headings["Descriptions"].isVisibleTo(container) is False
    assert headings["Images"].isVisibleTo(container) is True


def test_clearing_the_filter_brings_an_emptied_group_page_back(qtbot: QtBot) -> None:
    """Hiding an emptied page is the filter's doing, so clearing the filter undoes it (#230).

    **Test steps:**

    * select a group, filter until one page's blocks are gone, then clear the filter
    * verify every block and both headings are shown again
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    first = FakePage("Descriptions", [["Engine"]])
    second = FakePage("Images", [["Thumbnail"]])
    dialog.add_page(first, group="Plugins")
    dialog.add_page(second, group="Plugins")
    select_group(dialog, "Plugins")
    dialog_ui(dialog).filter_edit.setText("thumbnail")  # type: ignore[attr-defined]

    dialog_ui(dialog).filter_edit.setText("")  # type: ignore[attr-defined]

    container = shown_group_container(dialog)
    headings = group_headings_by_text(dialog)
    assert visible_stacked_group_blocks(dialog) == first.frames + second.frames
    assert headings["Descriptions"].isVisibleTo(container) is True


def test_blocks_borrowed_by_a_group_go_home_when_the_page_is_shown_alone(qtbot: QtBot) -> None:
    """A block a group column borrowed goes back into its own page's layout, at its own position (#230).

    The page is the view for its own blocks, so what it shows on its own row has to be all of them, in
    the order it declared them -- not whichever ones a group happened to leave behind.

    **Test steps:**

    * add a two-block page under a group and select the group, so the column borrows both blocks
    * select the page's own leaf row
    * verify both blocks are back under the page, in order, and the column no longer holds them
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    page = FakePage("Descriptions", [["Engine"], ["Fonts"]])
    dialog.add_page(page, group="Plugins")
    dialog.add_page(FakePage("Images", [["Thumbnail"]]), group="Plugins")
    select_group(dialog, "Plugins")
    assert [block.parentWidget() for block in page.frames] != [page, page]

    select_page(dialog, "Descriptions")

    assert current_page(dialog) is page
    assert [block.parentWidget() for block in page.frames] == [page, page]
    items = [page.main_layout.itemAt(index) for index in range(len(page.frames))]
    assert [item.widget() for item in items if item is not None] == page.frames


def test_a_short_group_packs_its_blocks_from_the_top(qtbot: QtBot) -> None:
    """A group with room to spare stacks its blocks one after another and lets the column's own
    trailing stretch keep the rest of the height (#230).

    Guards the gaps this view shipped with. It used to take whole *pages* into the column, and a page
    is built to fill a scroll area on its own -- trailing spacer and all -- so each one claimed a share
    of the surplus and spread the group down the page. Taking only the blocks leaves that layout on the
    page's own view, where it is right, and nothing here has to argue it back down.

    **Test steps:**

    * add two short pages under one group, select it, and give the dialog far more height than it needs
    * verify each block takes exactly the height it asks for and they sit one directly after the other,
      with all the slack left below them
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    first = FakePage("Descriptions", [["Engine"]])
    second = FakePage("Images", [["Thumbnail"]])
    dialog.add_page(first, group="Plugins")
    dialog.add_page(second, group="Plugins")
    select_group(dialog, "Plugins")
    dialog.resize(600, 1200)
    dialog.show()
    dialog_ui(dialog).main_layout.activate()  # type: ignore[attr-defined]

    container = shown_group_container(dialog)
    blocks = stacked_group_blocks(dialog)
    assert [block.height() for block in blocks] == [block.sizeHint().height() for block in blocks]
    # the stretch, not the blocks, holds the slack: everything ends well above the container's bottom
    assert blocks[-1].geometry().bottom() < container.height()


def test_a_group_taller_than_the_viewport_still_scrolls(qtbot: QtBot) -> None:
    """Packing the blocks from the top must not cost the column its scrolling (#230).

    **Test steps:**

    * add a page whose block is far taller than the dialog under a group, and select the group
    * verify the group's scroll area has somewhere to scroll to
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    tall = FakePage("Descriptions", [["Engine"]])
    tall.frames[0].setMinimumHeight(3000)
    dialog.add_page(tall, group="Plugins")
    select_group(dialog, "Plugins")
    dialog.resize(600, 400)
    dialog.show()
    dialog_ui(dialog).main_layout.activate()  # type: ignore[attr-defined]

    area = dialog_ui(dialog).page_stack.currentWidget()  # type: ignore[attr-defined]
    assert area.verticalScrollBar().maximum() > 0


# region the no-match blank page


def test_a_filter_matching_nothing_blanks_the_right_hand_side(qtbot: QtBot) -> None:
    """A filter narrowed past its last match shows a blank page, not the page that was up (#230).

    Leaving the last-shown page standing beside an empty tree reads as a page that survived a filter
    nothing survived.

    **Test steps:**

    * add two pages and filter to text neither matches
    * verify the tree is empty and the stack shows the blank page
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    dialog.add_page(FakePage("Identity", [["Name"]]))
    dialog.add_page(FakePage("Images", [["Thumbnail"]]))

    dialog_ui(dialog).filter_edit.setText("no-such-setting")  # type: ignore[attr-defined]

    assert visible_titles(dialog) == []
    assert showing_blank_page(dialog) is True


def test_deleting_a_typo_puts_the_same_page_back(qtbot: QtBot) -> None:
    """Widening a no-match filter back to what it matched before returns to the same page (#230).

    Qt drops the tree's current row when the filter hides it and never restores it, so the title is
    remembered on the way into the blank -- otherwise one stray keystroke would leave the right-hand
    side empty until something was clicked.

    **Test steps:**

    * select a page, narrow the filter past it, then widen it back
    * verify the same page is shown again and its row is current
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    dialog.add_page(FakePage("Identity", [["Name"]]))
    images = FakePage("Images", [["Thumbnail"]])
    dialog.add_page(images)
    select_page(dialog, "Images")
    dialog_ui(dialog).filter_edit.setText("thumbnailx")  # type: ignore[attr-defined]
    assert showing_blank_page(dialog) is True

    dialog_ui(dialog).filter_edit.setText("thumbnail")  # type: ignore[attr-defined]

    assert current_page(dialog) is images
    assert dialog_ui(dialog).category_tree.currentIndex() == visible_index(dialog, "Images")  # type: ignore[attr-defined]


def test_replacing_a_no_match_filter_wholesale_does_not_restore_the_old_page(qtbot: QtBot) -> None:
    """A different filter is a different question, not a return to the old one (#230).

    Guards the trap the remembered title sets: typing ``imagesx``, then selecting all of it and pasting
    ``identity`` over it, must not bring Images back -- least of all while the tree lists only Identity.
    The remembered row is restored *only* when the new filter still shows it.

    **Test steps:**

    * select one page, narrow the filter past it, then replace the filter text wholesale with another
      page's term
    * verify the newly-matching page is shown, not the remembered one
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    identity = FakePage("Identity", [["Name"]])
    images = FakePage("Images", [["Thumbnail"]])
    dialog.add_page(identity)
    dialog.add_page(images)
    select_page(dialog, "Images")
    dialog_ui(dialog).filter_edit.setText("thumbnailx")  # type: ignore[attr-defined]

    dialog_ui(dialog).filter_edit.setText("name")  # type: ignore[attr-defined]

    assert current_page(dialog) is identity
    assert current_page(dialog) is not images
    assert visible_titles(dialog) == ["Identity"]


def test_leaving_a_no_match_filter_never_leaves_rows_beside_a_blank(qtbot: QtBot) -> None:
    """With rows back in the tree, something is always shown -- the first of them when there is
    nothing particular to return to (#230).

    **Test steps:**

    * narrow the filter past every page before anything was ever selected by hand, then widen it to
      match a page the dialog was not showing
    * verify the stack is no longer blank
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    dialog.add_page(FakePage("Identity", [["Name"]]))
    dialog.add_page(FakePage("Images", [["Thumbnail"]]))
    dialog_ui(dialog).filter_edit.setText("no-such-setting")  # type: ignore[attr-defined]
    assert showing_blank_page(dialog) is True

    dialog_ui(dialog).filter_edit.setText("thumbnail")  # type: ignore[attr-defined]

    assert showing_blank_page(dialog) is False
    assert visible_titles(dialog) == ["Images"]


def test_a_group_shown_before_a_no_match_filter_comes_back_as_the_group(qtbot: QtBot) -> None:
    """What is remembered is the row, group rows included -- not merely a page (#230).

    **Test steps:**

    * select a group, narrow the filter past every page under it, then widen it back
    * verify the group's stacked column is what returns
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    first = FakePage("Descriptions", [["Engine"]])
    second = FakePage("Images", [["Engine"]])
    dialog.add_page(first, group="Plugins")
    dialog.add_page(second, group="Plugins")
    select_group(dialog, "Plugins")
    dialog_ui(dialog).filter_edit.setText("enginex")  # type: ignore[attr-defined]
    assert showing_blank_page(dialog) is True

    dialog_ui(dialog).filter_edit.setText("engine")  # type: ignore[attr-defined]

    assert stacked_group_blocks(dialog) == first.frames + second.frames


def test_closing_on_a_no_match_filter_stores_the_page_it_would_return_to(
    qtbot: QtBot, fake_persistent_settings: FakeSettings
) -> None:
    """The blank page stands in for a real one, and that is the title saved (#228, #230).

    Storing nothing would leave whatever a previous session saved, so the next launch would restore a
    page the user had already navigated away from.

    **Test steps:**

    * select a page, narrow the filter past it, and save the filter state
    * verify the stored title is the page the blank is standing in for
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    dialog.add_page(FakePage("Identity", [["Name"]]))
    dialog.add_page(FakePage("Images", [["Thumbnail"]]))
    select_page(dialog, "Images")
    dialog_ui(dialog).filter_edit.setText("thumbnailx")  # type: ignore[attr-defined]

    dialog.save_filter_state()

    saved = SettingsDialogSettings()
    saved.load(fake_persistent_settings)  # type: ignore[arg-type]
    assert saved.selected_page_title == "Images"


def test_a_restored_filter_matching_nothing_starts_blank(qtbot: QtBot, fake_persistent_settings: FakeSettings) -> None:
    """A saved no-match filter comes back blank rather than showing the restored page beside an empty
    tree -- the one case where the stack does not outrank the tree (#228, #230).

    **Test steps:**

    * save a page title together with filter text matching nothing, then build a dialog and restore
    * verify the stack is blank, and that clearing the filter brings the saved page up
    """
    saved_settings = SettingsDialogSettings(selected_page_title="Images", filter_text="thumbnailx")
    saved_settings.save(fake_persistent_settings)  # type: ignore[arg-type]
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    dialog.add_page(FakePage("Identity", [["Name"]]))
    images = FakePage("Images", [["Thumbnail"]])
    dialog.add_page(images)

    dialog.restore_selected_page()

    assert showing_blank_page(dialog) is True

    dialog_ui(dialog).filter_edit.setText("")  # type: ignore[attr-defined]

    assert current_page(dialog) is images


# endregion


def test_a_filling_block_fills_alone_and_packs_with_others(qtbot: QtBot) -> None:
    """A block stretched by its page fills that page's view, and takes its natural height in a group
    column -- the same block, sized by whichever view is showing it (#230).

    This is what makes the group column possible without arguing anything down: a page's stretch is a
    statement about the page's *own* view, so the column simply does not carry it. Taking whole pages
    into the column instead meant the stretch came along and had to be suppressed.

    **Test steps:**

    * add a two-block page whose first block its page stretches, plus a second page, under one group
    * show the page alone, then the group, then the page alone again
    * verify the block fills only in the page's own view, and its stretch survives the round trip
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    page = FakePage("Descriptions", [["Engine"], ["Fonts"]])
    page.main_layout.setStretch(0, 1)  # the page stretches its first block, as DescriptionsPage does
    dialog.add_page(page, group="Plugins")
    dialog.add_page(FakePage("Images", [["Thumbnail"]]), group="Plugins")
    dialog.resize(600, 900)
    dialog.show()

    select_page(dialog, "Descriptions")
    dialog_ui(dialog).main_layout.activate()  # type: ignore[attr-defined]
    filling_alone = page.frames[0].height()

    select_group(dialog, "Plugins")
    dialog_ui(dialog).main_layout.activate()  # type: ignore[attr-defined]
    packed = page.frames[0].height()

    select_page(dialog, "Descriptions")
    dialog_ui(dialog).main_layout.activate()  # type: ignore[attr-defined]

    assert filling_alone > packed, "the block should fill its own page but not the group column"
    assert packed == page.frames[0].sizeHint().height(), "packed, it takes its natural height"
    assert page.frames[0].height() == filling_alone, "the page's stretch must survive the round trip"
    assert page.main_layout.stretch(0) == 1


# region dirty-state UI (#77)


def test_a_freshly_added_page_carries_no_dirty_marker(qtbot: QtBot) -> None:
    """A clean page's tree row shows its plain title, with no badge.

    **Test steps:**

    * add a page
    * verify its tree row's text is its plain title
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)

    dialog.add_page(FakePage("Registry"))

    assert visible_titles(dialog) == ["Registry"]


def test_a_dirty_pages_row_gets_the_dirty_marker_prefix(qtbot: QtBot) -> None:
    """A page reporting itself dirty is badged in the tree, the same idiom a dirty document tab uses.

    **Test steps:**

    * add a page and mark it dirty, then refresh
    * verify its tree row's text is prefixed with the dirty marker
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    page = FakePage("Registry")
    dialog.add_page(page)

    page.dirty = True
    refresh_dirty_state(dialog)

    assert visible_titles(dialog) == [f"{DIRTY_DOCK_MARKER}Registry"]


def test_a_settled_page_loses_its_dirty_marker(qtbot: QtBot) -> None:
    """Once a dirty page reports itself clean again, its badge is removed.

    **Test steps:**

    * add a page, mark it dirty and refresh, then mark it clean and refresh again
    * verify its tree row's text is back to its plain title
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    page = FakePage("Registry")
    dialog.add_page(page)
    page.dirty = True
    refresh_dirty_state(dialog)

    page.dirty = False
    refresh_dirty_state(dialog)

    assert visible_titles(dialog) == ["Registry"]


def test_restore_selected_page_still_finds_a_dirty_pages_row(
    qtbot: QtBot, fake_persistent_settings: FakeSettings
) -> None:
    """The dirty badge is display state, not part of a row's identity -- ``restore_selected_page``
    still finds a badged row by its plain, saved title (#77, #228).

    **Test steps:**

    * save a page's title, then build a dialog, register that page dirty, and refresh
    * call ``restore_selected_page``
    * verify the stack shows that page despite its badged row
    """
    SettingsDialogSettings(selected_page_title="Markdown Rendering").save(fake_persistent_settings)  # type: ignore[arg-type]
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    dialog.add_page(FakePage("Registry"))
    second = FakePage("Markdown Rendering")
    dialog.add_page(second)
    second.dirty = True
    refresh_dirty_state(dialog)

    dialog.restore_selected_page()

    assert current_page(dialog) is second
    assert visible_titles(dialog) == ["Registry", f"{DIRTY_DOCK_MARKER}Markdown Rendering"]


def test_apply_and_reset_actions_are_disabled_when_nothing_is_dirty(qtbot: QtBot) -> None:
    """With every registered page clean, all four toolbar actions start disabled.

    **Test steps:**

    * add a page (left clean)
    * verify every apply/reset action is disabled
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)

    dialog.add_page(FakePage("Registry"))

    ui = dialog_ui(dialog)
    assert ui.apply_current_page_action.isEnabled() is False  # type: ignore[attr-defined]
    assert ui.reset_current_page_action.isEnabled() is False  # type: ignore[attr-defined]
    assert ui.apply_all_action.isEnabled() is False  # type: ignore[attr-defined]
    assert ui.reset_all_action.isEnabled() is False  # type: ignore[attr-defined]


def test_apply_all_action_enables_when_an_unselected_page_is_dirty(qtbot: QtBot) -> None:
    """ "Apply All"/"Reset All" answer for every page, not just the selected one -- a dirty page that
    isn't current still enables them.

    **Test steps:**

    * add two pages, leave the first (auto-selected) clean, and dirty the second
    * refresh
    * verify "Apply All"/"Reset All" are enabled, but the current-page actions are not
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    dialog.add_page(FakePage("Registry"))
    second = FakePage("Markdown Rendering")
    dialog.add_page(second)

    second.dirty = True
    refresh_dirty_state(dialog)

    ui = dialog_ui(dialog)
    assert ui.apply_all_action.isEnabled() is True  # type: ignore[attr-defined]
    assert ui.reset_all_action.isEnabled() is True  # type: ignore[attr-defined]
    assert ui.apply_current_page_action.isEnabled() is False  # type: ignore[attr-defined]
    assert ui.reset_current_page_action.isEnabled() is False  # type: ignore[attr-defined]


def test_apply_current_page_action_enables_once_the_current_page_is_dirty(qtbot: QtBot) -> None:
    """The current-page actions track the *selected* page's own dirty state.

    **Test steps:**

    * add a page (auto-selected, clean) and mark it dirty
    * refresh
    * verify "Apply"/"Reset" are now enabled
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    page = FakePage("Registry")
    dialog.add_page(page)

    page.dirty = True
    refresh_dirty_state(dialog)

    ui = dialog_ui(dialog)
    assert ui.apply_current_page_action.isEnabled() is True  # type: ignore[attr-defined]
    assert ui.reset_current_page_action.isEnabled() is True  # type: ignore[attr-defined]


def test_committing_a_page_resyncs_its_frame_baseline_so_the_badge_clears(qtbot: QtBot) -> None:
    """Applying a dirty page's changes settles both the page-level badge and its frame highlight --
    the frame baseline is resynced, not just ``save_changes`` called (#77).

    **Test steps:**

    * add a page with one editable frame, edit its field, and refresh
    * trigger "Apply"
    * verify the badge is gone and the frame's ``dirty`` property is off again
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    page = FakePage("Registry", [["Name"]])
    dialog.add_page(page)
    page.edits[0].setText("changed")
    page.dirty = True
    refresh_dirty_state(dialog)
    assert visible_titles(dialog) == [f"{DIRTY_DOCK_MARKER}Registry"]

    dialog_ui(dialog).apply_current_page_action.trigger()  # type: ignore[attr-defined]

    assert page.save_calls == 1
    assert visible_titles(dialog) == ["Registry"]
    refresh_dirty_state(dialog)
    assert page.frames[0].property("dirty") is False


def test_editing_a_frames_field_tints_it(qtbot: QtBot) -> None:
    """Typing into one of the current page's frames pinks its background (#77).

    The tint is the ``dirty`` dynamic property flipping true under the property-selector stylesheet
    every block wears from registration -- so the property is what's asserted, plus the stylesheet's
    presence once, since the property alone paints nothing without it.

    **Test steps:**

    * add a page with one editable frame and edit its field
    * refresh
    * verify the frame's ``dirty`` property is on, under the dirty-tint stylesheet
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    page = FakePage("Registry", [["Name"]])
    dialog.add_page(page)

    page.edits[0].setText("changed")
    refresh_dirty_state(dialog)

    assert page.frames[0].property("dirty") is True
    assert page.frames[0].styleSheet() == settings_dialog.DIRTY_FRAME_STYLESHEET


def test_a_clean_frame_has_no_tint(qtbot: QtBot) -> None:
    """A frame that has never been edited keeps its ``dirty`` property off (#77).

    **Test steps:**

    * add a page with one editable frame, left untouched
    * refresh
    * verify the frame's ``dirty`` property is off
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    page = FakePage("Registry", [["Name"]])
    dialog.add_page(page)

    refresh_dirty_state(dialog)

    assert page.frames[0].property("dirty") is False


def test_auto_apply_commits_a_dirty_page_on_the_next_poll_tick(qtbot: QtBot) -> None:
    """With auto-apply on, a page found dirty during a poll tick is committed immediately, without
    waiting for an explicit Apply (#77).

    **Test steps:**

    * add a page, check auto-apply, then mark the page dirty
    * run one poll tick
    * verify the page's ``save_changes`` was called and its badge is gone
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    page = FakePage("Registry")
    dialog.add_page(page)
    auto_apply_check_box(dialog).set_checked(True)
    page.dirty = True

    poll_dirty_state(dialog)

    assert page.save_calls == 1


def test_auto_apply_leaves_a_clean_page_alongside_a_dirty_one_untouched(qtbot: QtBot) -> None:
    """With auto-apply on, a poll tick commits only the pages that are actually dirty -- a clean
    sibling is skipped, not saved along with it (#77).

    **Test steps:**

    * add two pages, check auto-apply, and mark only the second dirty
    * run one poll tick
    * verify only the second page's ``save_changes`` was called
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    first = FakePage("Registry")
    second = FakePage("Markdown Rendering")
    dialog.add_page(first)
    dialog.add_page(second)
    auto_apply_check_box(dialog).set_checked(True)
    second.dirty = True

    poll_dirty_state(dialog)

    assert first.save_calls == 0
    assert second.save_calls == 1


def test_auto_apply_off_leaves_a_dirty_page_uncommitted(qtbot: QtBot) -> None:
    """With auto-apply off (the default), a poll tick never commits anything on its own -- only an
    explicit Apply/Reset does (#77).

    **Test steps:**

    * add a page and mark it dirty, auto-apply left off
    * run one poll tick
    * verify the page's ``save_changes`` was never called
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    page = FakePage("Registry")
    dialog.add_page(page)
    page.dirty = True

    poll_dirty_state(dialog)

    assert page.save_calls == 0


def test_save_filter_state_persists_auto_apply(qtbot: QtBot, fake_persistent_settings: FakeSettings) -> None:
    """:meth:`SettingsDialog.save_filter_state` writes the auto-apply toggle too (#77).

    **Test steps:**

    * check the auto-apply checkbox
    * call ``save_filter_state``
    * verify it comes back checked from a fresh `SettingsDialogSettings`
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    auto_apply_check_box(dialog).set_checked(True)

    dialog.save_filter_state()

    saved = SettingsDialogSettings()
    saved.load(fake_persistent_settings)  # type: ignore[arg-type]
    assert saved.auto_apply is True


def test_starts_with_the_persisted_auto_apply_toggle(qtbot: QtBot, fake_persistent_settings: FakeSettings) -> None:
    """A freshly-built dialog restores the auto-apply toggle from storage (#77).

    **Test steps:**

    * save auto-apply as checked, then build a dialog
    * verify its auto-apply checkbox comes up checked
    """
    SettingsDialogSettings(auto_apply=True).save(fake_persistent_settings)  # type: ignore[arg-type]

    dialog = SettingsDialog()
    qtbot.addWidget(dialog)

    assert auto_apply_check_box(dialog).is_checked() is True


# endregion
