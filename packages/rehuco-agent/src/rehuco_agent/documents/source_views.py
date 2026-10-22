"""Read-only inspection views over a document's raw JSON (#111).

Two surfaces, each a read-only, mouse-selectable, monospaced (#75) scroll of text -- **not** an editor
(the raw-text repair editor for unparseable docks is separate, #103):

- :class:`SavePreviewView` -- the model's *live* serialization, exactly what a Save would write to disk
  (reflecting unsaved edits and the in-memory format upgrade).
- :class:`OnDiskView` -- the *verbatim* bytes currently on disk, or a placeholder when the document has
  no file yet. For a legacy ``.tc``-backed document that path is the ``.tc`` itself, so this shows the
  original ``.tc`` ([[acquisition-tooling#tc-to-rehu]]).

A record is stored as more than one file -- the ``.rehu`` and one sidecar per user ([[data-model#single-file]], #513)
-- so each view shows one section per file, the record first, under a banner that collapses it the way a content-image
group's does. Every section starts expanded.

The two differ exactly when the in-memory model and the files diverge: an unsaved edit, or a
just-loaded older-format file the model has upgraded in memory but not yet written back.
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Final, override

from borco_pyside.core import SimpleProperty
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontDatabase, QMouseEvent, QPalette, QShowEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget
from rehuco_core import user_sidecar_path

from .content_images.content_images_view import BANNER_INSET, BANNER_MARK_WIDTH, COLLAPSED_MARK, EXPANDED_MARK
from .rehu_document_model import RehuDocumentModel

NOT_ON_DISK_PLACEHOLDER: Final = "(not saved on disk yet)"
"""Shown by :class:`OnDiskView` when the document has no readable file yet -- a brand-new/unsaved
document, or one whose path doesn't (yet) exist on disk."""

UNSAVED_RECORD: Final = Path("untitled.rehu")
"""What :class:`SavePreviewView` names the files of a document with no path yet."""

ON_DISK_REFRESH_FIELDS: Final = ("dirty", "saving", "path", "lock_reasons")
"""The model properties whose change re-reads :class:`OnDiskView` from disk. Deliberately **not** the
value fields (which fire per keystroke): the on-disk bytes only change at file-touching seams -- a save
landing (``saving`` clears, #497: ``dirty`` already cleared when Save handed the edits over), a revert or
convert (``lock_reasons``/``path`` recompute), or a new save path -- so re-reading the file on those alone
keeps a large file off the per-keystroke path.

Not the whole set: a property only notifies on an *actual* change, so reverting a clean, unlocked
document moves none of these (#174). ``RehuDocumentModel.reloaded`` covers that seam unconditionally and
:class:`OnDiskView` subscribes to it as well."""


