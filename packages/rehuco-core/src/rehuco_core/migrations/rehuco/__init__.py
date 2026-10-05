"""``.rehuco`` file format migrations ([[data-model#local-file-trio]], #371).

The target for the machine-local roots file ``rehuco_core.rehuco_file`` reads and writes. Same shape as every
other target -- a ``BASE_VERSION``, a ``CHAIN``, a head derived from it -- stamped under the file's
``format_version``, the spelling a ``.rehu`` uses.

Version 1 was the first shape the file ever had; version 2 (#378) replaced a root's ``removable`` flag with a
``storage``. Every ``.rehuco`` already on disk comes up on read, the way a ``.rehu`` does.
"""

from typing import Final

from ..runner import Chain, chain_head, run
from . import v2_root_storage

BASE_VERSION: Final = 1
"""What an unstamped file resolves to -- there has only ever been a v1, so a file whose stamp is missing or
malformed is read as one rather than refused."""

CHAIN: Final[Chain] = ((v2_root_storage.VERSION, v2_root_storage.upgrade),)
"""This target's ordered ``(target, step)`` chain."""

CURRENT_VERSION: Final = chain_head(CHAIN, BASE_VERSION)
"""The newest ``.rehuco`` version this build understands -- the chain's head. Derived, never declared separately,
so it cannot drift from the steps that actually exist."""


def migrate_rehuco_data(data: dict) -> None:
    """Bring a parsed ``.rehuco`` payload up to :data:`CURRENT_VERSION`, in place.

    :param data: the parsed JSON object; mutated to the current layout and stamped. A stamp *above*
        :data:`CURRENT_VERSION` is left as it is (the runner never lowers one) -- what a newer file means is
        the reader's decision, made where the file is loaded.
    """
    run(data, CHAIN, base_version=BASE_VERSION)
