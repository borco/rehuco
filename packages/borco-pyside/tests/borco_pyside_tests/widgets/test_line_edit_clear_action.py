"""Tests for LineEditClearActionFilter: the app-wide QLineEdit clear action."""

from collections.abc import Iterator

from borco_pyside.widgets.line_edit_clear_action import LineEditClearActionFilter
from PySide6.QtCore import QEvent, QSignalBlocker
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QComboBox, QLineEdit, QSpinBox, QStyle, QWidget
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from shiboken6 import invalidate, isValid

WAIT = 10_000
"""How long a ``waitUntil`` here is given -- generous for the reason the QtAds tests give: the first
wait in a Qt test can spend seconds draining earlier tests' ``deleteLater`` backlog."""


@fixture
def installed_filter(qtbot: QtBot) -> Iterator[LineEditClearActionFilter]:
    """Install a ``LineEditClearActionFilter`` on the real app for one test, then remove it.

    :param qtbot: pytest-qt bot, ensuring a QApplication exists.
    :returns: the installed filter.
    """
    del qtbot
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    line_edit_filter = LineEditClearActionFilter()
    app.installEventFilter(line_edit_filter)
    yield line_edit_filter
    app.removeEventFilter(line_edit_filter)


def test_showing_a_line_edit_adds_a_hidden_trailing_action_drawn_as_qts_clear_button(
    installed_filter: LineEditClearActionFilter, qtbot: QtBot
) -> None:
    """Showing a QLineEdit gets it a trailing action, invisible while it holds no text, drawn with the
    style's own clear icon (#406).

    **Test steps:**

    * show a fresh, empty QLineEdit
    * verify it now has exactly one trailing action, hidden, whose icon is the style's clear icon
    """
    del installed_filter
    line_edit = QLineEdit()
    qtbot.addWidget(line_edit)

    line_edit.show()

    actions = line_edit.actions()
    assert len(actions) == 1
    assert actions[0].isVisible() is False
    expected = line_edit.style().standardIcon(QStyle.StandardPixmap.SP_LineEditClearButton, None, line_edit)
    assert actions[0].icon().pixmap(16).toImage() == expected.pixmap(16).toImage()


def test_a_line_edit_showing_qts_own_clear_button_gets_no_second_one(
    installed_filter: LineEditClearActionFilter, qtbot: QtBot
) -> None:
    """A line edit that turned Qt's clear button on itself keeps that one alone (#406).

    **Test steps:**

    * turn on Qt's clear button on a fresh line edit, then show it
    * verify the filter added no action of its own
    """
    del installed_filter
    line_edit = QLineEdit()
    line_edit.setClearButtonEnabled(True)
    qtbot.addWidget(line_edit)

    line_edit.show()

    assert line_edit.actions() == []


def test_the_action_becomes_visible_once_the_line_edit_holds_text(
    installed_filter: LineEditClearActionFilter, qtbot: QtBot
) -> None:
    """Typing text into the line edit reveals the clear action.

    **Test steps:**

    * show a line edit, then set its text
    * verify the action becomes visible
    """
    del installed_filter
    line_edit = QLineEdit()
    qtbot.addWidget(line_edit)
    line_edit.show()

    line_edit.setText("hello")

    assert line_edit.actions()[0].isVisible() is True


def test_the_action_hides_again_once_the_text_is_cleared(
    installed_filter: LineEditClearActionFilter, qtbot: QtBot
) -> None:
    """Clearing the text back to empty hides the action again.

    **Test steps:**

    * show a line edit, set text, then clear it
    * verify the action becomes hidden again
    """
    del installed_filter
    line_edit = QLineEdit()
    qtbot.addWidget(line_edit)
    line_edit.show()
    line_edit.setText("hello")

    line_edit.setText("")

    assert line_edit.actions()[0].isVisible() is False


def test_triggering_the_action_clears_the_text_and_restores_focus(
    installed_filter: LineEditClearActionFilter, qtbot: QtBot, mocker: MockerFixture
) -> None:
    """Triggering the action clears the text and asks for keyboard focus back.

    Spies on ``setFocus`` rather than asserting real OS-level ``hasFocus()`` -- the offscreen test
    platform has no real window manager, so a widget never actually becomes active there
    (``QtWarningMsg: This plugin does not support raise()``) regardless of what the code under test
    does; asserting the call happened is what's actually verifiable here.

    **Test steps:**

    * show a line edit with text, spy on its ``setFocus``, then trigger its clear action
    * verify the text is empty and ``setFocus`` was called
    """
    del installed_filter
    line_edit = QLineEdit()
    qtbot.addWidget(line_edit)
    line_edit.show()
    line_edit.setText("hello")
    focus_spy = mocker.spy(line_edit, "setFocus")

    line_edit.actions()[0].trigger()

    assert line_edit.text() == ""
    focus_spy.assert_called_once()


