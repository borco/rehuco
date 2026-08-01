"""Which archive entries count as a reference-images resource's content ([[data-model#image-meanings]], #222).

`rehuco_core.rehu_content_images.enumerate_content_images` takes the recognized image extensions as a
parameter rather than reading a constant, so this is where that set comes from: one editable list, shown
as a block on the `Plugins > Images` settings page. A pack in a format the shipped set omits (``.bmp``,
``.tif``, ``.tga``, ``.psd``) is a preference change rather than a rebuild. Readers ask
:attr:`ReferenceImagesSettings.content_image_extensions` and never read the stored list directly -- one
naming nothing resolves to :data:`~rehuco_core.CONTENT_IMAGE_EXTENSIONS`, so a list left empty never makes
every reference-images resource count zero images.

A plain ``@dataclass``, unlike `ImageViewerSettings`: that one earns ``SimpleProperty`` because applying it
visibly resizes strips already on screen, whereas this set is read only when an enumeration runs, so there
is nothing to watch it change. Same shape as `ExcludedFilesSettings`, and for the same reason.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Final

from PySide6.QtCore import QSettings
from rehuco_core import CONTENT_IMAGE_EXTENSIONS

from .persistent_settings import persistent_settings, read_stored_strings

GROUP: Final = "reference_images"
EXTENSIONS_KEY: Final = "extensions"


def normalize_extensions(values: Sequence[str]) -> tuple[str, ...]:
    """Normalize an extension list into the form the enumeration matches against.

    Surrounding whitespace is ignored and a leading dot is optional, so ``jpg``, ``.jpg`` and ``  JPG ``
    all mean the same entry: every entry normalizes to lower case with exactly one leading dot. Empty
    entries and duplicates are dropped rather than rejected, keeping a blank row or a repeated format
    from being an error the user has to fix.

    A list holding no usable entry at all -- empty, or nothing but whitespace and bare dots -- falls back
    to :data:`~rehuco_core.CONTENT_IMAGE_EXTENSIONS`: a list left empty must not silently make every
    reference-images resource count zero images.

    :param values: the entries as edited or as stored.
    :returns: the recognized extensions, lower-cased and dot-prefixed, in the order first seen, or the
        shipped set when ``values`` names none.
    """
    extensions: list[str] = []
    for entry in values:
        stem = entry.strip().lstrip(".").lower()
        if not stem:
            continue
        extension = f".{stem}"
        if extension not in extensions:
            extensions.append(extension)
    return tuple(extensions) or CONTENT_IMAGE_EXTENSIONS


def read_extensions(value: object) -> tuple[str, ...]:
    """Coerce the stored value into the entry list it was saved as.

    Reading the stored shape at all -- including the ini backend's habit of handing a single-element
    list back as a bare string -- is
    :func:`~rehuco_agent.settings.persistent_settings.read_stored_strings`'s job; all this adds is
    dropping a blank entry, which is a row the editor would show as nothing.

    :param value: the raw stored value.
    :returns: the entries, otherwise as typed.
    """
    return tuple(entry for entry in read_stored_strings(value) if entry)


@dataclass
class ReferenceImagesSettings:
    """The reference-images plugin's own settings: today, which entries count as content images.

    One stored field, as the page left it; what everything else consumes is
    :attr:`content_image_extensions`, the set it resolves to.
    """

    extensions: tuple[str, ...] = field(default_factory=tuple)
    """The recognized image extensions as stored -- empty on a fresh install, where the effective set is
    the shipped one rather than nothing."""

    @property
    def content_image_extensions(self) -> tuple[str, ...]:
        """The effective extension set the content-image enumeration is handed
        ([[data-model#resource-scoping]]): :attr:`extensions` normalized, falling back to
        :data:`~rehuco_core.CONTENT_IMAGE_EXTENSIONS` when it names nothing usable
        (:func:`normalize_extensions`)."""
        return normalize_extensions(self.extensions)

    def load(self, settings: QSettings) -> None:
        """Replace the stored list with what's in persistent storage.

        A never-saved, empty or unreadable value comes back as no entries, which resolves to the shipped
        set rather than to no recognized formats at all (:func:`read_extensions`).

        :param settings: the ``QSettings`` to read from.
        """
        settings.beginGroup(GROUP)
        self.extensions = read_extensions(settings.value(EXTENSIONS_KEY))
        settings.endGroup()

    def save(self, settings: QSettings) -> None:
        """Save the list to persistent storage, as a list the ini backend can round-trip.

        :param settings: the ``QSettings`` to write to.
        """
        settings.beginGroup(GROUP)
        settings.setValue(EXTENSIONS_KEY, list(self.extensions))
        settings.endGroup()


@lru_cache(maxsize=1)
def shared_reference_images_settings() -> ReferenceImagesSettings:
    """The single, process-wide `ReferenceImagesSettings` instance, loaded from persistent storage on
    first call -- the same shape, and for the same reason, as
    :func:`~rehuco_agent.settings.identity_settings.shared_identity_settings`: the settings page's Save
    must be what the next enumeration reads, not a disconnected per-reader copy.

    :returns: the shared instance.
    """
    settings = ReferenceImagesSettings()
    settings.load(persistent_settings())
    return settings
