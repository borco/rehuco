"""Tests for the username a fresh install files its own edits under ([[field-schema#per-user-shared]], #412)."""

from pytest_mock import MockerFixture
from rehuco_core import DEFAULT_CURRENT_USERNAME, default_username


def test_the_default_username_is_the_os_login(mocker: MockerFixture) -> None:
    """The OS login name, when the platform can produce one.

    **Test steps:**

    * make ``getpass.getuser`` answer a known name
    * verify the default is that name
    """
    mocker.patch("getpass.getuser", return_value="alice")

    assert default_username() == "alice"


def test_the_default_username_falls_back_when_the_platform_has_none(mocker: MockerFixture) -> None:
    """With no usable environment or password entry, ``getpass`` raises; the default is ``admin`` instead.

    **Test steps:**

    * make ``getpass.getuser`` raise ``OSError``
    * verify the default is :data:`~rehuco_core.DEFAULT_CURRENT_USERNAME`
    """
    mocker.patch("getpass.getuser", side_effect=OSError)

    assert default_username() == DEFAULT_CURRENT_USERNAME
