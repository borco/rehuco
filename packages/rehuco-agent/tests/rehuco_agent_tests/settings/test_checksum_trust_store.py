"""Tests for `checksum_trust_path`: where the shared checksum trust cache lives (#358)."""

from pathlib import Path

from pytest_mock import MockerFixture
from rehuco_agent.settings import checksum_trust_store as store_module
from rehuco_agent.settings.checksum_trust_store import CHECKSUM_TRUST_FILENAME, checksum_trust_path


def test_the_trust_cache_sits_beside_the_settings_file(mocker: MockerFixture) -> None:
    """`checksum_trust_path` names a file in the settings file's own directory, the same placement
    `task_queue_path` gives the saved task queue.
    """
    settings = mocker.Mock()
    settings.fileName.return_value = str(Path.cwd() / "fake" / "rehuco-agent.ini")
    mocker.patch.object(store_module, "persistent_settings", return_value=settings)

    assert checksum_trust_path() == Path.cwd() / "fake" / CHECKSUM_TRUST_FILENAME