class SourceFileBanner(QWidget):
    """One file's banner: its collapse mark in a fixed column, then its name -- bold, in the palette's placeholder
    colour, as a content-image group's banner is painted. A click toggles the file's section.

    :param name: the file's name.
    :param parent: optional Qt parent.
    """

    clicked = Signal(str)
    """The banner was clicked, carrying its file's name."""

    def __init__(self, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__mark: Final = QLabel(EXPANDED_MARK)
        self.__mark.setFixedWidth(BANNER_MARK_WIDTH)
        self.__mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.__name: Final = QLabel(name)
        for label in (self.__mark, self.__name):
            font = label.font()
            font.setBold(True)
            label.setFont(font)
            label.setForegroundRole(QPalette.ColorRole.PlaceholderText)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(BANNER_INSET, 0, BANNER_INSET, 0)
        layout.setSpacing(0)
        layout.addWidget(self.__mark)
        layout.addWidget(self.__name, 1)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    @property
    def text(self) -> str:
        """What the banner says: its mark and the file's name, e.g. ``- info.rehu``."""
        return f"{self.__mark.text()} {self.__name.text()}"

    def set_collapsed(self, collapsed: bool) -> None:
        """Show the mark of a collapsed or an expanded section.

        :param collapsed: whether the section is collapsed.
        """
        self.__mark.setText(COLLAPSED_MARK if collapsed else EXPANDED_MARK)

    @override
    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Toggle the section on a left click.

        :param event: the Qt mouse event.
        """
        if event.button() is Qt.MouseButton.LeftButton:
            self.clicked.emit(self.__name.text())
            event.accept()
            return
        super().mousePressEvent(event)


class SourceFilesView(QScrollArea):
    """A read-only, mouse-selectable, monospaced (#75) scroll of files, one collapsible section each.

    The shared shell both inspection views render into: per file, a :class:`SourceFileBanner` over a `QLabel`
    (plain-text, so JSON's ``<``/``&`` are never taken as rich-text markup; no wrapping, so long lines scroll
    horizontally rather than reflow), all inside one scroll area (so a large document scrolls rather than being
    truncated). Subclasses feed it files via :meth:`set_files`. A file collapsed stays collapsed while it is shown
    again under the same name.

    :param parent: optional Qt parent.
    """

    TEXT_MARGIN: Final = 6
    """Padding (px) around the text, so it doesn't sit flush against the scroll area's edge."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__collapsed: Final[set[str]] = set()
        self.__sections: list[tuple[str, SourceFileBanner, QLabel]] = []
        self.__body: Final = QWidget()
        self.__layout: Final = QVBoxLayout(self.__body)
        self.__layout.setContentsMargins(0, 0, 0, 0)
        self.__layout.setSpacing(0)
        self.__layout.addStretch(1)
        self.setWidget(self.__body)
        self.setWidgetResizable(True)

    def set_files(self, files: Sequence[tuple[str, str]]) -> None:
        """Show ``files``, each verbatim under its name.

        :param files: each file's name and text, in the order to show them.
        """
        if [name for name, _ in files] != [name for name, _, _ in self.__sections]:
            self.__rebuild([name for name, _ in files])
        for (_, text), (_, _, label) in zip(files, self.__sections, strict=True):
            label.setText(text)

    def files(self) -> list[tuple[str, str]]:
        """What is shown: each file's name and text.

        :returns: the files, in the order shown.
        """
        return [(name, label.text()) for name, _, label in self.__sections]

    def banner(self, name: str) -> SourceFileBanner:
        """The banner of a file shown.

        :param name: the file's name.
        :returns: its banner.
        :raises KeyError: no file of that name is shown.
        """
        return self.__section(name)[1]

    def text_label(self, name: str) -> QLabel:
        """The label a file's text is shown in.

        :param name: the file's name.
        :returns: its label.
        :raises KeyError: no file of that name is shown.
        """
        return self.__section(name)[2]

    def is_collapsed(self, name: str) -> bool:
        """Whether a file's section is collapsed.

        :param name: the file's name.
        :returns: whether it is.
        """
        return name in self.__collapsed

    def set_collapsed(self, name: str, collapsed: bool) -> None:
        """Collapse or expand a file's section.

        :param name: the file's name.
        :param collapsed: whether to collapse it.
        """
        if collapsed:
            self.__collapsed.add(name)
        else:
            self.__collapsed.discard(name)
        for shown, banner, label in self.__sections:
            if shown == name:
                banner.set_collapsed(collapsed)
                label.setVisible(not collapsed)

    def __toggle(self, name: str) -> None:
        """Collapse an expanded file's section, or expand a collapsed one -- what a click on its banner does.

        :param name: the file's name.
        """
        self.set_collapsed(name, name not in self.__collapsed)

    def __section(self, name: str) -> tuple[str, SourceFileBanner, QLabel]:
        """A file's section.

        :param name: the file's name.
        :returns: its name, banner and label.
        :raises KeyError: no file of that name is shown.
        """
        for section in self.__sections:
            if section[0] == name:
                return section
        raise KeyError(name)

    def __rebuild(self, names: list[str]) -> None:
        """Replace the sections with one per name, each collapsed as it was when last shown.

        :param names: the files' names, in the order to show them.
        """
        for _, banner, label in self.__sections:
            for widget in (banner, label):
                self.__layout.removeWidget(widget)
                widget.deleteLater()
        self.__sections = []
        fixed = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()
        for index, name in enumerate(names):
            banner = SourceFileBanner(name, self.__body)
            label = QLabel(self.__body)
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            label.setMargin(self.TEXT_MARGIN)
            font = label.font()
            font.setFamily(fixed)
            label.setFont(font)
            banner.clicked.connect(self.__toggle)
            self.__layout.insertWidget(2 * index, banner)
            self.__layout.insertWidget(2 * index + 1, label)
            self.__sections.append((name, banner, label))
            collapsed = name in self.__collapsed
            banner.set_collapsed(collapsed)
            label.setVisible(not collapsed)


class SavePreviewView(SourceFilesView):
    """The live "what a Save would write" preview: the model's current serialization (#111).

    Renders :meth:`~rehuco_core.RehuDocument.serialize` and each sidecar
    :meth:`~rehuco_core.RehuDocument.serialize_user_sidecars` renders -- byte-for-byte what a save would write -- and
    always reflects the current in-memory state once shown, unsaved edits included. While hidden (e.g. a
    QtAds tab in the background) a change only flags the preview stale rather than re-serializing on the
    spot, so a large document doesn't re-render on every keystroke it can't be seen for; the deferred
    render catches up in :meth:`showEvent`. This is the model view, so it shows the in-memory format
    upgrade a just-loaded older file has already had, which is why it can differ from :class:`OnDiskView`.

    :param model: the reactive view-model whose document is serialized.
    :param parent: optional Qt parent.
    """

    def __init__(self, model: RehuDocumentModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__model: Final = model
        self.__stale = False
        # enumerate the model's declared properties rather than hand-listing them, so a field added
        # later stays reflected here with no second list to keep in step; unknown_fields_changed (a
        # dropped fallback field) is a plain Signal, not a property, so it's wired separately
        model_type = type(model)
        for name in SimpleProperty.property_names(model_type):
            getattr(model, SimpleProperty.notify_signal_name(model_type, name)).connect(self.__on_model_changed)
        model.unknown_fields_changed.connect(self.__on_model_changed)
        self.__render()

    def __on_model_changed(self, *_args: object) -> None:
        """Re-render if currently visible, else defer the render to the next :meth:`showEvent`.

        :param _args: whatever value the triggering notify signal carried; unused -- the text is always
            re-read whole from the document.
        """
        if self.isVisible():
            self.__render()
        else:
            self.__stale = True

    @override
    def showEvent(self, event: QShowEvent) -> None:
        """Catch up a render deferred while hidden, e.g. a QtAds tab switched back into view.

        :param event: the Qt show event, forwarded to the base class.
        """
        super().showEvent(event)
        if self.__stale:
            self.__render()

    def __render(self) -> None:
        """Re-serialize the document and show it, the record first and then each sidecar in slug order."""
        document = self.__model.document
        record = document.path or UNSAVED_RECORD
        sidecars = document.serialize_user_sidecars()
        self.set_files(
            [(record.name, document.serialize())]
            + [(user_sidecar_path(record, slug).name, text) for slug, text in sidecars.items()]
        )
        self.__stale = False


class OnDiskView(SourceFilesView):
    """The verbatim on-disk file contents -- exactly the bytes currently on disk (#111): the record, then every user's
    sidecar beside it ([[data-model#single-file]]).

    Reads the document's own :attr:`~RehuDocumentModel.path` straight off disk, unparsed, so it shows
    the file as it actually sits there -- including a still-older ``format_version`` the model has
    already upgraded in memory but not written back, and, for a legacy ``.tc``-backed document, the
    original ``.tc`` itself ([[acquisition-tooling#tc-to-rehu]]). A document with no readable file yet
    (brand-new/unsaved) shows :data:`NOT_ON_DISK_PLACEHOLDER` instead, under the name it would have.

    Re-read only at the seams that actually change the file -- a save, a revert, a convert, or a new save
    path -- never on the per-keystroke value signals, so a large file isn't re-read on every edit. Two
    subscriptions together make up "the seams": the :data:`ON_DISK_REFRESH_FIELDS` properties, plus
    `RehuDocumentModel.reloaded`, which fires unconditionally on a revert/convert and so also catches the
    revert of a *clean, unlocked* document -- the out-of-band-edit workflow Revert advertises, where no
    property moves at all (#174).

    **A hidden view reads nothing** -- the same discipline :class:`SavePreviewView` and the checksum
    dock already keep: a seam crossed while hidden only flags the text stale, and :meth:`showEvent`
    catches it up. This dock starts closed, so no file is read merely because a document was opened --
    which is also what keeps a session-restored placeholder's file untouched until its tab is actually
    viewed (#66); no :attr:`~RehuDocumentModel.pending` check is needed here, because *visible* is
    exactly the condition that makes the read legitimate.

    :param model: the reactive view-model whose file is shown.
    :param parent: optional Qt parent.
    """

    def __init__(self, model: RehuDocumentModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__model: Final = model
        self.__stale = True
        model_type = type(model)
        for name in ON_DISK_REFRESH_FIELDS:
            getattr(model, SimpleProperty.notify_signal_name(model_type, name)).connect(self.__on_file_seam)
        model.reloaded.connect(self.__on_file_seam)

    def __on_file_seam(self, *_args: object) -> None:
        """Re-read if currently visible, else defer the read to the next :meth:`showEvent`.

        :param _args: whatever value the triggering notify signal carried; unused -- the path is always
            re-read whole from the model.
        """
        if self.isVisible():
            self.__render()
        else:
            self.__stale = True

    @override
    def showEvent(self, event: QShowEvent) -> None:
        """Catch up a read deferred while hidden -- the dock being opened, or its tab switched back to.

        :param event: the Qt show event, forwarded to the base class.
        """
        super().showEvent(event)
        if self.__stale:
            self.__render()

    def __render(self) -> None:
        """Re-read the files from disk (or fall back to the placeholder) and show them."""
        self.set_files(self.__read_on_disk())
        self.__stale = False

    def __read_on_disk(self) -> list[tuple[str, str]]:
        """The document's files as they sit on disk, or :data:`NOT_ON_DISK_PLACEHOLDER` when there is no
        readable file (no local path, or one that doesn't exist -- a never-saved document).

        :returns: each file's name and verbatim text, or the record's name and the placeholder.
        """
        record = self.__model.path or UNSAVED_RECORD
        if self.__model.key is None:
            return [(record.name, NOT_ON_DISK_PLACEHOLDER)]
        try:
            return self.__model.stored_files()
        except OSError:
            return [(record.name, NOT_ON_DISK_PLACEHOLDER)]
