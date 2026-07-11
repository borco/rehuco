"""Tests for SettingsDialog: the filterable category tree + per-category stacked page shell."""

from PySide6.QtCore import QModelIndex
from PySide6.QtWidgets import QWidget
from pytestqt.qtbot import QtBot
from rehuco_agent.dialogs.settings_dialog import SettingsDialog


# region Sample classes
class FakePage(QWidget):
    """A minimal `SettingsPage` stand-in for exercising `SettingsDialog` without a real page."""

    def __init__(self, title: str, field_labels: list[str] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__title = title
        self.__field_labels = field_labels or []
        self.save_calls = 0
        self.drop_calls = 0

    @property
    def title(self) -> str:
        """This page's category-tree label."""
        return self.__title

    def field_labels(self) -> list[str]:
        """The stubbed field labels this page reports for filtering."""
        return self.__field_labels

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


def select_page(dialog: SettingsDialog, title: str) -> None:
    """Select the tree row for the page titled ``title``.

    :param dialog: the dialog whose tree to select in.
    :param title: the page's title, as passed to :meth:`SettingsDialog.add_page`'s page.
    :raises AssertionError: if no visible row has that title (e.g. filtered out).
    """
    tree = dialog_ui(dialog).category_tree  # type: ignore[attr-defined]
    model = tree.model()
    for row in range(model.rowCount()):
        index = model.index(row, 0)
        if model.data(index) == title:
            tree.setCurrentIndex(index)
            return
    raise AssertionError(f"no visible row titled {title!r}")


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
    dialog.add_page(FakePage("Registry", ["Register", "Unregister"]))
    dialog.add_page(FakePage("Markdown Rendering", ["Engine", "CSS"]))

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
    dialog.add_page(FakePage("Markdown Rendering", ["Maximum image width"]))

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
    dialog.add_page(FakePage("Registry", ["Register"]))
    dialog.add_page(FakePage("Markdown Rendering", ["Engine"]))
    dialog_ui(dialog).filter_edit.setText("regist")  # type: ignore[attr-defined]

    dialog_ui(dialog).filter_edit.setText("")  # type: ignore[attr-defined]

    assert dialog_ui(dialog).category_tree.model().rowCount() == 2  # type: ignore[attr-defined]


def test_save_current_page_action_saves_only_the_selected_page(qtbot: QtBot) -> None:
    """Triggering "Save" saves the currently-selected page and leaves the other untouched.

    **Test steps:**

    * add two pages, select the second
    * trigger ``save_current_page_action``
    * verify only the second page's ``save_changes`` was called
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    first = FakePage("Registry")
    second = FakePage("Markdown Rendering")
    dialog.add_page(first)
    dialog.add_page(second)
    select_page(dialog, "Markdown Rendering")

    dialog_ui(dialog).save_current_page_action.trigger()  # type: ignore[attr-defined]

    assert first.save_calls == 0
    assert second.save_calls == 1


def test_save_all_action_saves_every_page(qtbot: QtBot) -> None:
    """Triggering "Save All" saves every registered page, not just the selected one.

    **Test steps:**

    * add two pages, select the first (the default)
    * trigger ``save_all_action``
    * verify both pages' ``save_changes`` were called
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    first = FakePage("Registry")
    second = FakePage("Markdown Rendering")
    dialog.add_page(first)
    dialog.add_page(second)

    dialog_ui(dialog).save_all_action.trigger()  # type: ignore[attr-defined]

    assert first.save_calls == 1
    assert second.save_calls == 1


def test_drop_current_page_action_drops_only_the_selected_page(qtbot: QtBot) -> None:
    """Triggering "Drop" discards only the currently-selected page's changes.

    **Test steps:**

    * add two pages, select the second
    * trigger ``drop_current_page_action``
    * verify only the second page's ``drop_changes`` was called
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    first = FakePage("Registry")
    second = FakePage("Markdown Rendering")
    dialog.add_page(first)
    dialog.add_page(second)
    select_page(dialog, "Markdown Rendering")

    dialog_ui(dialog).drop_current_page_action.trigger()  # type: ignore[attr-defined]

    assert first.drop_calls == 0
    assert second.drop_calls == 1


def test_drop_all_action_drops_every_page(qtbot: QtBot) -> None:
    """Triggering "Drop All" discards every registered page's changes, not just the selected one.

    **Test steps:**

    * add two pages, select the first (the default)
    * trigger ``drop_all_action``
    * verify both pages' ``drop_changes`` were called
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    first = FakePage("Registry")
    second = FakePage("Markdown Rendering")
    dialog.add_page(first)
    dialog.add_page(second)

    dialog_ui(dialog).drop_all_action.trigger()  # type: ignore[attr-defined]

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

    ui.save_all_action.trigger()  # type: ignore[attr-defined]
    ui.save_current_page_action.trigger()  # type: ignore[attr-defined]
    ui.drop_all_action.trigger()  # type: ignore[attr-defined]
    ui.drop_current_page_action.trigger()  # type: ignore[attr-defined]
