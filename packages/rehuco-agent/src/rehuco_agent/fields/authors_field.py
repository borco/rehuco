"""The `authors` leaf field: a rich-text link viewer plus a lossless-guarded comma editor
([[plugins#field-toolkit]], [[field-schema#authors]]).
"""

import html
import logging
from collections.abc import Sequence
from typing import Final, override
from urllib.parse import urlsplit

from borco_pyside.theming import ActionIconThemeHandler
from PySide6.QtCore import QObject, QSignalBlocker, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QCursor, QDesktopServices
from PySide6.QtWidgets import QLabel, QLineEdit, QToolButton, QToolTip
from rehuco_core import AuthorEntry, author_name, authors_comma_editable

from .field import Field, FieldBinding, FieldEditorWidgets, FieldViewerWidgets
from .text_list_string import TextListString

LOG: Final = logging.getLogger(__name__)

FILTER_SCHEME: Final = "filter"
"""The click-to-filter internal scheme ([[plugins#filter-urls]]) -- a logged no-op here until a
browser exists to filter against (Milestone B); no author-name anchor emits it yet, but the
dispatch handler already recognizes it so it is never mistaken for an external link and sent to
:class:`~PySide6.QtGui.QDesktopServices`."""

HTTP_SCHEMES: Final = ("http", "https")

LOCK_ICON_RESOURCE: Final = ":/icons/lock_on.svg"
"""The disabled editor's lock indicator -- a static flag, not yet a control: clicking it does
nothing until #97's deferred advanced editor gives it something to open."""

DISABLED_EDITOR_TOOLTIP: Final = (
    "Some authors have a link, or a comma in the name, that this simple editor can't show. "
    "Editing here would drop it -- use the detailed editor (coming soon)."
)
"""Explains *why* the comma editor disabled itself and *where* the lossless path will be, without
alarming -- the guard prevents loss, it isn't a mere restriction (#97's deferred record-list editor
is that "coming soon")."""


