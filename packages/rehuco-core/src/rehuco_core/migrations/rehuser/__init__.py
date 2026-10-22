"""``.rehuser`` per-user sidecar format migrations ([[data-model#single-file]], #513).

The target for the sidecar :mod:`rehuco_core.user_sidecars` reads and writes. Same shape as every other target -- a
``BASE_VERSION``, a ``CHAIN``, a head derived from it -- stamped under the file's ``format_version``, the spelling a
``.rehu`` uses.

The chain is empty today: version 1 -- a JSON object of ``block key -> that user's fields`` -- is the first shape the
sidecar ever had. The hook exists so the day the shape changes, the step goes here and every sidecar already on disk
comes up on read, the way a ``.rehu`` does.
"""

from typing import Final

from ..runner import Chain, chain_head, run

BASE_VERSION: Final = 1
"""What an unstamped sidecar resolves to -- there has only ever been a v1, so one whose stamp is missing or malformed is
read as one rather than refused."""

CHAIN: Final[Chain] = ()
"""This target's ordered ``(target, step)`` chain -- empty, because v1 is the first shape."""

CURRENT_VERSION: Final = chain_head(CHAIN, BASE_VERSION)
"""The newest sidecar version this build understands -- the chain's head, or the base while the chain is empty. Derived,
never declared separately, so it cannot drift from the steps that actually exist."""


def migrate_rehuser_data(data: dict) -> None:
    """Bring a parsed ``.rehuser`` payload up to :data:`CURRENT_VERSION`, in place.

    :param data: the parsed JSON object; mutated to the current layout and stamped. A stamp *above*
        :data:`CURRENT_VERSION` is left as it is (the runner never lowers one) -- refusing it is the reader's decision,
        made where the sidecar is loaded.
    """
    run(data, CHAIN, base_version=BASE_VERSION)
