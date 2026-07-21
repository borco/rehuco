"""Read-only inspection views over a document's raw JSON (#111).

Two surfaces, each a read-only, mouse-selectable, monospaced (#75) scroll of text -- **not** an editor
(the raw-text repair editor for unparseable docks is separate, #103):

- :class:`SavePreviewView` -- the model's *live* serialization, exactly what a Save would write to disk
  (reflecting unsaved edits and the in-memory format upgrade).
- :class:`OnDiskView` -- the *verbatim* bytes currently on disk, or a placeholder when the document has
  no file yet. For a legacy ``.tc``-backed document that path is the ``.tc`` itself, so this shows the
  original ``.tc`` ([[acquisition-tooling#tc-to-rehu]]).

The two differ exactly when the in-memory model and the file diverge: an unsaved edit, or a
just-loaded older-format file the model has upgraded in memory but not yet written back.
"""

from typing import Final

from borco_pyside.core import SimpleProperty
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QLabel, QScrollArea, QWidget

from .rehu_document_model import RehuDocumentModel

NOT_ON_DISK_PLACEHOLDER: Final = "(not saved on disk yet)"
"""Shown by :class:`OnDiskView` when the document has no readable file yet -- a brand-new/unsaved
document, or one whose path doesn't (yet) exist on disk."""

ON_DISK_REFRESH_FIELDS: Final = ("dirty", "path", "lock_reasons")
"""The model properties whose change re-reads :class:`OnDiskView` from disk. Deliberately **not** the
value fields (which fire per keystroke): the on-disk bytes only change at file-touching seams -- a save
(``dirty`` clears), a revert or convert (``lock_reasons``/``path`` recompute), or a new save path -- so
re-reading the file on those alone keeps a large file off the per-keystroke path."""


class MonospaceTextView(QScrollArea):
    """A read-only, mouse-selectable, monospaced (#75) scroll of plain text.

    The shared shell both inspection views render into: a `QLabel` (plain-text, so JSON's ``<``/``&``
    are never taken as rich-text markup; no wrapping, so long lines scroll horizontally rather than
    reflow) inside a scroll area (so a large document scrolls rather than being truncated). Subclasses
    feed it text via :meth:`set_text`.

    :param label_object_name: the inner label's object name, so a specific view's content is findable.
    :param parent: optional Qt parent.
    """

    TEXT_MARGIN: Final = 6
    """Padding (px) around the text, so it doesn't sit flush against the scroll area's edge."""

    def __init__(self, label_object_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__label: Final = QLabel()
        self.__label.setObjectName(label_object_name)
        self.__label.setTextFormat(Qt.TextFormat.PlainText)
        self.__label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.__label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.__label.setMargin(self.TEXT_MARGIN)
        font = self.__label.font()
        font.setFamily(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family())
        self.__label.setFont(font)
        self.setWidget(self.__label)
        self.setWidgetResizable(True)

    def set_text(self, text: str) -> None:
        """Show ``text`` verbatim.

        :param text: the plain text to display.
        """
        self.__label.setText(text)


class SavePreviewView(MonospaceTextView):
    """The live "what a Save would write" preview: the model's current serialization (#111).

    Renders :meth:`~rehuco_core.RehuDocument.serialize` -- byte-for-byte what a save would write --
    and stays live even while hidden, re-rendering on every one of the model's field/dirty/lock notify
    signals so it always reflects the current in-memory state, unsaved edits included (the same "both
    stay live regardless of visibility" contract the viewer/editor docks have). This is the model view,
    so it shows the in-memory format upgrade a just-loaded older file has already had, which is why it
    can differ from :class:`OnDiskView`.

    :param model: the reactive view-model whose document is serialized.
    :param parent: optional Qt parent.
    """

    LABEL_NAME: Final = "save_preview_json"
    """Object name of the inner JSON label."""

    def __init__(self, model: RehuDocumentModel, parent: QWidget | None = None) -> None:
        super().__init__(self.LABEL_NAME, parent)
        self.__model: Final = model
        # enumerate the model's declared properties rather than hand-listing them, so a field added
        # later stays reflected here with no second list to keep in step; unknown_fields_changed
        # (a dropped fallback field) is a plain Signal, not a property, so it's wired separately
        model_type = type(model)
        for name in SimpleProperty.property_names(model_type):
            getattr(model, SimpleProperty.notify_signal_name(model_type, name)).connect(self.__render)
        model.unknown_fields_changed.connect(self.__render)
        self.__render()

    def __render(self, *_args: object) -> None:
        """Re-serialize the document and show it.

        :param _args: whatever value the triggering notify signal carried; unused -- the text is always
            re-read whole from the document.
        """
        self.set_text(self.__model.document.serialize())


class OnDiskView(MonospaceTextView):
    """The verbatim on-disk file contents -- exactly the bytes currently on disk (#111).

    Reads the document's own :attr:`~RehuDocumentModel.path` straight off disk, unparsed, so it shows
    the file as it actually sits there -- including a still-older ``format_version`` the model has
    already upgraded in memory but not written back, and, for a legacy ``.tc``-backed document, the
    original ``.tc`` itself ([[acquisition-tooling#tc-to-rehu]]). A document with no readable file yet
    (brand-new/unsaved) shows :data:`NOT_ON_DISK_PLACEHOLDER` instead.

    Re-read only at the seams that actually change the file (:data:`ON_DISK_REFRESH_FIELDS`) -- a save,
    a revert, a convert, or a new save path -- never on the per-keystroke value signals, so a large
    file isn't re-read on every edit.

    :param model: the reactive view-model whose file is shown.
    :param parent: optional Qt parent.
    """

    LABEL_NAME: Final = "on_disk_text"
    """Object name of the inner text label."""

    def __init__(self, model: RehuDocumentModel, parent: QWidget | None = None) -> None:
        super().__init__(self.LABEL_NAME, parent)
        self.__model: Final = model
        model_type = type(model)
        for name in ON_DISK_REFRESH_FIELDS:
            getattr(model, SimpleProperty.notify_signal_name(model_type, name)).connect(self.__render)
        self.__render()

    def __render(self, *_args: object) -> None:
        """Re-read the file from disk (or fall back to the placeholder) and show it.

        :param _args: whatever value the triggering notify signal carried; unused -- the path is always
            re-read whole from the model.
        """
        self.set_text(self.__read_on_disk())

    def __read_on_disk(self) -> str:
        """The document's file as it sits on disk, or :data:`NOT_ON_DISK_PLACEHOLDER` when there is no
        readable file (no path yet, or a path that doesn't exist -- a never-saved document).

        :returns: the verbatim file text, or the placeholder.
        """
        path = self.__model.path
        if path is None:
            return NOT_ON_DISK_PLACEHOLDER
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return NOT_ON_DISK_PLACEHOLDER