def test_the_action_resyncs_after_a_signal_blocked_settext(
    installed_filter: LineEditClearActionFilter, qtbot: QtBot
) -> None:
    """A ``setText`` made under a ``QSignalBlocker`` -- the field toolkit's echo-guard pattern, used
    to restore a value without re-triggering a write-through -- still gets the action's visibility
    resynced, via the paint-event fallback rather than the (deliberately suppressed) ``textChanged``.

    Reproduces the real bug: clearing a field's text (hiding the action), then having something
    restore the text the *signal-blocked* way (e.g. ``revert()``) left the action stuck hidden.

    **Test steps:**

    * show a line edit, clear it (hiding the action), then set its text back under a signal blocker
    * send it a synthetic paint event (standing in for the real repaint ``setText`` schedules)
    * verify the action is visible again
    """
    del installed_filter
    line_edit = QLineEdit()
    qtbot.addWidget(line_edit)
    line_edit.show()
    line_edit.setText("hello")
    line_edit.setText("")
    assert line_edit.actions()[0].isVisible() is False

    with QSignalBlocker(line_edit):
        line_edit.setText("restored")
    assert line_edit.actions()[0].isVisible() is False  # not yet -- textChanged was suppressed

    QApplication.sendEvent(line_edit, QEvent(QEvent.Type.Paint))

    assert line_edit.actions()[0].isVisible() is True


def test_a_paint_event_before_any_show_is_a_no_op(installed_filter: LineEditClearActionFilter, qtbot: QtBot) -> None:
    """A paint event reaching a line edit that was never shown (so has no clear action yet) is ignored.

    **Test steps:**

    * build a line edit but never show it
    * send it a paint event directly
    * verify nothing raises and it still carries no actions
    """
    del installed_filter
    line_edit = QLineEdit()
    qtbot.addWidget(line_edit)

    QApplication.sendEvent(line_edit, QEvent(QEvent.Type.Paint))

    assert line_edit.actions() == []


def test_a_second_show_does_not_add_a_second_action(installed_filter: LineEditClearActionFilter, qtbot: QtBot) -> None:
    """Hiding and re-showing the same line edit doesn't install a second clear action.

    **Test steps:**

    * show a line edit, hide it, then show it again
    * verify it still has exactly one trailing action
    """
    del installed_filter
    line_edit = QLineEdit()
    qtbot.addWidget(line_edit)
    line_edit.show()

    line_edit.hide()
    line_edit.show()

    assert len(line_edit.actions()) == 1


def test_a_shown_non_line_edit_widget_is_left_untouched(
    installed_filter: LineEditClearActionFilter, qtbot: QtBot
) -> None:
    """The filter ignores Show events for widgets that aren't QLineEdit.

    **Test steps:**

    * show a plain QWidget
    * verify nothing raises and it carries no actions
    """
    del installed_filter
    widget = QWidget()
    qtbot.addWidget(widget)

    widget.show()

    assert widget.actions() == []


def test_a_spin_boxs_internal_line_edit_is_left_untouched(
    installed_filter: LineEditClearActionFilter, qtbot: QtBot
) -> None:
    """The filter skips a ``QLineEdit`` owned by a ``QAbstractSpinBox`` -- "clear the text" there
    doesn't mean "clear the value" (see the filter's own docstring); a spin-box-owning field needs
    a clear affordance with spin-box-correct semantics, not this generic text-based one.

    **Test steps:**

    * show a ``QSpinBox`` (which shows its own internal line edit as part of showing)
    * verify its internal line edit carries no clear action
    """
    del installed_filter
    spin_box = QSpinBox()
    qtbot.addWidget(spin_box)

    spin_box.show()

    internal_line_edit = spin_box.lineEdit()
    assert internal_line_edit is not None
    assert internal_line_edit.actions() == []


def test_an_editable_combo_boxs_internal_line_edit_is_left_untouched(
    installed_filter: LineEditClearActionFilter, qtbot: QtBot
) -> None:
    """The filter skips a ``QLineEdit`` owned by an editable ``QComboBox`` -- its text renders the
    combo's current value, so a generic text-based clear would desync text from ``currentIndex()``
    exactly as it would for a spin box (see the filter's own docstring).

    **Test steps:**

    * show an editable ``QComboBox`` (which shows its own internal line edit as part of showing)
    * verify its internal line edit carries no clear action
    """
    del installed_filter
    combo_box = QComboBox()
    combo_box.setEditable(True)
    qtbot.addWidget(combo_box)

    combo_box.show()

    internal_line_edit = combo_box.lineEdit()
    assert internal_line_edit is not None
    assert internal_line_edit.actions() == []


