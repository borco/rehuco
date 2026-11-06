"""The notes being read and edited: one model, shown by every notes panel ([[plugins#video-notes-dock]], #573,
#575)."""

from typing import Final

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QWidget
from rehuco_core import insert_bookmark, video_href

from ..fields.widgets.markdown_edit import MarkdownEdit
from ..settings.description_editor_settings import shared_description_editor_settings
from .clock_text import clock_text
from .rehu_document_model import RehuDocumentModel


class VideoNotesEdit(QObject):  # pylint: disable=too-many-instance-attributes
    """Which video's notes are shown, and the text of them being edited -- one for the document, however many panels
    show it (the Notes dock, the player's ``N`` panel).

    **The text is one Scintilla document per part**, which this holds in editors of its own that are never shown; each
    panel's editors share those documents (:meth:`share`), so what one types is in the others as it is typed, and each
    keeps its own caret and view. **What is written is the user's own, written the moment editing ends** -- a panel
    leaving edit, an editor losing focus, the video changing, :meth:`flush` -- through the document's ``record_notes``
    and never a Save ([[field-schema#video-notes]]). Only a part the user changed is written. **A video with no data yet
    is looked for among the renamed ones first**, and until that search answers its notes are not safe to edit: the
    editors are disabled, and a bookmark asked for meanwhile is added once the search answers, so nothing typed or added
    over an empty note replaces the one the search then finds.

    :param model: the document, whose notes this records.
    :param parent: the panel that made this, which owns it and the editors holding the documents.
    """

    changed = Signal()
    """What the panels show changed: the video, whether it is being searched for, or the notes themselves."""

    def __init__(self, model: RehuDocumentModel, parent: QWidget) -> None:
        super().__init__(parent)
        self.__model: Final = model
        self.__key: str | None = None
        self.__editing = 0
        """How many panels are editing; the documents are fed and written while it is above zero."""
        self.__shown: dict[bool, str] = {}
        """What each document was last given -- by whether it is the video's -- so a changed one is the user's."""
        self.__searching = False
        self.__pending_note: float | None = None
        """The time of a bookmark asked for while the search was out, added once it answers."""
        self.__restored_key: str | None = None
        """The video a session restored the notes of, until the player has loaded its own (:meth:`follow_player`)."""
        self.__video_edit: Final = self.__make_editor(parent)
        self.__tutorial_edit: Final = self.__make_editor(parent)
        model.notes_changed.connect(self.__on_notes_changed)
        model.rename_search_finished.connect(self.__on_search_finished)

    def detach(self) -> None:
        """Write what is waiting, stop following the document and let go of the documents, before this is destroyed.

        The panels sharing them are detached first."""
        self.flush()
        # no panel is editing any more: a flush a panel's editor asks for as it loses the focus after this writes
        # nothing and reaches no deleted document
        self.__editing = 0
        self.__model.notes_changed.disconnect(self.__on_notes_changed)
        self.__model.rename_search_finished.disconnect(self.__on_search_finished)
        self.__video_edit.deleteLater()
        self.__tutorial_edit.deleteLater()

    @staticmethod
    def text_of(editor: MarkdownEdit) -> str:
        """Read an editor's full text.

        :param editor: the editor.
        :returns: its text.
        """
        return bytes(editor.getText(editor.length() + 1).data()).decode("utf-8")

    @property
    def key(self) -> str | None:
        """The content key of the video whose notes are shown above the tutorial's, or ``None`` for none."""
        return self.__key

    @property
    def searching(self) -> bool:
        """Whether the video shown is still being looked for among the renamed ones, its editors disabled meanwhile."""
        return self.__searching

    @property
    def editing(self) -> bool:
        """Whether any panel is editing."""
        return self.__editing > 0

    def video_text(self) -> str:
        """The video's notes as recorded.

        :returns: them, empty when no video is shown.
        """
        return self.__model.video_notes_of(self.__key) if self.__key is not None else ""

    def tutorial_text(self) -> str:
        """The tutorial's notes as recorded.

        :returns: them.
        """
        return self.__model.notes

    def share(self, video_edit: MarkdownEdit, tutorial_edit: MarkdownEdit) -> None:
        """Make a panel's editors show the documents this holds.

        :param video_edit: the panel's editor of the video's notes.
        :param tutorial_edit: the panel's editor of the tutorial's notes.
        """
        video_edit.setDocPointer(self.__video_edit.docPointer())
        tutorial_edit.setDocPointer(self.__tutorial_edit.docPointer())

    def begin_editing(self) -> None:
        """Count one more panel editing; the first gives the documents their text."""
        self.__editing += 1
        if self.__editing == 1:
            self.__refresh()

    def end_editing(self) -> None:
        """Count one panel less editing, after it has written what it changed (:meth:`flush`)."""
        self.__editing = max(self.__editing - 1, 0)

    def set_video(self, key: str | None) -> None:
        """Show the notes of another video, after writing what was changed in the one before.

        A video with nothing recorded yet is looked for among the renamed ones first, and its editors are disabled
        until the search answers, so what the user types is never lost to, or written over, the note the search finds.

        :param key: the video's content key, or ``None`` for none -- the tutorial's notes alone are shown.
        """
        self.flush()
        self.__restored_key = None
        self.__key = key
        self.__pending_note = None
        # set before the search is asked for: a search that answers at once answers through __on_search_finished
        self.__searching = key is not None and key not in self.__model.video_data_keys()
        if self.__searching and not self.__model.reattach_renamed_progress():
            self.__searching = False
        self.__refresh()
        self.changed.emit()

    def restore_video(self, key: str) -> None:
        """Show the notes of the video shown when the session ended ([[plugins#session-restore]]), which the player
        loading its own video next does not take away: a note picked from the tree need not be the player's video.

        :param key: the video's content key.
        """
        self.set_video(key)
        self.__restored_key = key

    def follow_player(self, key: str | None) -> None:
        """Show the notes of the video the player has just selected -- once a session's note is shown, not over it.

        :param key: the video's content key, or ``None`` when the player has let go of its video.
        """
        restored = self.__restored_key
        self.set_video(restored if restored is not None and key is not None else key)

    def add_note(self, key: str, seconds: float) -> None:
        """Add a bookmark to a video's notes at a time, among its other bookmarks in time order.

        The line is only recorded -- into the video's document, written at once, while the notes are being edited,
        else straight into the video's notes -- with no change of mode and no focus taken (#574).

        :param key: the video's content key.
        :param seconds: the time the bookmark is at.
        """
        if key != self.__key:
            self.set_video(key)
        if self.__searching:
            # added once the search answers
            self.__pending_note = seconds
            return
        line = f"- [{clock_text(int(seconds * 1000))}]({video_href(key, seconds)}) "
        if self.editing:
            # inserted, not set whole: the caret, the selection and the undo history of the edit in progress stay
            editor = self.__video_edit
            before = self.text_of(editor)
            text, _ = insert_bookmark(before, line, seconds)
            # one chunk went in -- the line, with a newline before or after it -- where the two first differ
            start = next((at for at, (old, new) in enumerate(zip(before, text)) if old != new), len(before))
            # Scintilla's positions count bytes, not characters
            editor.insertText(len(text[:start].encode("utf-8")), text[start : start + len(text) - len(before)])
            self.flush()
            return
        text, _ = insert_bookmark(self.__model.video_notes_of(key), line, seconds)
        self.__model.record_notes(video_notes={key: text})

    def flush(self) -> None:
        """Record the notes the user changed in the editors, at once; nothing else is written."""
        if not self.editing:
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

    @staticmethod
    def __make_editor(parent: QWidget) -> MarkdownEdit:
        """An editor that holds a document and is never shown: a hidden child, so it is no window of its own.

        :param parent: the widget it goes with.
        :returns: the editor.
        """
        settings = shared_description_editor_settings()
        editor = MarkdownEdit(
            line_numbers=settings.show_line_numbers,
            line_endings_visible=settings.show_line_endings,
            wrap_long_lines=settings.wrap_long_lines,
        )
        editor.setParent(parent)
        editor.hide()
        return editor

    def __refresh(self) -> None:
        """Give the documents the notes as they are, while they are being edited."""
        if self.editing:
            self.__give(self.__video_edit, True, self.video_text())
            self.__give(self.__tutorial_edit, False, self.tutorial_text())

    def __on_search_finished(self) -> None:
        """Let the video's notes be edited, now the search for them among the renamed videos has answered, and add
        the bookmark asked for meanwhile."""
        if not self.__searching:
            return
        self.__searching = False
        self.__refresh()
        self.changed.emit()
        pending, self.__pending_note = self.__pending_note, None
        if pending is not None and self.__key is not None:
            self.add_note(self.__key, pending)

    def __on_notes_changed(self) -> None:
        """Show the notes again after they changed -- a write landing, a rename search finding them: an editor the user
        changed keeps its text."""
        key = self.__key
        if self.editing:
            if key is not None and self.__changed(self.__video_edit, True) is None:
                self.__give(self.__video_edit, True, self.__model.video_notes_of(key))
            if self.__changed(self.__tutorial_edit, False) is None:
                self.__give(self.__tutorial_edit, False, self.__model.notes)
        self.changed.emit()

    def __give(self, editor: MarkdownEdit, of_video: bool, text: str) -> None:
        """Put a text in a document as what it was given, unless it already holds it -- which keeps the carets.

        :param editor: the editor holding the document.
        :param of_video: whether it is the video's.
        :param text: what it is to hold.
        """
        self.__shown = {**self.__shown, of_video: text}
        if self.text_of(editor) != text:
            editor.setText(text)

    def __changed(self, editor: MarkdownEdit, of_video: bool) -> str | None:
        """What the user typed in a document.

        :param editor: the editor holding it.
        :param of_video: whether it is the video's.
        :returns: its text if it differs from what it was given, else ``None``.
        """
        text = self.text_of(editor)
        return text if text != self.__shown.get(of_video, "") else None
