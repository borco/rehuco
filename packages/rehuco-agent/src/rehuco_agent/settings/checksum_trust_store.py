"""Where the shared checksum trust cache lives (#358).

`rehuco_core.ChecksumTrust` never reads a setting, so the file it tracks is the agent's to supply
([[data-model#checksums]]).
"""

from pathlib import Path
from typing import Final

from .persistent_settings import config_folder

CHECKSUM_TRUST_FILENAME: Final = "checksum-trust.json"
"""What the trust cache is called, in the app's own config folder -- the same placement
:func:`~rehuco_agent.tasks.task_queue_store.task_queue_path` gives the saved task queue."""


def checksum_trust_path() -> Path:
    """Where the checksum trust cache lives: :func:`~.persistent_settings.config_folder`, not loose
    beside the ``.ini`` in the organization folder every borco app shares (#361).

    :returns: the cache file's path, whether or not it exists.
    """
    return config_folder() / CHECKSUM_TRUST_FILENAME
