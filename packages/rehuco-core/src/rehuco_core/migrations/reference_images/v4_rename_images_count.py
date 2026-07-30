"""**reference_images block v3 -> v4**: rename ``images_count`` to ``current_count``
([[field-schema#field-mapping]], #198).

The count splits in two: ``advertised_count``, the pack's own claim (a string, since ``500+`` is a weaker
claim than ``500`` and storing it as an integer would silently strengthen it), and ``current_count``, what
counting the archives' entries actually finds ([[data-model#resource-scoping]]). The single stored number
was never a claim -- nothing but a scan or a hand edit ever wrote it -- so it becomes the *measured* half,
and the claim half starts absent on every existing file.

A rename in the **migration chain**, not in the editor: an old-field-to-known-field rename is applied on
load like ``author`` -> ``authors`` before it ([[data-model#schema-version]]), where a user mapping it by
hand would leave every unopened file carrying the old key.

Self-contained: both key names are frozen *here*, at v4, so a later rename of either never reaches back
into this step.
"""

from typing import Any

VERSION = 4
"""The version this step brings a ``reference_images`` block up to."""

# Frozen at v4 -- this migration's own copies, deliberately not imported from the live vocabulary.
OLD_KEY = "images_count"
NEW_KEY = "current_count"


def upgrade(block: dict[str, Any], _username: str) -> None:
    """Move :data:`OLD_KEY`'s value to :data:`NEW_KEY`, in place, whatever that value is.

    The value is carried **verbatim**, malformed included: a string where a whole number belongs still
    locks the document under the new name ([[data-model#write-integrity]]), where coercing it here would
    discard the very value the lock keeps recoverable.

    **Never overwrites.** A block already carrying :data:`NEW_KEY` is left exactly as it is, old key and
    all -- two counts written by two builds are not something this step can reconcile, and the stray one
    surfaces through the generic fallback with a drop button ([[plugins#fallback-editor]]) rather than
    silently replacing the value the newer build wrote.

    :param block: one v3 ``reference_images`` block's own fields; mutated in place.
    :param _username: unused -- the count is a shared block field, not per-user
        ([[field-schema#per-user-shared]]).
    """
    if OLD_KEY not in block or NEW_KEY in block:
        return
    block[NEW_KEY] = block.pop(OLD_KEY)
