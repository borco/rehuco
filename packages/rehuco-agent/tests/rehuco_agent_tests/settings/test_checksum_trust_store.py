"""Tests for `checksum_trust_path`: where the shared checksum trust cache lives (#358)."""

from rehuco_agent.settings.checksum_trust_store import CHECKSUM_TRUST_FILENAME, checksum_trust_path
from rehuco_agent.settings.persistent_settings import config_folder


def test_the_trust_cache_sits_in_the_app_config_folder() -> None:
    """`checksum_trust_path` names a file in the app's own config folder -- the same placement
    `task_queue_path` gives the saved task queue (#361, #412).
    """
    assert checksum_trust_path() == config_folder() / CHECKSUM_TRUST_FILENAME
