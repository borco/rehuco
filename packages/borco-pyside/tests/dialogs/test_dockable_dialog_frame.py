"""Tests for DockableDialogFrame: content plus a "Restore on start" checkbox."""

from borco_pyside.dialogs import DockableDialogFrame
from PySide6.QtWidgets import QLabel
from pytestqt.qtbot import QtBot


def test_content_is_exposed_unchanged(qtbot: QtBot) -> None:
    """The constructor's content widget comes back unchanged from the ``content`` property.

    **Test steps:**

    * build a frame around a label
    * verify ``content`` returns that same label
    """
    content = QLabel("hello")
    frame = DockableDialogFrame(content)
    qtbot.addWidget(frame)

    assert frame.content is content


def test_restore_on_start_defaults_to_unchecked(qtbot: QtBot) -> None:
    """A freshly-built frame's "Restore on start" checkbox starts unchecked.

    **Test steps:**

    * build a frame
    * verify ``restore_on_start`` is ``False``
    """
    frame = DockableDialogFrame(QLabel())
    qtbot.addWidget(frame)

    assert frame.restore_on_start is False


def test_restore_on_start_setter_updates_the_checkbox(qtbot: QtBot) -> None:
    """Setting ``restore_on_start`` checks/unchecks the underlying checkbox.

    **Test steps:**

    * build a frame and set ``restore_on_start`` to ``True``
    * verify the property reads back ``True``
    * set it back to ``False``
    * verify the property reads back ``False``
    """
    frame = DockableDialogFrame(QLabel())
    qtbot.addWidget(frame)

    frame.restore_on_start = True
    assert frame.restore_on_start is True

    frame.restore_on_start = False
    assert frame.restore_on_start is False
