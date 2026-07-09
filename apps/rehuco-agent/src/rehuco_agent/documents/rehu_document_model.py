"""Reactive view-model wrapping a `RehuDocument` for the viewer/editor surfaces ([[plugins#view-model]])."""

from pathlib import Path
from typing import Any, Final

from borco_pyside.core import SimpleProperty
from PySide6.QtCore import QObject
from rehuco_core import RehuDocument

from rehuco_agent.fields.field import Field, FieldBinding

INFO_REHU_FILENAME: Final = "info.rehu"
"""A directory-scoped resource's filename ([[data-model#resource-scoping]]); its label uses the parent
directory's name instead, since the literal filename is the same for every such resource."""

TYPE_FIELD_BOOL_DEFAULTS: Final = {
    "complete": True,
    "online": False,
    "viewed": False,
    "todo": False,
    "keep": False,
    "favorite": False,
}
"""The type-field boolean flags ([[field-schema#boolean-flags]]) and import defaults (``complete`` is ``true``)."""

TYPE_FIELD_INT_DEFAULTS: Final = {"rating": 0, "images_count": 0}
"""The type-field integer fields ([[field-schema#field-types]]) and their defaults; ``rating`` may be negative."""


class RehuDocumentModel(QObject):  # pylint: disable=too-many-instance-attributes
    """Reactive `QObject` over one `RehuDocument`, exposing common-core fields and a dirty flag
    ([[plugins#view-model]]).

    The viewer/editor surfaces bind to this instead of touching `RehuDocument` ([[data-model]]) directly, keeping
    the core non-GUI ([[plugins#core-vs-plugin]]). Setting ``title`` / ``publisher`` / ``url`` writes
    through to the document's **primary** source ([[field-schema#sources]]), marks the model dirty,
    and emits the field's ``<name>_changed`` signal -- which is what makes live "both" work: an edit
    in the editor updates the model, whose signal the viewer is bound to. ``sources`` is exposed as
    the list it is; the
    multi-source record-list editor is a later slice (A2.6/#26) that plugs into this seam. ``authors``
    / ``advertised_tags`` / ``extra_tags`` are common-core top-level lists, not source-scoped, so they
    write straight through to the document instead of through the primary source (A2.3/#23).
    :meth:`revert` is the write-through's mirror image: it re-reads the document from disk and
    reseeds every field, guarded so reseeding is never itself treated as an edit (#41).

    :param document: the document to wrap.
    :param parent: optional Qt parent.
    """

    title = SimpleProperty("")
    """The primary source's display title ([[field-schema#sources]])."""

    authors = SimpleProperty[list[str]](default_factory=list)
    """The shared ``authors`` list ([[field-schema#resource-types]])."""

    publisher = SimpleProperty("")
    """The primary source's publisher ([[field-schema#sources]])."""

    url = SimpleProperty("")
    """The primary source's URL ([[field-schema#sources]])."""

    complete = SimpleProperty(True)
    """The shared "all files present" flag ([[field-schema#boolean-flags]]); defaults ``true``."""

    online = SimpleProperty(False)
    """The shared "source still available online" flag ([[field-schema#online-flag]])."""

    viewed = SimpleProperty(False)
    """The per-user "viewed" flag ([[field-schema#per-user-shared]])."""

    todo = SimpleProperty(False)
    """The per-user "to do" flag ([[field-schema#per-user-shared]])."""

    keep = SimpleProperty(False)
    """The per-user "keep" flag ([[field-schema#per-user-shared]])."""

    favorite = SimpleProperty(False)
    """The per-user "favorite" flag ([[field-schema#boolean-flags]])."""

    rating = SimpleProperty(0)
    """The per-user rating ([[field-schema#per-user-shared]]); may be negative ([[field-schema#field-types]])."""

    images_count = SimpleProperty(0)
    """The ReferenceImages image count ([[field-schema#field-types]])."""

    advertised_tags = SimpleProperty[list[str]](default_factory=list)
    """The web-scraped ``advertised_tags`` list ([[field-schema#field-mapping]])."""

    extra_tags = SimpleProperty[list[str]](default_factory=list)
    """The personal ``extra_tags`` list ([[field-schema#field-mapping]])."""

    dirty = SimpleProperty(False)
    """True when the model holds edits not yet saved to disk."""

    def __init__(self, document: RehuDocument, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__document: Final = document
        self.__reverting = False

        # Seed the fields from the document *before* wiring the write-through handlers, so seeding a
        # freshly-loaded model never looks like an edit (no dirty, no document write-back).
        self.__seed_from_document()

        self.title_changed.connect(self.__on_title_changed)  # type: ignore[attr-defined]
        self.authors_changed.connect(self.__on_authors_changed)  # type: ignore[attr-defined]
        self.publisher_changed.connect(self.__on_publisher_changed)  # type: ignore[attr-defined]
        self.url_changed.connect(self.__on_url_changed)  # type: ignore[attr-defined]
        self.advertised_tags_changed.connect(self.__on_advertised_tags_changed)  # type: ignore[attr-defined]
        self.extra_tags_changed.connect(self.__on_extra_tags_changed)  # type: ignore[attr-defined]
        for name in (*TYPE_FIELD_BOOL_DEFAULTS, *TYPE_FIELD_INT_DEFAULTS):
            signal_name = SimpleProperty.notify_signal_name(type(self), name)
            getattr(self, signal_name).connect(lambda value, key=name: self.__on_type_field_changed(key, value))

    @classmethod
    def create_new(cls, path: Path | str | None = None, parent: QObject | None = None) -> RehuDocumentModel:
        """Start a new, empty document, optionally already bound to a save path.

        :param path: destination this document will save to by default. When given, the model
            starts dirty -- nothing is written to disk until :meth:`save`, but the caller already
            knows where it belongs (e.g. :meth:`~rehuco_agent.documents.documents_dock.DocumentsDock.open_folder`'s
            directory-scoped resource with no `info.rehu` yet). When omitted, the model starts
            clean, with no destination decided yet.
        :param parent: optional Qt parent.
        :returns: the new model, wrapping a fresh in-memory `RehuDocument`.
        """
        model = cls(RehuDocument({}, Path(path) if path is not None else None), parent)
        if path is not None:
            model.dirty = True
        return model

    @property
    def document(self) -> RehuDocument:
        """The wrapped document."""
        return self.__document

    @property
    def path(self) -> Path | None:
        """The document's file path, if any (the dock shell reuses-and-focuses by path)."""
        return self.__document.path

    @property
    def label(self) -> str:
        """This document's display label: the parent directory's name, trailing-slashed, for
        `info.rehu` ([[data-model#resource-scoping]]), the bare filename otherwise.

        :returns: the label, or an empty string when the document has no path yet.
        """
        path = self.path
        if path is None:
            return ""
        return f"{path.parent.name}/" if path.name == INFO_REHU_FILENAME else path.name

    @property
    def sources(self) -> list[dict[str, Any]]:
        """The document's ``sources`` list ([[field-schema#sources]]); the model edits its primary entry."""
        return self.__document.sources

    def save(self) -> None:
        """Atomically save the document ([[data-model#write-integrity]]) and clear the dirty flag."""
        self.__document.save()
        self.dirty = False

    def revert(self) -> None:
        """Discard in-memory edits and reseed every field from the document's file on disk.

        Re-reads the file (:meth:`RehuDocument.reload`) rather than just resetting to the
        last-loaded snapshot, so an out-of-band edit ([[data-model#write-integrity]]) is picked up
        too. Reseeding is guarded the same way construction is, so it never looks like an edit --
        no write-back to the document, and :attr:`dirty` ends up ``False`` regardless of what it was.

        :raises ValueError: if the document has no path (was never loaded from or saved to a file).
        """
        self.__document.reload()
        self.__reverting = True
        try:
            self.__seed_from_document()
        finally:
            self.__reverting = False
        self.dirty = False

    def bind[T](self, field: Field[T]) -> FieldBinding[T]:
        """Resolve a field into its current binding on this model ([[plugins#field-toolkit]], `FieldModel`).

        :param field: the field to resolve; its :attr:`~Field.name` must match a `SimpleProperty`
            declared on this class.
        :returns: the field's current value, its notify signal, and a setter.
        """
        name = field.name
        return FieldBinding(
            value=getattr(self, name),
            changed=getattr(self, SimpleProperty.notify_signal_name(type(self), name)),
            set_value=lambda value: setattr(self, name, value),
        )

    def __seed_from_document(self) -> None:
        """Set every field from :attr:`document`'s current in-memory state (construction and :meth:`revert`)."""
        self.title = self.__document.title
        self.authors = self.__document.authors
        self.publisher = self.__document.publisher
        self.url = self.__document.url
        self.advertised_tags = self.__document.advertised_tags
        self.extra_tags = self.__document.extra_tags

        # The type-field scalar fields read/write generically through the type-keyed plugin block
        # ([[field-schema#resource-types]]); values are coerced defensively (malformed -> default, #35).
        for name, default in TYPE_FIELD_BOOL_DEFAULTS.items():
            setattr(self, name, bool(self.__document.type_field(name, default)))
        for name, default in TYPE_FIELD_INT_DEFAULTS.items():
            value = self.__document.type_field(name, default)
            setattr(self, name, value if isinstance(value, int) and not isinstance(value, bool) else default)

    def __on_title_changed(self, value: str) -> None:
        """Write an edited title through to the document's primary source and mark dirty.

        No-op while :meth:`revert` is reseeding -- see the comment there.

        :param value: the new title.
        """
        if self.__reverting:
            return
        self.__document.title = value
        self.dirty = True

    def __on_authors_changed(self, value: list[str]) -> None:
        """Write an edited authors list through to the document and mark dirty.

        No-op while :meth:`revert` is reseeding -- see the comment there.

        :param value: the new authors list.
        """
        if self.__reverting:
            return
        self.__document.authors = value
        self.dirty = True

    def __on_publisher_changed(self, value: str) -> None:
        """Write an edited publisher through to the document's primary source and mark dirty.

        No-op while :meth:`revert` is reseeding -- see the comment there.

        :param value: the new publisher.
        """
        if self.__reverting:
            return
        self.__document.publisher = value
        self.dirty = True

    def __on_url_changed(self, value: str) -> None:
        """Write an edited url through to the document's primary source and mark dirty.

        No-op while :meth:`revert` is reseeding -- see the comment there.

        :param value: the new url.
        """
        if self.__reverting:
            return
        self.__document.url = value
        self.dirty = True

    def __on_advertised_tags_changed(self, value: list[str]) -> None:
        """Write an edited advertised_tags list through to the document and mark dirty.

        No-op while :meth:`revert` is reseeding -- see the comment there.

        :param value: the new advertised_tags list.
        """
        if self.__reverting:
            return
        self.__document.advertised_tags = value
        self.dirty = True

    def __on_extra_tags_changed(self, value: list[str]) -> None:
        """Write an edited extra_tags list through to the document and mark dirty.

        No-op while :meth:`revert` is reseeding -- see the comment there.

        :param value: the new extra_tags list.
        """
        if self.__reverting:
            return
        self.__document.extra_tags = value
        self.dirty = True

    def __on_type_field_changed(self, key: str, value: Any) -> None:
        """Write an edited type-field scalar through to the document's plugin block and mark dirty.

        No-op while :meth:`revert` is reseeding -- see the comment there.

        :param key: the type-field key that changed.
        :param value: the new value.
        """
        if self.__reverting:
            return
        self.__document.set_type_field(key, value)
        self.dirty = True
