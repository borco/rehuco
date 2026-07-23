"""Tests for SettingsDialog: the filterable category tree + per-category stacked page shell."""

from typing import Any

from PySide6.QtCore import QModelIndex
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
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
        self.save_calls = 0
        self.drop_calls = 0
        self.frames: list[QFrame] = []

        layout = QVBoxLayout(self)
        for terms in groups or []:
            frame = QFrame(self)
            frame_layout = QVBoxLayout(frame)
            for term in terms:
                frame_layout.addWidget(QLabel(term, frame))
            layout.addWidget(frame)
            self.frames.append(frame)

    @property
    def title(self) -> str:
        """This page's category-tree label."""
        return self.__title

    def is_dirty(self) -> bool:
        """Always clean -- not exercised by these tests."""
        return False

    def save_changes(self) -> None:
        """Record that a save was requested."""
        self.save_calls += 1

    def drop_changes(self) -> None:
        """Record that a drop was requested."""
        self.drop_calls += 1


# endregion


def dialog_ui(dialog: SettingsDialog) -> object:
    """Read the dialog's private ``.ui`` object, for reaching its tree/stack/toolbar in tests.

    :param dialog: the dialog to inspect.
    :returns: the generated ``Ui_SettingsDialog`` instance.
    """
    return dialog._SettingsDialog__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access


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
    assert ui.page_stack.count() == 1  # type: ignore[attr-defined]
    assert ui.page_stack.widget(0) is page  # type: ignore[attr-defined]


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

    assert dialog_ui(dialog).page_stack.currentWidget() is page  # type: ignore[attr-defined]


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

    assert dialog_ui(dialog).page_stack.currentWidget() is second  # type: ignore[attr-defined]


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

    assert dialog_ui(dialog).page_stack.currentWidget() is page  # type: ignore[attr-defined]


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

    assert dialog_ui(dialog).page_stack.currentWidget() is grouped  # type: ignore[attr-defined]


def test_selecting_a_group_row_leaves_the_shown_page_untouched(qtbot: QtBot) -> None:
    """A group row is a header carrying no page, so selecting it changes nothing (#76).

    **Test steps:**

    * add a grouped page (auto-selected) with a frame the live filter hides
    * select the group's own row
    * verify the stack still shows the page and its frame filtering is unchanged
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    page = FakePage("Descriptions", [["Engine"], ["Images"]])
    dialog.add_page(page, group="Editors")
    dialog_ui(dialog).filter_edit.setText("engine")  # type: ignore[attr-defined]

    dialog_ui(dialog).category_tree.setCurrentIndex(visible_index(dialog, "Editors"))  # type: ignore[attr-defined]

    assert dialog_ui(dialog).page_stack.currentWidget() is page  # type: ignore[attr-defined]
    assert page.frames[1].isVisibleTo(page) is False


def test_typing_filter_text_with_a_group_row_selected_does_nothing(qtbot: QtBot) -> None:
    """Filtering while a group header is the current row is a no-op: it has no frames of its own to
    show or hide, and there is no page under it to reach from here (#76).

    **Test steps:**

    * add a grouped page, then select the group's own row
    * type filter text
    * verify it doesn't raise, and the page's frames are left as they were (untouched, not hidden)
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    page = FakePage("Descriptions", [["Engine"], ["Images"]])
    dialog.add_page(page, group="Editors")
    dialog_ui(dialog).category_tree.setCurrentIndex(visible_index(dialog, "Editors"))  # type: ignore[attr-defined]

    dialog_ui(dialog).filter_edit.setText("engine")  # type: ignore[attr-defined]

    assert [frame.isVisibleTo(page) for frame in page.frames] == [True, True]


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
    SettingsDialogSettings(
        filter_text="engine", show_full_page_on_title_match=True, show_full_group_on_title_match=True
    ).save(fake_persistent_settings)  # type: ignore[arg-type]

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
