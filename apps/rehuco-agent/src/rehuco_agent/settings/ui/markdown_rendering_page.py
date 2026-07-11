"""Markdown-rendering settings page: engine choice, per-engine CSS, and image-width cap (#26, #47)."""

from typing import Final

from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import QWidget

from rehuco_agent.settings.markdown_rendering_settings import shared_markdown_rendering_settings
from rehuco_agent.settings.persistent_settings import persistent_settings
from rehuco_agent.settings.ui.markdown_rendering_page_ui import Ui_MarkdownRenderingPage


class MarkdownRenderingPage(QWidget):
    """Configure the Markdown renderer (#26's constants, made configurable): engine, per-engine
    CSS, and the image-width cap.

    Edits are staged locally (including a separate CSS draft per engine, swapped into the one
    ``css_edit`` box as the engine radio changes) until :meth:`save_changes` pushes them into the
    shared `MarkdownRenderingSettings` instance -- firing its ``_changed`` signals, which every
    open document's ``MarkdownView`` is already connected to, so already-open viewers re-render
    immediately.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_MarkdownRenderingPage()
        self.__ui.setupUi(self)

        self.__markdown_css_draft = ""
        self.__mistletoe_css_draft = ""

        self.__ui.markdown_engine_radio_button.toggled.connect(self.__on_engine_toggled)
        self.__ui.css_edit.textChanged.connect(self.__on_css_edited)

        self.drop_changes()

    @property
    def title(self) -> str:
        """This page's category-tree label."""
        return "Markdown Rendering"

    def field_labels(self) -> list[str]:
        """The setting labels this page exposes, for the settings dialog's filter box."""
        return ["Engine", "markdown", "mistletoe", "CSS", "Maximum image width"]

    def is_dirty(self) -> bool:
        """Whether any staged edit differs from the shared settings' current values."""
        settings = shared_markdown_rendering_settings()
        return (
            self.__current_engine() != settings.engine
            or self.__markdown_css_draft != settings.markdown_css
            or self.__mistletoe_css_draft != settings.mistletoe_css
            or self.__ui.max_image_width_spin_box.value() != settings.max_image_width
        )

    def save_changes(self) -> None:
        """Push the staged edits into the shared settings object (live-updating open viewers) and
        persist them."""
        self.__sync_current_css_draft()
        settings = shared_markdown_rendering_settings()
        settings.engine = self.__current_engine()
        settings.markdown_css = self.__markdown_css_draft
        settings.mistletoe_css = self.__mistletoe_css_draft
        settings.max_image_width = self.__ui.max_image_width_spin_box.value()
        settings.save(persistent_settings())

    def drop_changes(self) -> None:
        """Discard staged edits, reverting every field back to the shared settings' current values."""
        settings = shared_markdown_rendering_settings()
        self.__markdown_css_draft = settings.markdown_css
        self.__mistletoe_css_draft = settings.mistletoe_css
        if settings.engine == "mistletoe":
            self.__ui.mistletoe_engine_radio_button.setChecked(True)
        else:
            self.__ui.markdown_engine_radio_button.setChecked(True)
        self.__ui.max_image_width_spin_box.setValue(settings.max_image_width)
        self.__show_current_css_draft()

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
