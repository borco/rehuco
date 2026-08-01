"""The one rule an editable file-extension list is read under (#222, #225).

Two settings sections hold a list of extensions the user may change -- which archive entries count as a
reference-images resource's images (`ReferenceImagesSettings`) and which files a tutorial's duration scan
measures (`VideosSettings`) -- and both are read under exactly the same rule: a leading dot is optional,
case does not matter, blanks and repeats go, and a list naming nothing at all resolves to whatever that
section ships rather than to *no recognized formats*. Only the fallback set differs, which is a parameter.

Deliberately not next to :func:`~rehuco_agent.settings.persistent_settings.read_stored_strings`, which
this builds on: that one allows for the *storage backend's* behaviour and applies no policy, while this
is the policy -- and one an excluded-*pattern* list, matched verbatim, must not be given
([[appendices.settings-pages#persisting-changes]]).
"""

from .persistent_settings import read_stored_strings


def normalize_extensions(value: object, defaults: tuple[str, ...]) -> tuple[str, ...]:
    """Normalize an extension list into the form an enumeration matches against.

    Surrounding whitespace is ignored and a leading dot is optional, so ``mp4``, ``.mp4`` and ``  MP4 ``
    all mean the same entry: every entry normalizes to lower case with exactly one leading dot. Empty
    entries and duplicates are dropped rather than rejected, keeping a blank row or a repeated format
    from being an error the user has to fix.

    A value naming no usable entry at all -- absent, empty, of a type a list was never stored as, or
    nothing but whitespace and bare dots -- falls back to ``defaults``: a list left empty must not
    silently make every scan find nothing.

    :param value: the raw stored value, or the entries as edited.
    :param defaults: the shipped set to fall back to when ``value`` names no usable entry.
    :returns: the recognized extensions, lower-cased and dot-prefixed, in the order first seen, or
        ``defaults`` when there are none.
    """
    extensions: list[str] = []
    for entry in read_stored_strings(value):
        stem = entry.strip().lstrip(".").lower()
        if not stem:
            continue
        extension = f".{stem}"
        if extension not in extensions:
            extensions.append(extension)
    return tuple(extensions) or defaults
