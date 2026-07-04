"""Reactive view-model wrapping a `RehuDocument` for the viewer/editor surfaces (§13.2.2)."""

from pathlib import Path
from typing import Any, Final

from borco_pyside.core import SimpleProperty, notify_signal_name
from PySide6.QtCore import QObject
from rehuco_core import RehuDocument

from rehuco_agent.fields.field import Field, FieldBinding


class RehuDocumentModel(QObject):
    """Reactive `QObject` over one `RehuDocument`, exposing common-core fields and a dirty flag (§13.2.2).

    The viewer/editor surfaces bind to this instead of touching `RehuDocument` (§4) directly, keeping
    the core non-GUI (§13.1). Setting ``title`` / ``publisher`` / ``url`` writes through to the
    document's **primary** source (§17.2.3), marks the model dirty, and emits the field's
    ``<name>_changed`` signal -- which is what makes live "both" work: an edit in the editor updates
    the model, whose signal the viewer is bound to. ``sources`` is exposed as the list it is; the
    multi-source record-list editor is a later slice (A2.3/#23, A2.6/#26) that plugs into this seam.

    :param document: the document to wrap.
    :param parent: optional Qt parent.
    """

    title = SimpleProperty("")
    """The primary source's display title (§17.2.3)."""

    publisher = SimpleProperty("")
    """The primary source's publisher (§17.2.3)."""

    url = SimpleProperty("")
    """The primary source's URL (§17.2.3)."""

    dirty = SimpleProperty(False)
    """True when the model holds edits not yet saved to disk."""

    def __init__(self, document: RehuDocument, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__document: Final = document

        # Seed the fields from the document *before* wiring the write-through handlers, so seeding a
        # freshly-loaded model never looks like an edit (no dirty, no document write-back).
        self.title = document.title
        self.publisher = document.publisher
        self.url = document.url

        self.title_changed.connect(self.__on_title_changed)  # type: ignore[attr-defined]
        self.publisher_changed.connect(self.__on_publisher_changed)  # type: ignore[attr-defined]
        self.url_changed.connect(self.__on_url_changed)  # type: ignore[attr-defined]

    @property
    def document(self) -> RehuDocument:
        """The wrapped document."""
        return self.__document

    @property
    def path(self) -> Path | None:
        """The document's file path, if any (the dock shell reuses-and-focuses by path)."""
        return self.__document.path

    @property
    def sources(self) -> list[dict[str, Any]]:
        """The document's ``sources`` list (§17.2.3); the model edits its primary entry."""
        return self.__document.sources

    def save(self) -> None:
        """Atomically save the document (§4.9) and clear the dirty flag."""
        self.__document.save()
        self.dirty = False

    def bind[T](self, field: Field[T]) -> FieldBinding[T]:
        """Resolve a field into its current binding on this model (§13.2.1, `FieldModel`).

        :param field: the field to resolve; its :attr:`~Field.name` must match a `SimpleProperty`
            declared on this class.
        :returns: the field's current value, its notify signal, and a setter.
        """
        name = field.name
        return FieldBinding(
            value=getattr(self, name),
            changed=getattr(self, notify_signal_name(type(self), name)),
            set_value=lambda value: setattr(self, name, value),
        )

    def __on_title_changed(self, value: str) -> None:
        """Write an edited title through to the document's primary source and mark dirty.

        :param value: the new title.
        """
        self.__document.title = value
        self.dirty = True

    def __on_publisher_changed(self, value: str) -> None:
        """Write an edited publisher through to the document's primary source and mark dirty.

        :param value: the new publisher.
        """
        self.__document.publisher = value
        self.dirty = True

    def __on_url_changed(self, value: str) -> None:
        """Write an edited url through to the document's primary source and mark dirty.

        :param value: the new url.
        """
        self.__document.url = value
        self.dirty = True
