"""**file v1 -> v2**: nest the top-level common fields under the ``core`` block
([[data-model#rehu-format]]).

**Self-contained.** It inlines the ``core`` key and the frozen v1 common-field set, importing nothing from
the live vocabulary -- the same historical-record discipline every migration follows.

**Keeps its shape guards**, unlike a block step. The file's v0 (an unstamped payload) is ambiguous: the
runner resolves it to v1 by shape, so this step runs -- but a payload that *already* has a ``core`` block
is a self-contradictory v2-without-a-stamp, which this step must decline rather than mangle (it *creates*
``core``; folding into an existing one would drop a v1-named ``core`` block on the floor). A flat payload
with nothing to move simply gains no block.
"""

from typing import Any

VERSION = 2
"""The version this step brings the file up to."""

# Frozen at v2 and inlined -- not imported. The live core-block key is `rehu_format.CORE_BLOCK_KEY`; this
# step keeps its own copy so a future rename of the core block never rewrites what v1->v2 did.
CORE_BLOCK_KEY = "core"
V1_COMMON_FIELD_KEYS = frozenset(
    {
        "type",
        "id",
        "sources",
        "authors",
        "released",
        "created",
        "updated",
        "description",
        "advertised_tags",
        "extra_tags",
        "original_size",
        "current_size",
        "hidden_images",
    }
)


def upgrade(data: dict[str, Any], _username: str) -> None:
    """Move the top-level common fields into a fresh ``core`` block, in place.

    :param data: the parsed file object; mutated in place.
    :param _username: unused -- the file-wide migration owns no per-user state.
    """
    if CORE_BLOCK_KEY in data:
        return
    moved = {key: value for key, value in data.items() if key in V1_COMMON_FIELD_KEYS}
    if not moved:
        return
    for key in moved:
        del data[key]
    data[CORE_BLOCK_KEY] = moved
