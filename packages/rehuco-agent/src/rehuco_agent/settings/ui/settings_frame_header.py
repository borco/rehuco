"""One settings frame's header row: its bold title plus the per-frame Apply, Reset and Defaults buttons (#342)."""

from typing import Final

from borco_pyside.theming import ActionIconThemeHandler
from borco_pyside.widgets import ActionButtonColumn
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton, QWidget

APPLY_ICON_RESOURCE: Final = ":/icons/settings_apply.svg"
"""The per-frame Apply button's glyph: commit this group's edits, and only this group's."""

RESET_ICON_RESOURCE: Final = ":/icons/settings_reset_to_saved.svg"
"""The per-frame Reset button's glyph: back to the values last saved."""

DEFAULTS_ICON_RESOURCE: Final = ":/icons/settings_reset_to_defaults.svg"
"""The per-frame Defaults button's glyph: back to the factory values."""

HEADER_LABEL_SUFFIX: Final = "_label"
"""What a frame's header label is named after the frame itself: ``<frame>_label`` -- the convention
every settings page's ``.ui`` follows, and how :func:`header_label_of` finds the label to wrap."""


def header_label_of(frame: QFrame) -> QLabel | None:
    """The bold title label a settings frame declares first, if it follows the naming convention.

    :param frame: a settings page's top-level frame.
    :returns: its ``<frame>_label`` child, or ``None`` for a frame that declares no such label (the
        Scrapers table frame, whose first row is a caption beside a Reload button).
    """
    name = frame.objectName()
    if not name:
        return None
    return frame.findChild(QLabel, f"{name}{HEADER_LABEL_SUFFIX}", Qt.FindChildOption.FindDirectChildrenOnly)


class SettingsFrameHeader(QWidget):
    """A settings frame's title row, rebuilt around the label the ``.ui`` declares (#342).

    **Injected by the dialog, not declared by the page.** Every page's ``.ui`` keeps its plain bold
    ``<frame>_label`` as the frame's first layout item; at registration the dialog builds this row
    around that label -- the same label, reparented, a stretch, and up to three right-aligned
    icon-only tool buttons -- and the row takes the label's place in the frame's layout via
    ``QLayout.replaceWidget``, which lands it exactly where the label sat whatever the layout type (a
    ``QVBoxLayout`` item or a ``QFormLayout``'s spanning first row alike). Every page gains the
    buttons with no ``.ui`` change, and a page's author still sees only a label.

    **The swap happens before the label is taken**, in that order and here rather than at the call
    site: a layout drops a widget's item the moment the widget is reparented away from the layout's
    owner, so a ``replaceWidget`` attempted *after* the label has joined this row finds nothing to
    replace and quietly leaves the row a floating, unlaid-out child of the frame.

    Which buttons a frame gets is the dialog's call: **Apply** only for a frame whose values are
    settings (a try-it frame stages nothing to save); **Reset** and **Defaults** always. A list editor
    inside the frame used to carry a restore button of its own that put its shipped list back -- the
    same thing Defaults now says from the title row -- so the dialog hides the editor's copy rather
    than leave two buttons inviting the question of how they differ.

    The buttons are **not settings**: none is checkable, so the frame's dirty snapshot -- which reads a
    ``QAbstractButton`` only when it holds a checked state -- never counts them, and each carries
    `ActionButtonColumn.NOT_A_CAPTION_PROPERTY`, so the filter's searchable text never includes them,
    the same property the list editors' shared action buttons (#302) wear for the same reason.

    Enablement is the dialog's to drive through :meth:`set_state` on its dirty poll: Apply and Reset
    while the frame differs from its saved values, Defaults while it differs from its factory values.
    All start **disabled**: the poll refreshes only the pages on screen, so a page not yet shown would
    otherwise come up with every button live until its first tick -- the state a clean frame at its
    defaults has is the honest one to start from, the same way a frame starts untinted.

    :param label: the frame's existing ``<frame>_label``. This row is parented to the label's own
        parent, takes the label's place in that parent's layout (when it sits in one), and then
        reparents the label into itself.
    """

    def __init__(self, label: QLabel) -> None:
        frame = label.parentWidget()
        super().__init__(frame)
        self.__apply_action: Final = QAction("Apply", self)
        self.__apply_action.setToolTip("Apply this group's changes")
        ActionIconThemeHandler(self.__apply_action, APPLY_ICON_RESOURCE)
        self.__reset_action: Final = QAction("Reset", self)
        self.__reset_action.setToolTip("Reset this group to its saved values")
        ActionIconThemeHandler(self.__reset_action, RESET_ICON_RESOURCE)
        self.__defaults_action: Final = QAction("Defaults", self)
        self.__defaults_action.setToolTip("Restore this group's factory defaults")
        ActionIconThemeHandler(self.__defaults_action, DEFAULTS_ICON_RESOURCE)

        if frame is not None and (frame_layout := frame.layout()) is not None:
            frame_layout.replaceWidget(label, self)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label)
        layout.addStretch()
        layout.addWidget(self.__tool_button(self.__apply_action))
        layout.addWidget(self.__tool_button(self.__reset_action))
        layout.addWidget(self.__tool_button(self.__defaults_action))
        self.set_state(dirty=False, at_defaults=True)

    @property
    def apply_action(self) -> QAction:
        """The Apply button's action -- ``triggered`` is what the dialog wires to committing this frame."""
        return self.__apply_action

    @property
    def reset_action(self) -> QAction:
        """The Reset button's action -- ``triggered`` is what the dialog wires to restoring the saved values."""
        return self.__reset_action

    @property
    def defaults_action(self) -> QAction:
        """The Defaults button's action -- ``triggered`` is what the dialog wires to restoring the factory values."""
        return self.__defaults_action

    def set_state(self, *, dirty: bool, at_defaults: bool) -> None:
        """Enable each button only while it has something to do.

        :param dirty: whether the frame differs from its saved values (enables Apply and Reset).
        :param at_defaults: whether the frame already holds its factory values (disables Defaults).
        """
        self.__apply_action.setEnabled(dirty)
        self.__reset_action.setEnabled(dirty)
        self.__defaults_action.setEnabled(not at_defaults)

    def __tool_button(self, action: QAction) -> QToolButton:
        """A flat, icon-only button driven by ``action``, flagged as not a caption.

        :param action: the action the button shows and triggers.
        :returns: the button, parented here.
        """
        button = QToolButton(self)
        button.setDefaultAction(action)
        button.setAutoRaise(True)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setProperty(ActionButtonColumn.NOT_A_CAPTION_PROPERTY, True)
        return button
