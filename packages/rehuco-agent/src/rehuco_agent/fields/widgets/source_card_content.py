"""What one source card holds: Title, URL and Publisher line edits ([[field-schema#sources]], #391)."""

from typing import Any, Final, cast, override

from borco_pyside.widgets import toggle_dynamic_property
from PySide6.QtCore import QEvent, QObject, Signal
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QFormLayout, QLabel, QWidget

from ...scraping.url_drop import UrlDrop
from ..author_url import is_http_author_url
from ..colors import WARNING_COLOR
from .authors_table_model import INVALID_URL_REASON
from .line_edit import LineEdit


class UrlEditDropFilter(QObject):
    """Sets a URL edit's text to the link dropped on it, instead of inserting the link's text into it.

    A `QLineEdit` already accepts a plain-text drop and would insert the link's characters at the drop point;
    what a link dropped **on a URL edit** means is the edit's new text, whole. Only a link is taken here: any
    other drop is left to the edit's own handling. The edits beside it accept no drops at all
    (:class:`SourceCardContent`), which is what lets a link dropped anywhere else on the card reach the Main
    Editor dock's scrape.

    :param edit: the URL edit.
    """

    def __init__(self, edit: LineEdit) -> None:
        super().__init__(edit)
        self.__edit: Final = edit
        edit.installEventFilter(self)

    @override
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802  (Qt override)
        if watched is not self.__edit or event.type() not in (
            QEvent.Type.DragEnter,
            QEvent.Type.DragMove,
            QEvent.Type.Drop,
        ):
            return False
        drop_event = cast(QDropEvent, event)
        drop = UrlDrop.parse(drop_event.mimeData())
        if drop is None:
            return False
        drop_event.acceptProposedAction()
        if event.type() == QEvent.Type.Drop:
            self.__edit.setText(drop.url)
        return True


class SourceCardContent(QWidget):
    """One source, as three captioned line edits: a `CardContent` ([[plugins#field-toolkit]]).

    **Merge, don't rebuild.** :meth:`item_values` starts from the source the card was shown, changing only
    the keys whose edit was touched: a key this card has no edit for is kept, and an emptied edit deletes its
    key rather than writing ``""``. Opening a source and typing in one edit therefore never rewrites another
    field, nor a key a later version adds.

    **Flagged, never refused.** A source with an address or a publisher but no title, and an address that is
    not an http(s) one, are painted in the warning colour with the reason as a tooltip; the value is kept
    either way. A card holding nothing yet is not flagged -- it is just started.

    **The top card is the primary**, but nothing on the card says so: the captions stay plain, so dragging a
    card never makes a different one look changed.

    A link dropped on the URL edit replaces its text (:class:`UrlEditDropFilter`); the title and publisher
    edits accept no drops, so a link dropped on them reaches the dock behind the editor.

    :param parent: optional Qt parent.
    """

    value_changed = Signal()
    """Fires on every edit."""

    TITLE_KEY: Final = "title"
    URL_KEY: Final = "url"
    PUBLISHER_KEY: Final = "publisher"

    MISSING_TITLE_REASON: Final = "A source needs a title."
    """Why an untitled source that says something else is flagged."""

    WARNING_STYLESHEET: Final = f'QLineEdit[warning="true"] {{ color: {WARNING_COLOR}; }}'
    """Paints an edit's text in the warning colour while its source is flagged for it."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__item: dict[str, Any] = {}
        self.__shown: dict[str, str] = {}
        self.__title: Final = LineEdit(self)
        self.__url: Final = LineEdit(self)
        self.__publisher: Final = LineEdit(self)
        self.__edits: Final = {
            self.TITLE_KEY: self.__title,
            self.URL_KEY: self.__url,
            self.PUBLISHER_KEY: self.__publisher,
        }
        self.__captions: Final = [QLabel(text, self) for text in ("Title", "URL", "Publisher")]
        self.setStyleSheet(self.WARNING_STYLESHEET)
        layout = QFormLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        for caption, edit in zip(self.__captions, self.__edits.values(), strict=True):
            layout.addRow(caption, edit)
        for edit in (self.__title, self.__publisher):
            edit.setAcceptDrops(False)
        UrlEditDropFilter(self.__url)  # parented to the edit, which is what keeps it alive
        for edit in self.__edits.values():
            edit.value_changed.connect(self.__on_edited)

    @property
    def title_edit(self) -> LineEdit:
        """The Title line edit."""
        return self.__title

    @property
    def url_edit(self) -> LineEdit:
        """The URL line edit."""
        return self.__url

    @property
    def publisher_edit(self) -> LineEdit:
        """The Publisher line edit."""
        return self.__publisher

    @property
    def captions(self) -> tuple[QLabel, ...]:
        """The Title, URL and Publisher captions, in row order."""
        return tuple(self.__captions)

    def set_item(self, item: Any) -> None:
        """Show ``item`` without emitting :attr:`value_changed`.

        :param item: the source record.
        """
        self.__item = dict(item)
        self.__shown = {key: value if isinstance(value, str) else "" for key, value in self.__item.items()}
        for key, edit in self.__edits.items():
            edit.set_value(self.__shown.get(key, ""))
        self.__flag()

    def item_values(self) -> dict[str, Any]:
        """The source as the edits now read it: the shown record, with every touched key updated.

        :returns: the merged record.
        """
        item = dict(self.__item)
        for key, edit in self.__edits.items():
            text = edit.text()
            if text == self.__shown.get(key, ""):
                continue
            if text:
                item[key] = text
            else:
                item.pop(key, None)
        return item

    def buddies(self) -> tuple[QWidget, QWidget]:
        """Insert sits on the Title row, above delete on the Publisher row -- the order of the buttons beside
        the item tables (``[+]`` first).

        :returns: the delete button's buddy, then the insert button's.
        """
        return self.__publisher, self.__title

    def __on_edited(self) -> None:
        """Re-flag the source and pass the edit on."""
        self.__flag()
        self.value_changed.emit()

    def __flag(self) -> None:
        """Flag the edits whose value the source is faulted for, with the reason as their tooltip."""
        title, url, publisher = (edit.text() for edit in self.__edits.values())
        untitled = not title.strip() and bool(url.strip() or publisher.strip())
        bad_url = bool(url.strip()) and not is_http_author_url(url.strip())
        for edit, flagged, reason in (
            (self.__title, untitled, self.MISSING_TITLE_REASON),
            (self.__url, bad_url, INVALID_URL_REASON),
        ):
            toggle_dynamic_property(edit, "warning", flagged)
            edit.setToolTip(reason if flagged else "")
