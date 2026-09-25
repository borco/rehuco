"""Tests for SettingsFrameHeader: a frame's title row with its Reset/Defaults buttons (#342)."""

from borco_pyside.widgets import ActionButtonColumn
from PySide6.QtWidgets import QFormLayout, QFrame, QLabel, QLineEdit, QToolButton, QVBoxLayout
from pytestqt.qtbot import QtBot
from rehuco_agent.settings.ui.settings_frame_filter import SettingsFrameFilter
from rehuco_agent.settings.ui.settings_frame_header import SettingsFrameHeader, header_label_of


def test_header_label_of_finds_the_frames_conventionally_named_label(qtbot: QtBot) -> None:
    """A frame's ``<frame>_label`` direct child is its header label.

    **Test steps:**

    * build a frame named ``probe_frame`` holding a ``probe_frame_label``
    * verify it is found
    """
    frame = QFrame()
    qtbot.addWidget(frame)
    frame.setObjectName("probe_frame")
    label = QLabel("Duration probe", frame)
    label.setObjectName("probe_frame_label")

    assert header_label_of(frame) is label


def test_header_label_of_answers_none_for_an_unnamed_frame_or_a_missing_label(qtbot: QtBot) -> None:
    """No name to derive a label name from, or no such label, means no header label.

    **Test steps:**

    * build an unnamed frame with a label, and a named frame with a differently named label
    * verify neither yields a header label
    """
    unnamed = QFrame()
    qtbot.addWidget(unnamed)
    QLabel("x", unnamed).setObjectName("_label")
    named = QFrame()
    qtbot.addWidget(named)
    named.setObjectName("scrapers_frame")
    QLabel("Scanned", named).setObjectName("scanned_label")

    assert header_label_of(unnamed) is None
    assert header_label_of(named) is None


def make_box_frame(qtbot: QtBot) -> tuple[QFrame, QLabel, QLineEdit]:
    """A frame laid out the way a page's ``.ui`` lays one out: a bold ``<frame>_label`` first, then
    one control, in a ``QVBoxLayout``.

    :param qtbot: the Qt test bot, to own the frame.
    :returns: the frame, its header label and its line edit.
    """
    frame = QFrame()
    qtbot.addWidget(frame)
    frame.setObjectName("probe_frame")
    layout = QVBoxLayout(frame)
    label = QLabel("Duration probe", frame)
    label.setObjectName("probe_frame_label")
    layout.addWidget(label)
    edit = QLineEdit(frame)
    layout.addWidget(edit)
    return frame, label, edit


def test_the_row_takes_the_labels_place_in_the_frames_layout(qtbot: QtBot) -> None:
    """Building a header around a frame's label swaps the row in where the label sat -- first in
    the frame's layout -- with the label now inside the row, then a stretch, then Reset and Defaults.

    **Test steps:**

    * build a box-layout frame and a header around its label
    * verify the row is the frame's first layout item, the label is its child and first, and the
      three tool buttons carry Apply, Reset, Defaults in that order
    """
    frame, label, edit = make_box_frame(qtbot)

    header = SettingsFrameHeader(label)

    frame_layout = frame.layout()
    assert frame_layout is not None
    assert frame_layout.indexOf(header) == 0
    assert frame_layout.indexOf(edit) == 1
    assert frame_layout.indexOf(label) == -1
    assert label.parentWidget() is header
    header_layout = header.layout()
    assert header_layout is not None
    assert header_layout.indexOf(label) == 0
    buttons = header.findChildren(QToolButton)
    assert [button.defaultAction() for button in buttons] == [
        header.apply_action,
        header.reset_action,
        header.defaults_action,
    ]


def test_a_label_outside_any_layout_is_simply_adopted(qtbot: QtBot) -> None:
    """A label with no layout to be replaced in still becomes the row's first child.

    **Test steps:**

    * build a header around a parentless label
    * verify the label is its child
    """
    label = QLabel("Duration probe")
    header = SettingsFrameHeader(label)
    qtbot.addWidget(header)

    assert label.parentWidget() is header


def test_the_buttons_are_flagged_as_neither_settings_nor_captions(qtbot: QtBot) -> None:
    """The tool buttons are not checkable, so a frame filter never snapshots them (it reads a
    ``QAbstractButton`` only when it holds a checked state), and they wear the not-a-caption property,
    so it never searches their text.

    **Test steps:**

    * build a page whose frame gets a header beside a line edit
    * verify the buttons are not checkable and not captions, the filter snapshots only the edit, and
      the frame's search text carries the label alone
    """
    page = QFrame()
    qtbot.addWidget(page)
    frame, label, edit = make_box_frame(qtbot)
    frame.setParent(page)
    QVBoxLayout(page).addWidget(frame)
    header = SettingsFrameHeader(label)
    for button in header.findChildren(QToolButton):
        assert button.isCheckable() is False
        assert button.property(ActionButtonColumn.NOT_A_CAPTION_PROPERTY) is True
    frame_filter = SettingsFrameFilter(page, "Videos")

    assert frame_filter.field_labels() == ["duration probe"]
    header.reset_action.setChecked(True)  # a checkable flip on the action, were the button counted
    assert frame_filter.dirty_frames() == []
    edit.setText("changed")
    assert frame_filter.dirty_frames() == [frame]


def test_set_state_enables_apply_and_reset_while_dirty_and_defaults_while_off_defaults(qtbot: QtBot) -> None:
    """Apply and Reset follow ``dirty``; Defaults is the inverse of ``at_defaults``.

    **Test steps:**

    * drive ``set_state`` through the four combinations
    * verify each action's enablement
    """
    header = SettingsFrameHeader(QLabel("x"))
    qtbot.addWidget(header)

    def enabled() -> tuple[bool, bool, bool]:
        return (
            header.apply_action.isEnabled(),
            header.reset_action.isEnabled(),
            header.defaults_action.isEnabled(),
        )

    # starts as a clean frame at its defaults would: all off, until the poll says otherwise
    assert enabled() == (False, False, False)

    header.set_state(dirty=True, at_defaults=False)
    assert enabled() == (True, True, True)

    header.set_state(dirty=False, at_defaults=False)
    assert enabled() == (False, False, True)

    header.set_state(dirty=True, at_defaults=True)
    assert enabled() == (True, True, False)

    header.set_state(dirty=False, at_defaults=True)
    assert enabled() == (False, False, False)


def test_the_row_takes_a_form_layouts_spanning_label_row(qtbot: QtBot) -> None:
    """The swap works for a ``QFormLayout`` frame too -- the row lands in the label's spanning
    first row, above the form's fields, which is how three of the real pages lay their frames out.

    **Test steps:**

    * build a form-layout frame whose spanning row 0 is the label and row 1 a field
    * build a header around the label
    * verify the header occupies row 0's spanning role and the field is still row 1
    """
    frame = QFrame()
    qtbot.addWidget(frame)
    frame.setObjectName("identity_frame")
    layout = QFormLayout(frame)
    label = QLabel("Identity", frame)
    label.setObjectName("identity_frame_label")
    layout.setWidget(0, QFormLayout.ItemRole.SpanningRole, label)
    edit = QLineEdit(frame)
    layout.addRow("Name:", edit)

    header = SettingsFrameHeader(label)

    spanning = layout.itemAt(0, QFormLayout.ItemRole.SpanningRole)
    assert spanning is not None and spanning.widget() is header
    assert label.parentWidget() is header
    field = layout.itemAt(1, QFormLayout.ItemRole.FieldRole)
    assert field is not None and field.widget() is edit
