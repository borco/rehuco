"""The notes panel: the loaded video's notes above the tutorial's, rendered, with an Edit toggle
([[plugins#video-notes-dock]], #573)."""

import logging
from typing import Final, override

from PySide6.QtCore import QByteArray, QEvent, QObject, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import QStackedWidget, QWidget
from rehuco_core import VIDEO_LINK_SCHEME, insert_bookmark, parse_video_href, video_href

from ..fields.widgets.markdown_edit import MarkdownEdit
from ..fields.widgets.markdown_view import MarkdownView
from ..settings.description_editor_settings import shared_description_editor_settings
from ..settings.image_viewer_settings import shared_image_viewer_settings
from ..settings.markdown_rendering_settings import shared_markdown_rendering_settings
from .clock_text import clock_text
from .notes_panel_ui import Ui_NotesPanel
from .rehu_document_model import RehuDocumentModel

LOG: Final = logging.getLogger(__name__)


class NotesPanel(QWidget):  # pylint: disable=too-many-instance-attributes
    """One document's notes: the video loaded in the player above the tutorial as a whole.

    Both are rendered Markdown, the Description View's renderer, until the **Edit** action swaps in the Markdown editor
    for each. **What is written is the user's own, written the moment editing ends** -- leaving edit, the editor losing
    focus, the video changing, :meth:`flush` -- through the document's ``record_notes`` and never a Save
    ([[field-schema#video-notes]]). Only a part the user changed is written. **A video with no data yet is looked for
    among the renamed ones first**, and until that search answers its notes are not safe to edit: the editor is
    disabled, and a bookmark asked for meanwhile is added once the search answers, so nothing typed or added over an
    empty note replaces the one the search then finds.

    A ``rehuco-video:`` link in a note is a request to the player (:attr:`video_link_activated`); any other link opens
    in the system's browser.

    :param model: the document, whose notes this shows and records.
    :param parent: optional Qt parent.
    """

    video_link_activated = Signal(str, object)
    """Emitted ``(content key, seconds or None)`` for a click on a link to a video of the tutorial: the video to take
    to the player and the time to go to, ``None`` for none. The document decides what the player does."""

    def __init__(self, model: RehuDocumentModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__model: Final = model
        self.__key: str | None = None
        self.__editing = False
        self.__shown: dict[bool, str] = {}
        """What each editor was last given -- by whether it is the video's -- so a changed editor is the user's."""
        self.__searching = False
        """Whether the video shown is still being looked for among the renamed ones: its editor waits."""
        self.__pending_note: tuple[float, bool] | None = None
        """A bookmark asked for while the search was out -- its time, and whether to edit -- added once it answers."""

        self.__ui: Final = Ui_NotesPanel()
        self.__ui.setupUi(self)
        self.__video_edit: Final = self.__setup_part(self.__ui.video_stack, self.__ui.video_view)
        self.__tutorial_edit: Final = self.__setup_part(self.__ui.tutorial_stack, self.__ui.tutorial_view)
        self.__ui.edit_action.toggled.connect(self.__on_edit_toggled)
        self.__setup_rendering()
        model.notes_changed.connect(self.__on_notes_changed)
        model.rename_search_finished.connect(self.__on_search_finished)
        model.image_scanner_changed.connect(self.__set_image_scanner)  # type: ignore[attr-defined]
        self.__set_image_scanner(model.image_scanner)
        self.__show()

    def detach(self) -> None:
        """Write what is waiting and stop following the document, before this panel is destroyed."""
        self.flush()
        self.__model.notes_changed.disconnect(self.__on_notes_changed)
        self.__model.rename_search_finished.disconnect(self.__on_search_finished)
        self.__model.image_scanner_changed.disconnect(self.__set_image_scanner)  # type: ignore[attr-defined]
        previews = shared_image_viewer_settings()
        for view in (self.__ui.video_view, self.__ui.tutorial_view):
            previews.previews_visible_changed.disconnect(view.set_images_visible)  # type: ignore[attr-defined]
        shared_markdown_rendering_settings().description_rendering_changed.disconnect(self.__apply_rendering)

    @property
    def title_bar_actions(self) -> list[QAction]:
        """*Edit*, for the dock's title bar."""
        return [self.__ui.edit_action]

    @property
    def editing(self) -> bool:
        """Whether the editors, not the rendered notes, are shown."""
        return self.__editing

    @property
    def video_key(self) -> str | None:
        """The content key of the video whose notes are shown above the tutorial's, or ``None`` for none."""
        return self.__key

    @property
    def searching(self) -> bool:
        """Whether the video shown is still being looked for among the renamed ones, its editor disabled meanwhile."""
        return self.__searching

    def set_video(self, key: str | None) -> None:
        """Show the notes of another video, after writing what was changed in the one before.

        A video with nothing recorded yet is looked for among the renamed ones first, and its editor is disabled until
        the search answers, so what the user types is never lost to, or written over, the note the search finds.

        :param key: the video's content key, or ``None`` for none -- the tutorial's notes alone are shown.
        """
        self.flush()
        self.__key = key
        self.__pending_note = None
        # set before the search is asked for: a search that answers at once answers through __on_search_finished
        self.__searching = key is not None and key not in self.__model.video_data_keys()
        if self.__searching and not self.__model.reattach_renamed_progress():
            self.__searching = False
        self.__show()

    def add_note(self, key: str, seconds: float, *, edit: bool = True) -> None:
        """Add a bookmark to a video's notes at a time, among its other bookmarks in time order.

        By default the notes open in the editor with the caret at the end of the new line. Without ``edit`` the line is
        only recorded: into the editor's text, written at once, if the notes are being edited, else straight into the
        video's notes, with no change of mode and no focus taken.

        :param key: the video's content key.
        :param seconds: the time the bookmark is at.
        :param edit: whether to open the notes for editing at the new line.
        """
        if key != self.__key:
            self.set_video(key)
        if self.__searching:
            # the editor shows, disabled, until the search answers; the line is added then
            self.__pending_note = (seconds, edit)
            if edit:
                self.__ui.edit_action.setChecked(True)
            return
        line = f"- [{clock_text(int(seconds * 1000))}]({video_href(key, seconds)}) "
        if edit:
            self.__ui.edit_action.setChecked(True)
        if edit or self.__editing:
            editor = self.__video_edit
            text, end = insert_bookmark(self.__text(editor), line, seconds)
            editor.setText(text)
            if edit:
                # Scintilla's positions count bytes, not characters
                editor.gotoPos(len(text[:end].encode("utf-8")))
                QWidget.setFocus(editor)
            else:
                self.flush()
            return
        text, _ = insert_bookmark(self.__model.video_notes_of(key), line, seconds)
        self.__model.record_notes(video_notes={key: text})

    def flush(self) -> None:
        """Record the notes the user changed in the editors, at once; nothing else is written."""
        if not self.__editing:
            return
        notes = self.__changed(self.__tutorial_edit, False)
        key = self.__key
        video = self.__changed(self.__video_edit, True) if key is not None and not self.__searching else None
        if notes is None and video is None:
            return
        if notes is not None:
            self.__shown = {**self.__shown, False: notes}
        if video is not None:
            self.__shown = {**self.__shown, True: video}
        self.__model.record_notes(
            notes=notes, video_notes={key: video} if key is not None and video is not None else None
        )

    def save_state(self) -> bytes:
        """Encode where the two parts split, for the dock's entry in the layout.

        :returns: the splitter's state, restorable by :meth:`restore_state`.
        """
        return bytes(self.__ui.splitter.saveState().data())

    def restore_state(self, state: bytes) -> None:
        """Restore the split :meth:`save_state` encoded.

        :param state: the blob; one Qt does not recognise leaves the split as it is.
        """
        self.__ui.splitter.restoreState(QByteArray(state))

    @override
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802  (Qt API name)
        """Write what was typed as an editor loses focus.

        :param watched: the editor, or its viewport.
        :param event: what happened to it.
        :returns: whether the event is consumed -- never.
        """
        if event.type() == QEvent.Type.FocusOut:
            self.flush()
        return super().eventFilter(watched, event)

    # region Setup

    def __setup_part(self, stack: QStackedWidget, view: MarkdownView) -> MarkdownEdit:
        """Give a part its viewer's links and an editor beside it.

        :param stack: the stack of the part's two pages, the viewer first.
        :param view: the part's viewer.
        :returns: the part's editor, added to the stack.
        """
        view.setOpenLinks(False)
        view.setOpenExternalLinks(False)
        view.anchorClicked.connect(self.__on_link)
        settings = shared_description_editor_settings()
        editor = MarkdownEdit(
            line_numbers=settings.show_line_numbers,
            line_endings_visible=settings.show_line_endings,
            wrap_long_lines=settings.wrap_long_lines,
        )
        stack.addWidget(editor)
        editor.installEventFilter(self)
        editor.viewport().installEventFilter(self)
        return editor

    def __setup_rendering(self) -> None:
        """Render as the Description View does, and follow its settings."""
        rendering = shared_markdown_rendering_settings()
        previews = shared_image_viewer_settings()
        for view in (self.__ui.video_view, self.__ui.tutorial_view):
            view.apply_rendering_settings(engine=rendering.engine, css=rendering.css)
            view.set_images_visible(previews.previews_visible)
            previews.previews_visible_changed.connect(view.set_images_visible)  # type: ignore[attr-defined]
        rendering.description_rendering_changed.connect(self.__apply_rendering)

    def __apply_rendering(self) -> None:
        """Render again after the Markdown settings changed."""
        rendering = shared_markdown_rendering_settings()
        for view in (self.__ui.video_view, self.__ui.tutorial_view):
            view.apply_rendering_settings(engine=rendering.engine, css=rendering.css)

    def __set_image_scanner(self, scanner: object) -> None:
        """Give the viewers and the editors the scanner that finds the record's images.

        :param scanner: the document's, or ``None``.
        """
        for widget in (self.__ui.video_view, self.__ui.tutorial_view, self.__video_edit, self.__tutorial_edit):
            widget.set_image_scanner(scanner)  # type: ignore[arg-type]

    # endregion

    # region What it shows

    def __show(self) -> None:
        """Show the notes of the video and the tutorial as they are, in the viewers or the editors."""
        key = self.__key
        self.__ui.video_part.setVisible(key is not None)
        self.__ui.video_label.set_text(key or "")
        video = self.__model.video_notes_of(key) if key is not None else ""
        self.__ui.video_view.set_markdown(video)
        self.__ui.tutorial_view.set_markdown(self.__model.notes)
        self.__video_edit.setEnabled(not self.__searching)
        if self.__editing:
            self.__give(self.__video_edit, True, video)
            self.__give(self.__tutorial_edit, False, self.__model.notes)

    def __on_search_finished(self) -> None:
        """Let the video's notes be edited, now the search for them among the renamed videos has answered, and add
        the bookmark asked for meanwhile."""
        if not self.__searching:
            return
        self.__searching = False
        self.__show()
        pending, self.__pending_note = self.__pending_note, None
        if pending is not None and self.__key is not None:
            seconds, edit = pending
            self.add_note(self.__key, seconds, edit=edit)

    def __on_notes_changed(self) -> None:
        """Show the notes again after they changed -- a write landing, a rename search finding them: an editor the user
        changed keeps its text."""
        key = self.__key
        self.__ui.video_view.set_markdown(self.__model.video_notes_of(key) if key is not None else "")
        self.__ui.tutorial_view.set_markdown(self.__model.notes)
        if self.__editing:
            if key is not None and self.__changed(self.__video_edit, True) is None:
                self.__give(self.__video_edit, True, self.__model.video_notes_of(key))
            if self.__changed(self.__tutorial_edit, False) is None:
                self.__give(self.__tutorial_edit, False, self.__model.notes)

    def __on_edit_toggled(self, editing: bool) -> None:
        """Swap the viewers for the editors, or back, writing what was changed on the way back.

        :param editing: whether the editors are to be shown.
        """
        if not editing:
            self.flush()
        self.__editing = editing
        self.__show()
        page = 1 if editing else 0
        self.__ui.video_stack.setCurrentIndex(page)
        self.__ui.tutorial_stack.setCurrentIndex(page)

    def __give(self, editor: MarkdownEdit, of_video: bool, text: str) -> None:
        """Put a text in an editor as what it was given, unless it already holds it -- which keeps its caret.

        :param editor: the editor.
        :param of_video: whether it is the video's.
        :param text: what it is to hold.
        """
        self.__shown = {**self.__shown, of_video: text}
        if self.__text(editor) != text:
            editor.setText(text)

    def __changed(self, editor: MarkdownEdit, of_video: bool) -> str | None:
        """What the user typed in an editor.

        :param editor: the editor.
        :param of_video: whether it is the video's.
        :returns: its text if it differs from what it was given, else ``None``.
        """
        text = self.__text(editor)
        return text if text != self.__shown.get(of_video, "") else None

    @staticmethod
    def __text(editor: MarkdownEdit) -> str:
        """Read an editor's full text.

        :param editor: the editor.
        :returns: its text.
        """
        return bytes(editor.getText(editor.length() + 1).data()).decode("utf-8")

    # endregion

    def __on_link(self, url: QUrl) -> None:
        """Take a click on a link: to the player if it names a video of the tutorial, else to the system's browser.

        :param url: the link's target.
        """
        href = url.toString(QUrl.ComponentFormattingOption.FullyEncoded)
        if not href.startswith(VIDEO_LINK_SCHEME):
            QDesktopServices.openUrl(url)
            return
        parsed = parse_video_href(href)
        if parsed is None:
            LOG.warning("ignoring a link to no video: %s", href)
            return
        self.video_link_activated.emit(*parsed)
