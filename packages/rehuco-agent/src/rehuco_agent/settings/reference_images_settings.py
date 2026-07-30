"""Which archive entries count as a reference-images resource's content ([[data-model#image-meanings]], #222).

`rehuco_core.rehu_content_images.enumerate_content_images` takes the recognized image extensions as a
parameter rather than reading a constant, so this is where that set comes from. The choice is a pair of
radio buttons on the settings page: **Default** uses core's
:data:`~rehuco_core.CONTENT_IMAGE_EXTENSIONS` (never restated here), **Custom** uses a user-typed
comma-separated list -- a reference pack in a format the default set omits (``.bmp``, ``.tif``, ``.tga``,
``.psd``) would otherwise count zero images with no recourse but a rebuild. Both halves of the choice
persist: the custom text survives a switch back to Default, so trying the defaults again doesn't cost a
retyped list. Readers ask :attr:`ReferenceImagesSettings.content_image_extensions` for the effective set
and never look at the raw pair.

A plain ``@dataclass``, unlike `ImageViewerSettings`: that one earns ``SimpleProperty`` because applying it
visibly resizes strips already on screen, whereas this set is read only when an enumeration runs, so there
is nothing to watch it change. Same shape as `IdentitySettings`, and for the same reason.
"""

from dataclasses import dataclass
from functools import lru_cache
from typing import Final, cast

from PySide6.QtCore import QSettings
from rehuco_core import CONTENT_IMAGE_EXTENSIONS

from .persistent_settings import persistent_settings

GROUP: Final = "reference_images"
USE_CUSTOM_EXTENSIONS_KEY: Final = "use_custom_extensions"
CUSTOM_EXTENSIONS_KEY: Final = "custom_extensions"

SEPARATOR: Final = ","
"""What separates one extension from the next, in the custom list as typed and as stored -- the list is
edited as one comma-separated string, so it goes through :func:`parse_extensions` on every read and
:func:`format_extensions` when a set is shown as text."""


def parse_extensions(text: str) -> tuple[str, ...]:
    """Parse a comma-separated extension list into the form the enumeration matches against.

    Surrounding whitespace is ignored and a leading dot is optional, so ``jpg``, ``.jpg`` and ``  JPG ``
    all mean the same entry: every entry normalizes to lower case with exactly one leading dot. Empty
    entries and duplicates are dropped rather than rejected, keeping a trailing comma or a repeated
    format from being an error the user has to fix.

    Text holding no usable entry at all -- empty, whitespace, or nothing but separators -- falls back to
    :data:`~rehuco_core.CONTENT_IMAGE_EXTENSIONS`: a custom list naming nothing must not silently make
    every reference-images resource count zero images.

    :param text: the raw list as typed or as stored.
    :returns: the recognized extensions, lower-cased and dot-prefixed, in the order first seen, or the
        default set when ``text`` names none.
    """
    extensions: list[str] = []
    for entry in text.split(SEPARATOR):
        stem = entry.strip().lstrip(".").lower()
        if not stem:
            continue
        extension = f".{stem}"
        if extension not in extensions:
            extensions.append(extension)
    return tuple(extensions) or CONTENT_IMAGE_EXTENSIONS


def format_extensions(extensions: tuple[str, ...]) -> str:
    """Format an extension set the way a custom list is typed: comma-separated, dots kept.

    :param extensions: the extensions to format, as :func:`parse_extensions` returns them.
    :returns: e.g. ``".jpg, .jpeg, .png"`` -- what :func:`parse_extensions` reads back unchanged.
    """
    return f"{SEPARATOR} ".join(extensions)


@dataclass
class ReferenceImagesSettings:
    """The reference-images plugin's own settings: today, which entries count as content images.

    Both stored fields are raw: the choice between the default and the custom set, and the custom list
    exactly as typed -- persisted verbatim, and even while Default is selected, so switching away and
    back never loses it. What everything else consumes is :attr:`content_image_extensions`, the
    effective set the pair resolves to.
    """

    use_custom_extensions: bool = False
    """Whether the custom list is in effect. Off means core's default set, with nothing restated."""

    custom_extensions: str = ""
    """The custom comma-separated list, exactly as typed -- normalized only when read through
    :attr:`content_image_extensions`, never in storage, so what the user typed is what they get back."""

    @property
    def content_image_extensions(self) -> tuple[str, ...]:
        """The effective extension set the content-image enumeration is handed
        ([[data-model#resource-scoping]]): the parsed custom list when it is selected, core's
        :data:`~rehuco_core.CONTENT_IMAGE_EXTENSIONS` otherwise. A selected custom list naming nothing
        usable also resolves to the default set (:func:`parse_extensions`'s fallback)."""
        if self.use_custom_extensions:
            return parse_extensions(self.custom_extensions)
        return CONTENT_IMAGE_EXTENSIONS

    def load(self, settings: QSettings) -> None:
        """Replace both stored fields with what's in persistent storage.

        Values that were never saved fall back to the defaults-selected, empty-custom-list state; a
        stored custom list is restored verbatim whether or not it is the selected choice.

        :param settings: the ``QSettings`` to read from.
        """
        settings.beginGroup(GROUP)
        self.use_custom_extensions = cast(bool, settings.value(USE_CUSTOM_EXTENSIONS_KEY, False, type=bool))
        self.custom_extensions = cast(str, settings.value(CUSTOM_EXTENSIONS_KEY, "", type=str))
        settings.endGroup()

    def save(self, settings: QSettings) -> None:
        """Save both stored fields to persistent storage -- the custom list verbatim, selected or not.

        :param settings: the ``QSettings`` to write to.
        """
        settings.beginGroup(GROUP)
        settings.setValue(USE_CUSTOM_EXTENSIONS_KEY, self.use_custom_extensions)
        settings.setValue(CUSTOM_EXTENSIONS_KEY, self.custom_extensions)
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