class AuthorsField(Field[Sequence[AuthorEntry]], QObject):
    """An ``authors`` field ([[plugins#field-toolkit]], [[field-schema#authors]]): the viewer renders
    each entry as an HTML-escaped name, with a trailing ``(url)`` link for a strict http/https URL;
    the editor keeps :class:`~rehuco_agent.fields.text_list_field.TextListField`'s comma-separated
    ``QLineEdit`` shape but disables itself (tooltipped, with a lock icon in the row's ``misc``
    column) whenever an entry would be corrupted by a round-trip through it -- a record entry, or a
    name containing a comma (:func:`~rehuco_core.authors_comma_editable`). The lock icon is a static
    flag for now, not a control -- #97's deferred advanced editor is what will eventually give a
    click on it something to open.

    The viewer's link never auto-follows (``setOpenExternalLinks(False)``): one
    :meth:`__on_link_activated` handler dispatches on the href's scheme instead, so a future
    ``filter://`` anchor (:data:`FILTER_SCHEME`, Milestone B) can never reach
    :class:`~PySide6.QtGui.QDesktopServices` by accident, and no other scheme is ever followed.
    """

    TYPE = "authors"

    status_message: Signal = Signal(str)
    """Fires with a hovered link's URL for the **owner to route** to the real status bar (an empty
    string on leave, to clear it) -- the `StatusReporter` contract ([[plugins#field-toolkit]]). The field
    emits rather than driving the status bar itself: a toolkit field must not reach for app chrome it does
    not own, which was exactly the smell here. The routing -- and the empirically-verified ``.window()``
    trap it sidesteps -- now lives at the genuine top-level owner
    (:class:`~rehuco_agent.main_window.MainWindow`), which is the one wired to a real status bar."""

    @override
    def make_viewer(self, binding: FieldBinding[Sequence[AuthorEntry]]) -> FieldViewerWidgets:
        label = QLabel()
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setWordWrap(True)
        label.setOpenExternalLinks(False)
        label.linkActivated.connect(self.__on_link_activated)
        label.linkHovered.connect(lambda href: self.__on_link_hovered(label, href))
        label.setText(self.__to_html(binding.value))
        self.bind_external(binding.changed, lambda value: label.setText(self.__to_html(value)))
        return FieldViewerWidgets(self.viewer_tab, self.make_label(), label)

    @override
    def make_editor(self, binding: FieldBinding[Sequence[AuthorEntry]]) -> FieldEditorWidgets:
        line_edit = QLineEdit()
        line_edit.textChanged.connect(lambda text: binding.set_value(TextListString.split(text)))
        lock = self.__make_lock_indicator()
        self.__apply(line_edit, lock, binding.value)
        self.bind_external(binding.changed, lambda value: self.__apply(line_edit, lock, value))
        return FieldEditorWidgets(self.editor_tab, self.make_label(), line_edit, lock)

    # region viewer

    def __to_html(self, entries: Sequence[AuthorEntry]) -> str:
        """Render ``entries`` as the viewer's rich text: each name escaped, with a trailing ``(url)``
        anchor for a strict http/https URL -- anything else (no URL, a non-http(s) scheme, a malformed
        value) renders as if the entry carried no URL at all ([[data-model#write-integrity]]).

        :param entries: the authors entries to render, string or record alike.
        :returns: the joined rich-text HTML.
        """
        parts = []
        for entry in entries:
            name_html = html.escape(author_name(entry))
            url = entry.get("url") if isinstance(entry, dict) else None
            if isinstance(url, str) and self.__is_http_url(url):
                parts.append(f'{name_html} (<a href="{html.escape(url)}">url</a>)')
            else:
                parts.append(name_html)
        return TextListString.join(parts)

    @staticmethod
    def __is_http_url(value: str) -> bool:
        """Whether ``value`` parses strictly as an absolute http/https URL.

        :param value: the candidate URL string.
        :returns: ``True`` iff the scheme is ``http``/``https`` and a host is present.
        """
        parsed = urlsplit(value)
        return parsed.scheme in HTTP_SCHEMES and bool(parsed.netloc)

    def __on_link_activated(self, href: str) -> None:
        """Dispatch a clicked viewer link by its scheme -- the shared shape ``tags``/``publishers``
        will reuse once they linkify too ([[plugins#filter-urls]]).

        :param href: the clicked anchor's href.
        """
        scheme = QUrl(href).scheme().lower()
        if scheme == FILTER_SCHEME:
            LOG.info("click-to-filter link is not wired yet (Milestone B): %s", href)
        elif scheme in HTTP_SCHEMES:
            QDesktopServices.openUrl(QUrl(href))
        else:
            LOG.warning("ignoring an authors link with an unsupported scheme: %s", href)

    def __on_link_hovered(self, label: QLabel, href: str) -> None:
        """Show ``href`` as a tooltip while hovering and report it as a status message; clear both once
        the cursor leaves the link (``href`` empty).

        The status text is emitted as :attr:`status_message` for the **owner** to route to the real
        status bar (`StatusReporter`), never driven from here -- the field toolkit does not reach for app
        chrome it does not own.

        :param label: the viewer label the link belongs to.
        :param href: the hovered anchor's href, or empty on leave.
        """
        if href:
            QToolTip.showText(QCursor.pos(), href, label)
        else:
            QToolTip.hideText()
        self.status_message.emit(href)

    # endregion

    # region editor

    def __apply(self, line_edit: QLineEdit, lock: QToolButton, value: Sequence[AuthorEntry]) -> None:
        """Seed or echo the editor from ``value``, toggling the lossless-round-trip guard live.

        Enabled (every entry a comma-free plain string): the editor round-trips the list as typed,
        same as :class:`~rehuco_agent.fields.text_list_field.TextListField` -- the echo guard compares
        the editor's own *parsed* text against ``value``, not the raw text, so a user's own keystroke
        doesn't bounce back and reset the cursor. Disabled (a record entry, or a comma in a name): the
        editor goes fully ``setEnabled(False)``, tooltipped with :data:`DISABLED_EDITOR_TOOLTIP`,
        showing each entry's plain name (:func:`~rehuco_core.author_name`) -- a display only, never
        written back -- with the row's lock indicator shown alongside it.

        :param line_edit: the editor to update.
        :param lock: the row's lock indicator, shown exactly while the editor is disabled.
        :param value: the current authors list.
        """
        editable = authors_comma_editable(value)
        line_edit.setEnabled(editable)
        line_edit.setToolTip("" if editable else DISABLED_EDITOR_TOOLTIP)
        lock.setVisible(not editable)
        if editable:
            # authors_comma_editable's own guarantee: every entry is a plain string here
            names = [entry for entry in value if isinstance(entry, str)]
            if TextListString.split(line_edit.text()) != names:
                with QSignalBlocker(line_edit):
                    line_edit.setText(TextListString.join(names))
        else:
            text = TextListString.join(author_name(entry) for entry in value)
            if line_edit.text() != text:
                with QSignalBlocker(line_edit):
                    line_edit.setText(text)

    @staticmethod
    def __make_lock_indicator() -> QToolButton:
        """Build the row's lock indicator: a themed, initially-hidden static icon flagging that some
        entries can't be shown in the simple editor -- purely a flag, not yet a control (clicking it
        does nothing until #97's deferred advanced editor gives it something to open).

        :returns: the lock button, hidden until :meth:`__apply` shows it.
        """
        button = QToolButton()
        action = QAction(button)
        action.setToolTip(DISABLED_EDITOR_TOOLTIP)
        ActionIconThemeHandler(action, LOCK_ICON_RESOURCE)
        button.setDefaultAction(action)
        button.setVisible(False)
        return button

    # endregion
