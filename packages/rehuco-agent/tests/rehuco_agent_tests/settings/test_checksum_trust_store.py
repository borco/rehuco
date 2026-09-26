"""Tests for `checksum_trust_path`: where the shared checksum trust cache lives (#358)."""

from pathlib import Path

from pytest_mock import MockerFixture
from rehuco_agent.settings import persistent_settings as persistent_settings_module
from rehuco_agent.settings.checksum_trust_store import CHECKSUM_TRUST_FILENAME, checksum_trust_path
from rehuco_agent.settings.persistent_settings import APPLICATION_NAME


def test_the_trust_cache_sits_in_the_app_config_folder(mocker: MockerFixture) -> None:
    """`checksum_trust_path` names a file in the app's own config folder -- the same placement
    `task_queue_path` gives the saved task queue, and not loose in the organization folder every borco
    app shares (#361).
    """
    settings = mocker.Mock()
    settings.fileName.return_value = str(Path.cwd() / "fake" / "rehuco-agent.ini")
    mocker.patch.object(persistent_settings_module, "persistent_settings", return_value=settings)

    assert checksum_trust_path() == Path.cwd() / "fake" / APPLICATION_NAME / CHECKSUM_TRUST_FILENAME
