"""``.checksum`` record format migrations ([[data-model#checksums]], #203).

The target for the verification record ``rehuco_core.checksum_record`` reads and writes. Same shape as
every other target -- a ``BASE_VERSION``, a ``CHAIN``, a head derived from it -- with one spelling of its
own: the record stamps ``version`` rather than ``format_version``, because it is a whole file, not a block
inside one, and the format the issue fixed spells it so. The runner takes the key as a parameter for
exactly this chain.

The chain is empty today: version 1 is the first shape the record ever had, so there is nothing to climb
from. The hook exists so the day the shape changes, the step goes here and every record already on disk
comes up on read, the way a ``.rehu`` does.
"""

from typing import Final

from ..runner import Chain, chain_head, run

BASE_VERSION: Final = 1
"""What an unstamped record resolves to -- there has only ever been a v1, so a record whose stamp is
missing or malformed is read as one rather than refused ([[data-model#checksums]])."""

CHAIN: Final[Chain] = ()
"""This target's ordered ``(target, step)`` chain -- empty, because v1 is the first shape."""

CURRENT_VERSION: Final = chain_head(CHAIN, BASE_VERSION)
"""The newest record version this build understands -- the chain's head, or the base while the chain is
empty. Derived, never declared separately, so it cannot drift from the steps that actually exist."""

VERSION_KEY: Final = "version"
"""The record's own version stamp spelling (#203) -- deliberately not ``format_version``: the record is
a whole file with a top-level stamp, and this is the spelling the format fixed."""


def migrate_checksum_data(data: dict) -> None:
    """Bring a parsed ``.checksum`` record up to :data:`CURRENT_VERSION`, in place.

    :param data: the parsed JSON object; mutated to the current layout and stamped. A stamp *above*
        :data:`CURRENT_VERSION` is left as it is (the runner never lowers one) -- refusing it is the
        reader's decision, made where the record is loaded.
    """
    run(data, CHAIN, base_version=BASE_VERSION, version_key=VERSION_KEY)
