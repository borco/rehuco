"""The `authors` leaf field: a rich-text link viewer plus a two-mode editor -- a comma line while it
is lossless, record rows otherwise ([[plugins#field-toolkit]], [[field-schema#authors]]).
"""

import html
import logging
from collections.abc import Sequence
from typing import Final, override

from PySide6.QtCore import QObject, QSignalBlocker, Qt, QUrl, Signal
from PySide6.QtGui import QCursor, QDesktopServices
from PySide6.QtWidgets import QLabel, QToolTip
from rehuco_core import AuthorEntry, author_name

from .author_url import HTTP_SCHEMES, is_http_author_url
from .field import Field, FieldBinding, FieldEditorWidgets, FieldViewerWidgets
from .text_list_string import TextListString
from .widgets import AuthorsEditor, ExpandToggleButton
from .widgets.authors_editor import SIMPLE_UNAVAILABLE_TOOLTIP

LOG: Final = logging.getLogger(__name__)

FILTER_SCHEME: Final = "filter"
"""The click-to-filter internal scheme ([[plugins#filter-urls]]) -- a logged no-op here until a
browser exists to filter against; no author-name anchor emits it yet, but the
dispatch handler already recognizes it so it is never mistaken for an external link and sent to
:class:`~PySide6.QtGui.QDesktopServices`."""

MODE_TOOLTIP: Final = "Edit the authors as rows, with a link for each."
"""What the row's misc-column toggle offers, while both modes are on offer."""


class AuthorsField(Field[Sequence[AuthorEntry]], QObject):
    """An ``authors`` field ([[plugins#field-toolkit]], [[field-schema#authors]]): the viewer renders
    each entry as an HTML-escaped name, with a trailing ``(url)`` link for a strict http/https URL;
    the editor is an :class:`~rehuco_agent.fields.widgets.AuthorsEditor`, which is the comma-separated
    ``QLineEdit`` the other list fields use for as long as every entry survives a round-trip through
    it, and one row per author -- name and author-page URL -- whenever an entry would not
    (:func:`~rehuco_core.authors_comma_editable`).

    The row's ``misc`` column carries the toggle between the two (#97), which is what the lock
    indicator #95 put there was standing in for: with a lossless editor now reachable, a value the
    comma line cannot represent is no longer a flag on a disabled control but a switch to the editor
    that *can* show it. The toggle disables itself, tooltipped, exactly while the simple mode is
    unavailable -- the mode on screen is then not the user's to choose, and a control that silently
    does nothing is worse than one that says why.

    The viewer's link never auto-follows (``setOpenExternalLinks(False)``): one
    :meth:`__on_link_activated` handler dispatches on the href's scheme instead, so a future
    ``filter://`` anchor (:data:`FILTER_SCHEME`) can never reach
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
        editor = AuthorsEditor()
        # the mode is a view state of this document, restored per ``.rehu`` (`StatefulWidget`), and the
        # owner collects those by object name
        editor.setObjectName(self.name)
        # the ignore: PySide types a class-level ``Signal`` as ``Signal``, not as the
        # ``SignalInstance`` an *instance* actually exposes, so no widget declaring one ever satisfies
        # a protocol naming it statically
        self.bind_value_widget(editor, binding)  # type: ignore[arg-type]  # value_changed is a class-level Signal

        toggle = ExpandToggleButton()
        toggle.toggled.connect(editor.set_advanced)
        editor.mode_changed.connect(lambda: self.__sync_toggle(toggle, editor))
        self.__sync_toggle(toggle, editor)
        return FieldEditorWidgets(self.editor_tab, self.make_label(), editor, toggle)

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
            if isinstance(url, str) and is_http_author_url(url):
                parts.append(f'{name_html} (<a href="{html.escape(url)}">url</a>)')
            else:
                parts.append(name_html)
        return TextListString.join(parts)

    def __on_link_activated(self, href: str) -> None:
        """Dispatch a clicked viewer link by its scheme -- the shared shape ``tags``/``publishers``
        will reuse once they linkify too ([[plugins#filter-urls]]).

        :param href: the clicked anchor's href.
        """
        scheme = QUrl(href).scheme().lower()
        if scheme == FILTER_SCHEME:
            LOG.info("click-to-filter link is not wired yet: %s", href)
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

    @staticmethod
    def __sync_toggle(toggle: ExpandToggleButton, editor: AuthorsEditor) -> None:
        """Show the editor's current mode on the toggle, and whether it is the user's to change.

        Blocked while it is written: a forced mode must not read back as a *choice*, or a document
        whose authors all carry links would leave the user in the rows for good once the value became
        representable again.

        :param toggle: the row's misc-column toggle.
        :param editor: the editor whose mode it shows.
        """
        available = editor.simple_available
        with QSignalBlocker(toggle):
            toggle.setChecked(editor.advanced)
        # on the action, not the button: a tool button showing a default action mirrors it, and would
        # undo an enabled state or a tooltip set on itself at the next refresh
        action = toggle.defaultAction()
        action.setEnabled(available)
        action.setToolTip(MODE_TOOLTIP if available else SIMPLE_UNAVAILABLE_TOOLTIP)

    # endregion
