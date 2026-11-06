"""The notes panel: the loaded video's notes above the tutorial's, rendered, with an Edit toggle
([[plugins#video-notes-dock]], #573, #575)."""

import logging
from typing import Any, Final, override

import cbor2
from PySide6.QtCore import QByteArray, QEvent, QObject, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import QStackedWidget, QWidget
from rehuco_core import VIDEO_LINK_SCHEME, parse_video_href

from ..fields.widgets.markdown_edit import MarkdownEdit
from ..fields.widgets.markdown_view import MarkdownView
from ..settings.description_editor_settings import shared_description_editor_settings
from ..settings.image_viewer_settings import shared_image_viewer_settings
from ..settings.markdown_rendering_settings import shared_markdown_rendering_settings
from .notes_panel_ui import Ui_NotesPanel
from .rehu_document_model import RehuDocumentModel
from .video_notes_edit import VideoNotesEdit

LOG: Final = logging.getLogger(__name__)

SPLIT_STATE_KEY: Final = "split"
VIDEO_STATE_KEY: Final = "video"
EDITING_STATE_KEY: Final = "editing"
"""The keys of a panel's saved state: where its two parts split, the video it shows the notes of, and its editing."""


class NotesPanel(QWidget):
    """One view of a document's notes: the video loaded in the player above the tutorial as a whole.

    Both are rendered Markdown, the Description View's renderer, until the **Edit** action swaps in the Markdown editor
    for each. **The notes themselves are a** :class:`~rehuco_agent.documents.video_notes_edit.VideoNotesEdit`, shared by
    every panel of a document: the same video, and the same text in the editors, whichever panel it is typed in (#575).
    This panel has its own Edit toggle, scroll and caret. What is written, and when, is the model's.

    A ``rehuco-video:`` link in a note is a request to the player (:attr:`video_link_activated`); any other link opens
    in the system's browser.

    :param model: the document, whose notes this shows.
    :param parent: optional Qt parent.
    :param notes: the notes model to show; one of its own, which :meth:`detach` then lets go of, when not given.
    """

    video_link_activated = Signal(str, object)
    """Emitted ``(content key, seconds or None)`` for a click on a link to a video of the tutorial: the video to take
    to the player and the time to go to, ``None`` for none. The document decides what the player does."""

    def __init__(
        self, model: RehuDocumentModel, parent: QWidget | None = None, notes: VideoNotesEdit | None = None
    ) -> None:
        super().__init__(parent)
        self.__model: Final = model
        self.__owns_notes: Final = notes is None
        self.__notes: Final = notes if notes is not None else VideoNotesEdit(model, self)
        self.__editing = False

        self.__ui: Final = Ui_NotesPanel()
        self.__ui.setupUi(self)
        self.__video_edit: Final = self.__setup_part(self.__ui.video_stack, self.__ui.video_view)
        self.__tutorial_edit: Final = self.__setup_part(self.__ui.tutorial_stack, self.__ui.tutorial_view)
        self.__notes.share(self.__video_edit, self.__tutorial_edit)
        self.__ui.edit_action.toggled.connect(self.__on_edit_toggled)
        self.__setup_rendering()
        self.__notes.changed.connect(self.__show)
        model.image_scanner_changed.connect(self.__set_image_scanner)  # type: ignore[attr-defined]
        self.__set_image_scanner(model.image_scanner)
        self.__show()

    def detach(self) -> None:
        """Write what is waiting and stop following the document, before this panel is destroyed."""
        self.flush()
        self.__notes.changed.disconnect(self.__show)
        self.__model.image_scanner_changed.disconnect(self.__set_image_scanner)  # type: ignore[attr-defined]
        previews = shared_image_viewer_settings()
        for view in (self.__ui.video_view, self.__ui.tutorial_view):
            previews.previews_visible_changed.disconnect(view.set_images_visible)  # type: ignore[attr-defined]
        shared_markdown_rendering_settings().description_rendering_changed.disconnect(self.__apply_rendering)
        if self.__owns_notes:
            self.__notes.detach()

    @property
    def title_bar_actions(self) -> list[QAction]:
        """*Edit*, for the dock's title bar."""
        return [self.__ui.edit_action]

    @property
    def notes(self) -> VideoNotesEdit:
        """The notes this shows, which other panels of the document show too."""
        return self.__notes

    @property
    def editing(self) -> bool:
        """Whether this panel shows the editors, not the rendered notes."""
        return self.__editing

    def set_editing(self, editing: bool) -> None:
        """Show the editors, or the rendered notes, as the Edit action does.

        :param editing: whether the editors are to be shown.
        """
        self.__ui.edit_action.setChecked(editing)

    def focus_editor(self) -> None:
        """Put the keyboard in the editor of the video's notes (owner: always there, never the tutorial's)."""
        QWidget.setFocus(self.__video_edit, Qt.FocusReason.OtherFocusReason)

    @property
    def video_key(self) -> str | None:
        """The content key of the video whose notes are shown above the tutorial's, or ``None`` for none."""
        return self.__notes.key

    @property
    def searching(self) -> bool:
        """Whether the video shown is still being looked for among the renamed ones, its editor disabled meanwhile."""
        return self.__notes.searching

    def set_video(self, key: str | None) -> None:
        """Show the notes of another video, in every panel of the document.

        :param key: the video's content key, or ``None`` for none -- the tutorial's notes alone are shown.
        """
        self.__notes.set_video(key)

    def follow_player(self, key: str | None) -> None:
        """Show the notes of the video the player selected. See :meth:`VideoNotesEdit.follow_player`.

        :param key: the video's content key, or ``None`` for none.
        """
        self.__notes.follow_player(key)

    def add_note(self, key: str, seconds: float) -> None:
        """Add a bookmark to a video's notes at a time, among its other bookmarks in time order.

        :param key: the video's content key.
        :param seconds: the time the bookmark is at.
        """
        self.__notes.add_note(key, seconds)

    def flush(self) -> None:
        """Record the notes the user changed in the editors, at once; nothing else is written."""
        self.__notes.flush()

    def save_state(self) -> bytes:
        """Encode where the two parts split, the note shown and whether it is being edited, for the dock's entry in the
        layout.

        :returns: the state, restorable by :meth:`restore_state`.
        """
        return cbor2.dumps(
            {
                SPLIT_STATE_KEY: bytes(self.__ui.splitter.saveState().data()),
                VIDEO_STATE_KEY: self.__notes.key,
                EDITING_STATE_KEY: self.__editing,
            }
        )

    def restore_state(self, state: bytes) -> None:
        """Restore what :meth:`save_state` encoded. The keyboard stays where it is: a restored editor is not one the
        reader just asked for.

        :param state: the blob; one that cannot be read leaves everything as it is, and each value costs only itself.
        """
        try:
            values: Any = cbor2.loads(state)
        except cbor2.CBORDecodeError:
            return
        if not isinstance(values, dict):
            return
        split = values.get(SPLIT_STATE_KEY)
        if isinstance(split, bytes):
            self.__ui.splitter.restoreState(QByteArray(split))
        video = values.get(VIDEO_STATE_KEY)
        if isinstance(video, str) and video:
            self.__notes.restore_video(video)
        editing = values.get(EDITING_STATE_KEY)
        if isinstance(editing, bool):
            self.set_editing(editing)

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
        """Show the notes of the video and the tutorial as they are, in the viewers; the editors hold their own."""
        key = self.__notes.key
        self.__ui.video_part.setVisible(key is not None)
        self.__ui.video_label.set_text(key or "")
        self.__ui.video_view.set_markdown(self.__notes.video_text())
        self.__ui.tutorial_view.set_markdown(self.__notes.tutorial_text())
        self.__video_edit.setEnabled(not self.__notes.searching)

    def __on_edit_toggled(self, editing: bool) -> None:
        """Swap the viewers for the editors, or back, writing what was changed on the way back.

        :param editing: whether the editors are to be shown.
        """
        if not editing:
            self.flush()
        self.__editing = editing
        if editing:
            self.__notes.begin_editing()
        else:
            self.__notes.end_editing()
        self.__show()
        page = 1 if editing else 0
        self.__ui.video_stack.setCurrentIndex(page)
        self.__ui.tutorial_stack.setCurrentIndex(page)

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