def test_a_field_specific_trailing_action_coexists_untouched(
    installed_filter: LineEditClearActionFilter, qtbot: QtBot
) -> None:
    """A field's own trailing action, added before the line edit is ever shown, is left alone by the
    filter -- it gets exactly one more action (the clear one), and only that one toggles visibility
    with the text.

    :class:`~borco_pyside.widgets.line_edit_clear_action.LineEditClearActionFilter`'s docstring notes
    that a newly-added trailing action renders nearest the text, pushing earlier ones outward
    (confirmed empirically) -- ``QLineEdit.actions()`` itself always lists actions in insertion
    order regardless of that visual placement, so this test checks behavior, not screen position.

    **Test steps:**

    * add a trailing action to a fresh line edit and make it visible, then show the line edit
      (installing the filter's clear action second)
    * verify there are now two actions and the second is the filter's own
    * set text and verify only the filter's action reacts; the field's own stays as set
    """
    del installed_filter
    line_edit = QLineEdit()
    qtbot.addWidget(line_edit)
    field_action = line_edit.addAction(QIcon(), QLineEdit.ActionPosition.TrailingPosition)
    field_action.setVisible(True)

    line_edit.show()

    actions = line_edit.actions()
    assert len(actions) == 2
    clear_action = actions[1]
    assert clear_action is not field_action
    assert clear_action.isVisible() is False

    line_edit.setText("hi")
    assert clear_action.isVisible() is True
    assert field_action.isVisible() is True


def test_a_show_after_the_action_is_deleted_equips_a_working_one(
    installed_filter: LineEditClearActionFilter, qtbot: QtBot
) -> None:
    """#365: the clear action can be deleted while its line edit lives on; the next ``Show`` equips a fresh
    one, with no repaint raising in between.

    The action is detached before it is deleted, as a real deleter would: deleting it while attached leaves the
    line edit's *own* internal trailing-icon widget holding a dangling pointer, a native crash of its own
    (confirmed on a stock ``QLineEdit`` with no filter of this module's involved).

    **Test steps:**

    * show a line edit, then remove and delete its clear action
    * hide and show it again
    * verify it carries exactly one live action, and it still tracks the text
    """
    del installed_filter
    line_edit = QLineEdit()
    qtbot.addWidget(line_edit)
    line_edit.show()
    action = line_edit.actions()[0]
    line_edit.removeAction(action)
    action.deleteLater()
    qtbot.waitUntil(lambda: not isValid(action), timeout=WAIT)
    line_edit.update()
    QApplication.processEvents()

    line_edit.hide()
    line_edit.show()

    actions = line_edit.actions()
    assert len(actions) == 1
    assert isValid(actions[0])
    line_edit.setText("hello")
    assert actions[0].isVisible() is True


def test_an_invalidated_action_wrapper_is_not_equipped_twice(
    installed_filter: LineEditClearActionFilter, qtbot: QtBot
) -> None:
    """#459: a wrapper of the clear action can be invalidated while the C++ action lives on. The line edit must
    keep that one action -- not equip a second beside it, two clear buttons -- and it must keep tracking the
    text.

    **Test steps:**

    * show a line edit and invalidate the wrapper of its clear action
    * hide and show it again, and set some text
    * verify it still carries exactly one clear action, visible, and clearing it empties the line edit
    """
    del installed_filter
    line_edit = QLineEdit()
    qtbot.addWidget(line_edit)
    line_edit.show()
    invalidate(line_edit.actions()[0])

    line_edit.hide()
    line_edit.show()
    line_edit.setText("hello")

    actions = line_edit.actions()
    assert len(actions) == 1
    assert actions[0].isVisible() is True
    actions[0].trigger()
    assert line_edit.text() == ""


def test_text_changes_are_followed_once_however_often_the_line_edit_is_equipped(
    installed_filter: LineEditClearActionFilter, qtbot: QtBot, mocker: MockerFixture
) -> None:
    """Showing an equipped line edit again must not stack another ``textChanged`` listener.

    **Test steps:**

    * show, hide and show a line edit three times
    * count the resync helpers on it
    * verify there is one
    """
    del installed_filter, mocker
    line_edit = QLineEdit()
    qtbot.addWidget(line_edit)
    for _ in range(3):
        line_edit.show()
        line_edit.hide()

    assert [type(child).__name__ for child in line_edit.children()].count("__Resync") == 1


def test_a_removed_filter_equips_nothing_more(qtbot: QtBot) -> None:
    """Once the filter is taken off the app, a line edit shown after it gets no clear action.

    **Test steps:**

    * install the filter on the app and remove it again
    * show a fresh line edit
    * verify it carries no action
    """
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    line_edit_filter = LineEditClearActionFilter()
    app.installEventFilter(line_edit_filter)
    app.removeEventFilter(line_edit_filter)
    line_edit = QLineEdit()
    qtbot.addWidget(line_edit)

    line_edit.show()

    assert line_edit.actions() == []
