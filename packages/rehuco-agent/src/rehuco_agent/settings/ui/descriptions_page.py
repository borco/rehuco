"""Descriptions settings page: renderer engine choice, its per-engine CSS (#26, #47), and the editor's
line-numbers/line-endings/wrap-long-lines switches (#69)."""

from typing import Final

from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import QFrame, QWidget

from ..description_editor_settings import DescriptionEditorSettings, shared_description_editor_settings
from ..markdown_rendering_settings import MarkdownRenderingSettings, shared_markdown_rendering_settings
from ..persistent_settings import persistent_settings
from .descriptions_page_ui import Ui_DescriptionsPage


class DescriptionsPage(QWidget):
    """Configure every document's description field (#26's constants, made configurable): how it
    *renders* -- the Markdown engine and its per-engine CSS -- and how its *editor* looks -- line
    numbers, line endings, wrap long lines (#69).

    The width cap on an embedded image is `ImagesDisplayPage`'s, not this page's -- it shares
    `MarkdownRenderingSettings` with the two fields here but answers a different question, and a
    reader looking for it went to Images first. This page keeps what is description-specific.

    Edits are staged locally (including a separate CSS draft per engine, swapped into the one
    ``css_edit`` box as the engine radio changes) until :meth:`save_changes` pushes them into the
    shared `MarkdownRenderingSettings` and `DescriptionEditorSettings` instances -- firing their
    ``_changed`` signals, which every open document's ``MarkdownView`` and ``MarkdownEdit`` are
    already connected to, so already-open viewers re-render and already-open editors restyle
    immediately.

    **This page takes over its frames' Apply / Reset / Defaults buttons** (`FrameRestoringPage`,
    #342), because the draft of the engine *not* shown lives off-widget, where the dialog's generic
    path cannot see it. That path commits one frame by writing the other frames' saved values back
    into their widgets around a whole-page save -- and writing ``css_edit`` fires ``textChanged``,
    which would copy the *saved* text over the edited draft: applying the editor frame would silently
    lose an unsaved CSS edit. Here the two frames map one-to-one onto the two settings objects, so
    each can be saved, reverted or re-seeded exactly, drafts included, with no parking at all.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_DescriptionsPage()
        self.__ui.setupUi(self)

        # Stretch the engine block so its CSS editor fills the page; the bottom spacer only expands
        # when the engine block is filtered out. Set here, not in the .ui: this pyside6-uic
        # mistranslates a box-layout stretch property. This is what "fills" means to `SettingsDialog`,
        # which reads the stretch back at registration so it can restore it after a group column has
        # borrowed the block ([[appendices.settings-pages#category-groups]]) -- a block taken out of a
        # box layout leaves its stretch factor behind.
        self.__ui.main_layout.setStretch(0, 1)

        self.__markdown_css_draft = ""
        self.__mistletoe_css_draft = ""

        self.__ui.markdown_engine_radio_button.toggled.connect(self.__on_engine_toggled)
        self.__ui.css_edit.textChanged.connect(self.__on_css_edited)

        self.drop_changes()

    def is_dirty(self) -> bool:
        """Whether any staged edit differs from the shared settings' current values."""
        settings = shared_markdown_rendering_settings()
        editor_settings = shared_description_editor_settings()
        return (
            self.__current_engine() != settings.engine
            or self.__markdown_css_draft != settings.markdown_css
            or self.__mistletoe_css_draft != settings.mistletoe_css
            or self.__ui.line_numbers_check_box.isChecked() != editor_settings.show_line_numbers
            or self.__ui.line_endings_check_box.isChecked() != editor_settings.show_line_endings
            or self.__ui.wrap_long_lines_check_box.isChecked() != editor_settings.wrap_long_lines
        )

    def save_changes(self) -> None:
        """Push the staged edits into the shared settings objects (live-updating open viewers and
        editors) and persist them."""
        self.__save_rendering()
        self.__save_editor()

    def drop_changes(self) -> None:
        """Discard staged edits, reverting every field back to the shared settings' current values."""
        self.__show_rendering(shared_markdown_rendering_settings())
        self.__show_editor(shared_description_editor_settings())

    def seed_defaults(self) -> None:
        """Stage the factory values: what unloaded `MarkdownRenderingSettings` and
        `DescriptionEditorSettings` hold (#342) -- both engines' CSS drafts included, not just the
        one on screen."""
        self.__show_rendering(MarkdownRenderingSettings())
        self.__show_editor(DescriptionEditorSettings())

    # region FrameRestoringPage

    def apply_frame(self, frame: QFrame) -> None:
        """Persist the one settings object ``frame`` edits, drafts included, leaving the other frame's
        edits staged (#342).

        :param frame: the engine frame or the editor frame.
        """
        if frame is self.__ui.engine_frame:
            self.__save_rendering()
        else:
            self.__save_editor()

    def reset_frame(self, frame: QFrame) -> None:
        """Put ``frame``'s controls -- and, for the engine frame, both CSS drafts -- back to the
        shared settings' current values (#342).

        :param frame: the engine frame or the editor frame.
        """
        if frame is self.__ui.engine_frame:
            self.__show_rendering(shared_markdown_rendering_settings())
        else:
            self.__show_editor(shared_description_editor_settings())

    def restore_frame_defaults(self, frame: QFrame) -> None:
        """Put ``frame``'s controls -- and, for the engine frame, both CSS drafts -- back to their
        factory values (#342).

        :param frame: the engine frame or the editor frame.
        """
        if frame is self.__ui.engine_frame:
            self.__show_rendering(MarkdownRenderingSettings())
        else:
            self.__show_editor(DescriptionEditorSettings())

    # endregion

    def __save_rendering(self) -> None:
        """Push the engine frame's staged choices -- engine and both CSS drafts -- into the shared
        rendering settings and persist them."""
        self.__sync_current_css_draft()
        settings = shared_markdown_rendering_settings()
        settings.engine = self.__current_engine()
        settings.markdown_css = self.__markdown_css_draft
        settings.mistletoe_css = self.__mistletoe_css_draft
        settings.save(persistent_settings())

    def __save_editor(self) -> None:
        """Push the editor frame's three toggles into the shared editor settings and persist them."""
        editor_settings = shared_description_editor_settings()
        editor_settings.show_line_numbers = self.__ui.line_numbers_check_box.isChecked()
        editor_settings.show_line_endings = self.__ui.line_endings_check_box.isChecked()
        editor_settings.wrap_long_lines = self.__ui.wrap_long_lines_check_box.isChecked()
        editor_settings.save(persistent_settings())

    def __show_rendering(self, settings: MarkdownRenderingSettings) -> None:
        """Fill the engine frame -- the radio, and both off-widget CSS drafts -- from ``settings``.

        :param settings: the rendering choices to show.
        """
        self.__markdown_css_draft = settings.markdown_css
        self.__mistletoe_css_draft = settings.mistletoe_css
        if settings.engine == "mistletoe":
            self.__ui.mistletoe_engine_radio_button.setChecked(True)
        else:
            self.__ui.markdown_engine_radio_button.setChecked(True)
        self.__show_current_css_draft()

    def __show_editor(self, editor_settings: DescriptionEditorSettings) -> None:
        """Fill the editor frame's three toggles from ``editor_settings``.

        :param editor_settings: the editor toggles to show.
        """
        self.__ui.line_numbers_check_box.setChecked(editor_settings.show_line_numbers)
        self.__ui.line_endings_check_box.setChecked(editor_settings.show_line_endings)
        self.__ui.wrap_long_lines_check_box.setChecked(editor_settings.wrap_long_lines)

    def __current_engine(self) -> str:
        """The engine currently selected in the radio buttons."""
        return "mistletoe" if self.__ui.mistletoe_engine_radio_button.isChecked() else "markdown"

    def __sync_current_css_draft(self) -> None:
        """Copy the CSS editor's current text into the draft slot for the selected engine."""
        if self.__current_engine() == "mistletoe":
            self.__mistletoe_css_draft = self.__ui.css_edit.toPlainText()
        else:
            self.__markdown_css_draft = self.__ui.css_edit.toPlainText()

    def __show_current_css_draft(self) -> None:
        """Show the draft CSS for the selected engine in the editor, without re-triggering
        :meth:`__on_css_edited` (which would just copy the shown text right back into the same
        draft slot -- harmless, but a needless round trip)."""
        draft = self.__mistletoe_css_draft if self.__current_engine() == "mistletoe" else self.__markdown_css_draft
        with QSignalBlocker(self.__ui.css_edit):
            self.__ui.css_edit.setPlainText(draft)

    def __on_engine_toggled(self, checked: bool) -> None:
        """Show the newly-selected engine's CSS draft.

        Connected only to ``markdown_engine_radio_button.toggled`` -- with exactly two mutually
        exclusive radios, that alone fires once per switch either way.

        :param checked: whether the markdown radio is now checked; unused (only the direction of
            the switch matters, not which specific signal reported it).
        """
        del checked
        self.__show_current_css_draft()

    def __on_css_edited(self) -> None:
        """Keep the selected engine's draft in sync as the user types."""
        self.__sync_current_css_draft()
