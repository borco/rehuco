"""Tests for HeaderSectionsMenu: a header's context menu of section visibility, and its saved state."""

from borco_pyside.widgets import HeaderSectionsMenu
from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, QPoint, Qt
from PySide6.QtWidgets import QMenu, QTableView
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot

HEADERS: list[str | None] = ["Name", "Size", "Date"]


# region Sample classes


class HeaderModel(QAbstractTableModel):
    """A row-less model whose columns are named by a list the test can change."""

    def __init__(self, labels: list[str | None]) -> None:
        super().__init__()
        self.labels = labels

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:  # noqa: N802
        del parent
        return 0

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:  # noqa: N802
        del parent
        return len(self.labels)

    def headerData(  # noqa: N802
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> str | None:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.labels[section]
        return None

    def set_labels(self, labels: list[str | None]) -> None:
        """Replace the column labels, announcing the change of count and text.

        :param labels: the new labels, one per column.
        """
        self.beginResetModel()
        self.labels = labels
        self.endResetModel()


# endregion
# region HeaderSectionsMenu tests


class Setup:
    """A table view over a model with ``HEADERS`` columns, and the menu attached to its header."""

    def __init__(self, qtbot: QtBot) -> None:
        self.model = HeaderModel(list(HEADERS))
        self.view = QTableView()
        qtbot.addWidget(self.view)
        self.view.setModel(self.model)
        self.header = self.view.horizontalHeader()
        self.menu = HeaderSectionsMenu(self.header)

    def labels(self, menu: QMenu) -> list[str]:
        """The menu's action texts.

        :param menu: the menu to read.
        :returns: its action texts in order.
        """
        return [action.text() for action in menu.actions()]

    def checked(self, menu: QMenu) -> list[bool]:
        """The menu's checkmarks.

        :param menu: the menu to read.
        :returns: each action's checked state in order.
        """
        return [action.isChecked() for action in menu.actions()]


@fixture
def setup(qtbot: QtBot) -> Setup:
    """A header with a menu attached.

    :param qtbot: pytest-qt bot.
    :returns: the view, its model, header and menu.
    """
    return Setup(qtbot)


def test_attaching_makes_sections_movable_and_the_header_menu_custom(setup: Setup) -> None:
    """Attaching changes the header only in being movable and answering its own context menu.

    **Test steps:**

    * attach a menu to a header
    * verify its sections are movable and its context menu policy is custom
    """
    assert setup.header.sectionsMovable()
    assert setup.header.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu


def test_the_menu_has_one_checked_action_per_section_labeled_from_the_model(setup: Setup) -> None:
    """Every section gets a checkable action, labeled by the model and checked while shown.

    **Test steps:**

    * hide the second section, then build the menu
    * verify the labels are the model's and only the hidden section is unchecked
    """
    setup.header.setSectionHidden(1, True)

    menu = setup.menu.build_menu()

    assert setup.labels(menu) == HEADERS
    assert setup.checked(menu) == [True, False, True]
    assert all(action.isCheckable() for action in menu.actions())


def test_a_section_without_a_label_is_named_by_its_position(setup: Setup) -> None:
    """A model with no header text for a section still gives its action a name.

    **Test steps:**

    * clear the second section's label, then build the menu
    * verify its action reads ``2``
    """
    setup.model.set_labels(["Name", None, "Date"])

    assert setup.labels(setup.menu.build_menu())[1] == "2"


def test_a_header_without_a_model_gives_an_empty_menu(qtbot: QtBot) -> None:
    """With no model there are no sections to list.

    **Test steps:**

    * attach a menu to a view that has no model
    * verify the built menu has no actions
    """
    view = QTableView()
    qtbot.addWidget(view)

    assert not HeaderSectionsMenu(view.horizontalHeader()).build_menu().actions()


def test_a_header_without_a_model_refuses_any_state(setup: Setup, qtbot: QtBot) -> None:
    """With no model there is nothing to lay out, so a restore fails without touching the header.

    **Test steps:**

    * save a state from the three-column header
    * restore it onto a view that has no model
    * verify the restore reports failure and that header still has no sections
    """
    state = setup.menu.save_state()
    view = QTableView()
    qtbot.addWidget(view)
    menu = HeaderSectionsMenu(view.horizontalHeader())

    assert not menu.restore_state(state)

    assert view.horizontalHeader().count() == 0


def test_toggling_an_action_hides_and_shows_its_section(setup: Setup) -> None:
    """Unchecking an action hides its section and checking it again shows it.

    **Test steps:**

    * uncheck the first action; verify its section is hidden
    * check it again; verify the section is shown
    """
    menu = setup.menu.build_menu()

    menu.actions()[0].setChecked(False)
    assert setup.header.isSectionHidden(0)

    menu.actions()[0].setChecked(True)
    assert not setup.header.isSectionHidden(0)


def test_the_last_visible_section_cannot_be_hidden(setup: Setup) -> None:
    """The only shown section's action is disabled, and unchecking it anyway changes nothing.

    **Test steps:**

    * hide all but the first section, then build the menu
    * verify the first action is disabled and the others are enabled
    * uncheck the first action regardless
    * verify its section is still shown
    """
    setup.header.setSectionHidden(1, True)
    setup.header.setSectionHidden(2, True)
    menu = setup.menu.build_menu()

    assert [action.isEnabled() for action in menu.actions()] == [False, True, True]

    menu.actions()[0].setChecked(False)
    assert not setup.header.isSectionHidden(0)


def test_toggling_an_action_announces_the_change_of_visibility(setup: Setup, qtbot: QtBot) -> None:
    """Each section the menu hides or shows is announced, so a consumer mirroring the choice can follow it.

    **Test steps:**

    * uncheck the first action, then check it again
    * verify each announced the change
    """
    menu = setup.menu.build_menu()

    with qtbot.waitSignal(setup.menu.sections_visibility_changed):
        menu.actions()[0].setChecked(False)
    with qtbot.waitSignal(setup.menu.sections_visibility_changed):
        menu.actions()[0].setChecked(True)


def test_a_refused_hide_of_the_last_section_announces_nothing(setup: Setup, qtbot: QtBot) -> None:
    """Nothing changed, so nothing is said.

    **Test steps:**

    * hide all but the first section, then uncheck its action anyway
    * verify no change was announced
    """
    setup.header.setSectionHidden(1, True)
    setup.header.setSectionHidden(2, True)
    menu = setup.menu.build_menu()

    with qtbot.assertNotEmitted(setup.menu.sections_visibility_changed):
        menu.actions()[0].setChecked(False)


def test_an_action_for_a_section_already_so_announces_nothing(setup: Setup, qtbot: QtBot) -> None:
    """A menu built before something else hid a section changes nothing by unchecking it again, and says nothing.

    **Test steps:**

    * build the menu, then hide the first section on the header directly
    * uncheck the first action, still checked from when the menu was built
    * verify the section stays hidden and no change was announced
    """
    menu = setup.menu.build_menu()
    setup.header.setSectionHidden(0, True)

    with qtbot.assertNotEmitted(setup.menu.sections_visibility_changed):
        menu.actions()[0].setChecked(False)

    assert setup.header.isSectionHidden(0)


def test_a_restore_announces_a_change_of_visibility_and_only_a_change(setup: Setup, qtbot: QtBot) -> None:
    """A restore that hides or shows a section is announced like a toggle, including the show-all fallback; one
    that leaves every section as it was is not.

    **Test steps:**

    * save a state with a section hidden, show it again, and restore that state
    * verify the change was announced
    * restore the same state again
    * verify nothing was announced
    * restore bytes the header refuses
    * verify the fallback showing every section was announced
    """
    setup.header.setSectionHidden(1, True)
    state = setup.menu.save_state()
    setup.header.setSectionHidden(1, False)

    with qtbot.waitSignal(setup.menu.sections_visibility_changed):
        setup.menu.restore_state(state)
    with qtbot.assertNotEmitted(setup.menu.sections_visibility_changed):
        setup.menu.restore_state(state)
    with qtbot.waitSignal(setup.menu.sections_visibility_changed):
        setup.menu.restore_state(b"not a header state")


def test_restoring_a_saved_state_brings_back_visibility_order_and_checkmarks(setup: Setup) -> None:
    """A state saved from one header restores onto another, and the next menu reads the restored header.

    **Test steps:**

    * hide a section and move another, then save the state
    * show everything, restore the state
    * verify the visibility and order are back and the menu's checkmarks match
    """
    setup.header.setSectionHidden(1, True)
    setup.header.moveSection(2, 0)
    state = setup.menu.save_state()
    setup.header.setSectionHidden(1, False)
    setup.header.moveSection(0, 2)

    assert setup.menu.restore_state(state)

    assert setup.header.isSectionHidden(1)
    assert setup.header.visualIndex(2) == 0
    assert setup.menu.build_menu().actions()[1].isChecked() is False


def test_a_state_that_fails_to_restore_leaves_every_section_shown(setup: Setup) -> None:
    """Garbage bytes are refused and every section ends up visible.

    **Test steps:**

    * hide a section, then restore bytes the header cannot parse
    * verify the restore reports failure and no section is hidden
    """
    setup.header.setSectionHidden(1, True)

    assert not setup.menu.restore_state(b"not a header state")

    assert setup.header.hiddenSectionCount() == 0


def test_a_state_hiding_every_section_leaves_every_section_shown(setup: Setup) -> None:
    """A state that would leave nothing visible is treated as a failed restore.

    **Test steps:**

    * hide every section and save that state; show them again
    * restore it
    * verify the restore reports failure and no section is hidden
    """
    for section in range(len(HEADERS)):
        setup.header.setSectionHidden(section, True)
    state = setup.menu.save_state()
    for section in range(len(HEADERS)):
        setup.header.setSectionHidden(section, False)

    assert not setup.menu.restore_state(state)

    assert setup.header.hiddenSectionCount() == 0


def test_a_state_saved_from_more_sections_than_the_model_has_is_refused(setup: Setup) -> None:
    """A state from a wider header would grow this one past its model; it is refused and the header kept.

    **Test steps:**

    * save the three-column state, then shrink the model to two columns and move a section
    * restore the saved state
    * verify the restore reports failure, the header still has two sections in the order it had, and
      nothing is hidden
    """
    setup.header.setSectionHidden(1, True)
    state = setup.menu.save_state()
    setup.model.set_labels(HEADERS[:2])
    setup.header.moveSection(0, 1)

    assert not setup.menu.restore_state(state)

    assert setup.header.count() == 2
    assert setup.header.visualIndex(0) == 1
    assert setup.header.hiddenSectionCount() == 0


def test_a_state_saved_from_fewer_sections_than_the_model_has_applies_to_those(setup: Setup) -> None:
    """A state from a narrower header restores the sections it knows and leaves the new ones shown.

    **Test steps:**

    * save a state with the second section hidden, then grow the model by a column
    * restore the saved state
    * verify the restore reports success, the second section is hidden and the new one shown
    """
    setup.header.setSectionHidden(1, True)
    state = setup.menu.save_state()
    setup.model.set_labels([*HEADERS, "Extra"])

    assert setup.menu.restore_state(state)

    assert [setup.header.isSectionHidden(i) for i in range(4)] == [False, True, False, False]


def test_a_model_whose_column_count_changes_rebuilds_the_menu(setup: Setup) -> None:
    """The menu is read from the header each time, so a new column appears in the next one.

    **Test steps:**

    * add a column to the model and label it
    * verify the next built menu has four actions, the last being the new label
    """
    setup.model.set_labels([*HEADERS, "Extra"])

    assert setup.labels(setup.menu.build_menu()) == [*HEADERS, "Extra"]


def test_a_context_menu_request_opens_the_menu_at_the_click(setup: Setup, mocker: MockerFixture) -> None:
    """Right-clicking the header executes the built menu at the click's global position.

    **Test steps:**

    * make the menu builder return a mock menu
    * request the header's context menu at a position
    * verify the mock was executed at that position in global coordinates
    """
    menu = mocker.MagicMock()
    mocker.patch.object(setup.menu, "build_menu", return_value=menu)
    position = QPoint(3, 4)

    setup.header.customContextMenuRequested.emit(position)

    menu.exec.assert_called_once_with(setup.header.mapToGlobal(position))
    menu.deleteLater.assert_called_once_with()


# endregion
