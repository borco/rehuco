"""The License sub-dock: a record's licenses, and the text of the one selected, read as rendered Markdown and edited
in place ([[assets#licenses]], #688, #705)."""

import html
from typing import Final

import cbor2
from borco_pyside.core import ConnectionList
from PySide6.QtCore import QSignalBlocker, QUrl
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import QWidget
from rehuco_core import AssetLicense, LicenseTerms

from ..commands import LICENSE_EDIT, shared_command_registry
from ..fields.widgets.markdown_edit import MarkdownEdit
from ..rehuco.web_pages import is_web_page
from ..settings.description_editor_settings import shared_description_editor_settings
from ..settings.markdown_rendering_settings import shared_markdown_rendering_settings
from .license_panel_ui import Ui_LicensePanel
from .licenses_list_editor import LicensesListEditor
from .rehu_document_model import RehuDocumentModel

EDITING_STATE_KEY: Final = "editing"
"""The key of a panel's saved state: whether it shows the editors."""

UNREADABLE_HINT: Final = " It cannot be shown or edited until the file is fixed; Revert reads it again."
"""What follows the reason a ``.rehuterms`` could not be read."""

READ_ONLY_HINT: Final = " It cannot be edited now."
"""What follows the info line while the document cannot take an edit."""


class LicensePanel(QWidget):
    """One view of a record's licenses: the list of them, and for the one selected its title, where and when its text
    was read, and the terms as rendered Markdown, until the **Edit** action makes the list editable -- add, delete, a
    grip to drag a row by, its id picked or typed and its URL typed in place (:class:`LicensesListEditor`) -- and
    swaps in the Markdown editor; a preset picked brings its text, which the list reads in the background. The first
    license is selected when the record is shown, and a selection is kept while its license is, under a new id too.

    **The licenses and their texts are the document's, edited as any of its details are**: an edit writes through
    (:meth:`~rehuco_agent.documents.rehu_document_model.RehuDocumentModel.edit_license` and the list's own) and makes
    the document dirty, and the record's Save writes the ``.rehuterms`` with it -- no write of its own, so Revert
    drops an edit and a save that cannot land is a failed save. A license being added has no text until it has an
    id. The ``url`` and the date it was read are shown, never edited: only a refresh makes them. **A file that cannot
    be read** is named and left alone until it is fixed; **a document that cannot be written** shows the terms and
    cannot edit them.

    A link in the terms opens in the system's browser when it is a web page, and does nothing otherwise: the text is
    outside input. Images are never loaded.

    :param model: the document, whose license text this shows.
    :param parent: optional Qt parent.
    """

    def __init__(self, model: RehuDocumentModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__model: Final = model
        self.__editing = False
        self.__selected: str | None = None
        """The short id of the license whose text is shown, or ``None`` while the record holds none."""
        self.__settings: Final = ConnectionList()
        self.__ui: Final = Ui_LicensePanel()
        self.__ui.setupUi(self)
        self.__editor: Final = self.__make_editor()
        self.__ui.text_stack.addWidget(self.__editor)
        self.__list: Final = LicensesListEditor(model, self)
        self.__ui.main_layout.insertWidget(0, self.__list)
        self.__list.current_index_changed.connect(self.__sync_selected)
        self.__list.licenses.dataChanged.connect(self.__sync_selected)
        view = self.__ui.text_view
        view.setOpenLinks(False)
        view.setOpenExternalLinks(False)
        view.set_images_visible(False)
        view.anchorClicked.connect(self.__on_anchor)
        self.__ui.info_label.linkActivated.connect(self.__on_link)
        self.__ui.edit_action.toggled.connect(self.__on_edit_toggled)
        self.__editor.notifyChange.connect(lambda *_: self.__on_text_edited())
        shared_command_registry().bind(self.__ui.edit_action, LICENSE_EDIT.id)
        self.addAction(self.__ui.edit_action)
        self.__follow_settings()
        model.licenses_changed.connect(self.__on_licenses_changed)  # type: ignore[attr-defined]
        self.__on_licenses_changed(model.licenses)
        for signal in (
            model.license_terms_changed,  # type: ignore[attr-defined]
            model.license_unreadable_changed,  # type: ignore[attr-defined]
            model.lock_reasons_changed,  # type: ignore[attr-defined]
            model.reading_changed,  # type: ignore[attr-defined]
            model.reloaded,
        ):
            signal.connect(self.__show)
        self.__show()

    def detach(self) -> None:
        """Stop following the document and the settings, before this panel is destroyed."""
        model = self.__model
        model.licenses_changed.disconnect(self.__on_licenses_changed)  # type: ignore[attr-defined]
        self.__list.detach()
        for signal in (
            model.license_terms_changed,  # type: ignore[attr-defined]
            model.license_unreadable_changed,  # type: ignore[attr-defined]
            model.lock_reasons_changed,  # type: ignore[attr-defined]
            model.reading_changed,  # type: ignore[attr-defined]
            model.reloaded,
        ):
            signal.disconnect(self.__show)
        self.__settings.clear()

    @property
    def title_bar_actions(self) -> list[QAction]:
        """*Edit*, for the dock's title bar."""
        return [self.__ui.edit_action]

    @property
    def selected(self) -> str | None:
        """The short id of the license whose text is shown, or ``None`` while the record holds none."""
        return self.__selected

    @property
    def editing(self) -> bool:
        """Whether this panel shows the editors, not the rendered terms."""
        return self.__editing

    def set_editing(self, editing: bool) -> None:
        """Show the editors, or the rendered terms, as the Edit action does -- the editors only while the document can
        take an edit.

        :param editing: whether the editors are to be shown.
        """
        self.__ui.edit_action.setChecked(editing and self.__editable())

    def save_state(self) -> bytes:
        """Encode whether the editors are shown, for the dock's entry in the layout.

        :returns: the state, restorable by :meth:`restore_state`.
        """
        return cbor2.dumps({EDITING_STATE_KEY: self.__editing})

    def restore_state(self, state: bytes) -> None:
        """Restore what :meth:`save_state` encoded. The keyboard stays where it is: a restored editor is not one the
        reader just asked for.

        :param state: the blob; one that cannot be read leaves everything as it is.
        """
        try:
            values = cbor2.loads(state)
        except cbor2.CBORDecodeError:
            return
        editing = values.get(EDITING_STATE_KEY) if isinstance(values, dict) else None
        if isinstance(editing, bool):
            self.set_editing(editing)

    # region Setup

    @staticmethod
    def __make_editor() -> MarkdownEdit:
        """The Markdown editor, as the description's: its three view settings as they are now.

        :returns: the editor.
        """
        settings = shared_description_editor_settings()
        return MarkdownEdit(
            line_numbers=settings.show_line_numbers,
            line_endings_visible=settings.show_line_endings,
            wrap_long_lines=settings.wrap_long_lines,
        )

    def __follow_settings(self) -> None:
        """Render and edit as the description does, and follow its settings."""
        self.__settings.clear_on_destroyed(self)
        rendering = shared_markdown_rendering_settings()
        editing = shared_description_editor_settings()
        self.__apply_rendering()
        self.__settings.connect(rendering.description_rendering_changed, self.__apply_rendering)
        self.__settings.connect(editing.description_editor_changed, self.__apply_editor_settings)

    def __apply_rendering(self) -> None:
        """Render again after the Markdown settings changed."""
        rendering = shared_markdown_rendering_settings()
        self.__ui.text_view.apply_rendering_settings(engine=rendering.engine, css=rendering.css)

    def __apply_editor_settings(self) -> None:
        """Give the editor the description editor's view settings as they are now."""
        settings = shared_description_editor_settings()
        self.__editor.line_numbers = settings.show_line_numbers
        self.__editor.line_endings_visible = settings.show_line_endings
        self.__editor.wrap_long_lines = settings.wrap_long_lines

    # endregion

    # region What it shows

    def __terms(self) -> LicenseTerms | None:
        """The selected license's text.

        :returns: its terms; ``None`` when none is selected or it has no text.
        """
        texts = self.__model.license_terms
        return None if texts is None or self.__selected is None else texts.get(self.__selected)

    def __editable(self) -> bool:
        """Whether the document can take an edit of the text now.

        :returns: ``False`` for one locked, still being read, not yet read, with no file of its own or whose sidecar
            cannot be read.
        """
        model = self.__model
        return not (model.locked or model.reading is not None or model.pending or model.license_unreadable) and (
            model.path is not None
        )

    def __show(self) -> None:
        """Show the license text as the document holds it: the title, the line saying where it is from, the rendered
        terms, and what the editors hold -- each only where it differs, so a keystroke is never echoed back."""
        terms = self.__terms()
        editable = self.__editable()
        self.__ui.edit_action.setEnabled(editable)
        if not editable and self.__editing:
            self.__ui.edit_action.setChecked(False)
        self.__show_title(terms)
        self.__set_info(self.__info(terms, editable))
        if not self.__editing:
            self.__render()
        self.__give("" if terms is None else terms.text)
        self.__editor.setEnabled(editable and self.__selected is not None)

    def __show_title(self, terms: LicenseTerms | None) -> None:
        """Show the selected license's title above its rendered terms; none while editing, where the list holds it.

        :param terms: the selected license's terms, or ``None`` for none.
        """
        title = "" if terms is None else terms.title
        self.__ui.title_label.set_text(title)
        self.__ui.title_label.setVisible(bool(title) and not self.__editing)

    def __render(self) -> None:
        """Render the terms as they are -- not while they are being typed, which the viewer behind the editor would
        render again at every keystroke; leaving the editors does."""
        terms = self.__terms()
        self.__ui.text_view.set_markdown("" if terms is None else terms.text)

    def __set_info(self, line: str) -> None:
        """Show the line under the title, and the label only while it says something.

        :param line: the line, as rich text; empty for none.
        """
        self.__ui.info_label.setText(line)
        self.__ui.info_label.setVisible(bool(line))

    def __info(self, terms: LicenseTerms | None, editable: bool) -> str:
        """The line under the title: where and when the terms were read, or why they cannot be shown.

        :param terms: the selected license's terms, or ``None`` for none.
        :param editable: whether the document can take an edit.
        :returns: the line, as rich text; empty for a license with no text, whose empty view says so itself.
        """
        reason = self.__model.license_unreadable
        if reason:
            return html.escape(reason + UNREADABLE_HINT)
        if terms is None:
            return ""
        day = terms.read.isoformat()
        if terms.url is None:
            line = html.escape(f"Written for this item, {day}.")
        else:
            address = html.escape(terms.url)
            where = f'<a href="{address}">{address}</a>' if is_web_page(terms.url) else address
            line = f"Read {day} from {where}."
        return line if editable else line + html.escape(READ_ONLY_HINT)

    def __give(self, text: str) -> None:
        """Put the text in the editor, where it differs -- without writing it back.

        :param text: the terms' Markdown.
        """
        if self.__text() != text:
            with QSignalBlocker(self.__editor):
                self.__editor.setText(text)

    def __text(self) -> str:
        """What the Markdown editor holds.

        :returns: its text.
        """
        return bytes(self.__editor.getText(self.__editor.length() + 1).data()).decode("utf-8")

    # endregion

    # region What is done to it

    def __on_edit_toggled(self, editing: bool) -> None:
        """Make the list editable and swap the rendered terms for the editor, or back.

        :param editing: whether the editors are to be shown.
        """
        self.__editing = editing
        self.__list.set_editable(editing)
        terms = self.__terms()
        self.__show_title(terms)
        self.__set_info(self.__info(terms, self.__editable()))
        if not editing:
            self.__render()
        self.__ui.text_stack.setCurrentIndex(1 if editing else 0)

    def __on_text_edited(self) -> None:
        """Hand the text the user typed to the document."""
        if self.__selected is not None:
            self.__model.edit_license(self.__selected, text=self.__text())

    def __on_licenses_changed(self, licenses: list[AssetLicense]) -> None:
        """Show the record's licenses, keeping the one selected while the record still holds it, else the first; a row
        being added stays where it is.

        :param licenses: the licenses, in order.
        """
        keep = self.__selected
        rows = self.__list.licenses
        rows.set_entries(licenses)
        current = self.__list.current_index
        if 0 <= current < rows.count and rows.license_at(current) in (keep, None):
            self.__sync_selected()
            return
        row = rows.row_of(keep) if keep is not None else -1
        self.__list.set_current_index(row if row >= 0 else (0 if rows.count else -1))
        self.__sync_selected()

    def __sync_selected(self, *_args: object) -> None:
        """Show the text of the license in the current row -- after the row changed, or the license in it did.

        :param _args: whichever signal's arguments arrived; unused.
        """
        self.__set_selected(self.__list.licenses.license_at(self.__list.current_index))

    def __set_selected(self, license_id: str | None) -> None:
        """Show one license's text.

        :param license_id: its short id, or ``None`` for none.
        """
        if license_id == self.__selected:
            return
        self.__selected = license_id
        self.__show()

    def __on_anchor(self, url: QUrl) -> None:
        """Take a click on a link in the rendered terms.

        :param url: the link's target.
        """
        self.__on_link(url.toString(QUrl.ComponentFormattingOption.FullyEncoded))

    @staticmethod
    def __on_link(href: str) -> None:
        """Open a link in the system's browser if it is a web page; the text is outside input, so any other is left.

        :param href: the link's target.
        """
        if is_web_page(href):
            QDesktopServices.openUrl(QUrl(href))

    # endregion
