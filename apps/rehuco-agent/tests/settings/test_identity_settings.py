"""Tests for IdentitySettings: the persisted username per-user state is filed under (#99).

Uses a hand-rolled in-memory stand-in for ``QSettings`` (see ``test_main_window_settings.py`` for
the same rationale) rather than a real one or ``tmp_path``.
"""

from collections.abc import Iterator
from typing import Any

from pytest import fixture
from pytest_mock import MockerFixture
from rehuco_agent.settings import identity_settings
from rehuco_agent.settings.identity_settings import IdentitySettings, default_username, shared_identity_settings


# region fixtures
# Mirrors every other settings test's FakeSettings exactly -- kept as a separate copy rather than a
# shared import, matching this codebase's settings-test convention.
# pylint: disable=duplicate-code
class FakeSettings:  # pylint: disable=invalid-name,missing-function-docstring,redefined-builtin
    """A minimal in-memory stand-in for the ``QSettings`` group/value API.

    Method names and the ``type=`` parameter deliberately mirror ``QSettings``'s own C++-derived
    API, since :meth:`IdentitySettings.load`/:meth:`~IdentitySettings.save` call them by name.
    """

    def __init__(self) -> None:
        self.__data: dict[str, Any] = {}
        self.__group = ""

    def beginGroup(self, name: str) -> None:  # noqa: N802
        self.__group = f"{name}/"

    def endGroup(self) -> None:  # noqa: N802
        self.__group = ""

    def setValue(self, key: str, value: Any) -> None:  # noqa: N802
        self.__data[self.__group + key] = value

    def value(self, key: str, default: Any = None, type: Any = None) -> Any:  # noqa: A002, N802
        del type
        return self.__data.get(self.__group + key, default)


@fixture
def settings() -> FakeSettings:
    """A fresh in-memory settings stand-in."""
    return FakeSettings()


# pylint: enable=duplicate-code


@fixture(autouse=True)
def clear_shared_instance_cache() -> Iterator[None]:
    """Clear the ``lru_cache``-backed singleton before and after every test (see
    ``test_markdown_rendering_settings.py`` for the full rationale)."""
    shared_identity_settings.cache_clear()
    yield
    shared_identity_settings.cache_clear()


# endregion


def test_default_username_is_the_os_login_name(mocker: MockerFixture) -> None:
    """``default_username`` reads the OS login name ([[field-schema#per-user-shared]]'s seeding rule).

    **Test steps:**

    * mock ``getpass.getuser`` to return a known name
    * verify ``default_username`` returns it
    """
    mocker.patch("getpass.getuser", return_value="alice")

    assert default_username() == "alice"


def test_default_username_falls_back_to_admin_when_the_os_has_no_login_name(mocker: MockerFixture) -> None:
    """When the platform can't produce a login name, the default falls back to core's
    ``DEFAULT_USERNAME`` (``admin``) rather than raising.

    **Test steps:**

    * mock ``getpass.getuser`` to raise ``OSError`` (what it does with no usable env/passwd entry)
    * verify ``default_username`` returns ``admin``
    """
    mocker.patch("getpass.getuser", side_effect=OSError)

    assert default_username() == "admin"


def test_save_then_load_round_trips_the_username(settings: FakeSettings) -> None:
    """Saving and reloading reproduces the same username.

    **Test steps:**

    * set a username and save
    * load into a fresh instance from the same settings stand-in
    * verify the username came back unchanged
    """
    identity = IdentitySettings(username="alice")

    identity.save(settings)  # type: ignore[arg-type]

    restored = IdentitySettings()
    restored.load(settings)  # type: ignore[arg-type]

    assert restored.username == "alice"


def test_load_defaults_to_the_os_login_name_when_nothing_was_saved(
    settings: FakeSettings, mocker: MockerFixture
) -> None:
    """Loading from settings that never had a username saved yields the OS login name.

    **Test steps:**

    * mock the OS login name and load from an empty settings stand-in
    * verify the username is the OS login name
    """
    mocker.patch("getpass.getuser", return_value="alice")
    identity = IdentitySettings()

    identity.load(settings)  # type: ignore[arg-type]

    assert identity.username == "alice"


def test_load_treats_a_blank_stored_username_as_unset(settings: FakeSettings, mocker: MockerFixture) -> None:
    """A stored username that is blank (nothing but whitespace) falls back to the OS login name --
    per-user state must always be filed under *some* name ([[field-schema#per-user-shared]]).

    **Test steps:**

    * store a whitespace-only username, mock the OS login name, and load
    * verify the username fell back to the OS login name
    """
    settings.setValue("identity/username", "   ")
    mocker.patch("getpass.getuser", return_value="alice")
    identity = IdentitySettings()

    identity.load(settings)  # type: ignore[arg-type]

    assert identity.username == "alice"


def test_shared_instance_is_the_same_object_across_calls(mocker: MockerFixture) -> None:
    """``shared_identity_settings`` returns the identical instance every call.

    **Test steps:**

    * mock ``persistent_settings`` so the first call's ``load`` doesn't touch real storage
    * call the accessor twice
    * verify both calls return the same object
    """
    mocker.patch.object(identity_settings, "persistent_settings", return_value=FakeSettings())

    first = shared_identity_settings()
    second = shared_identity_settings()

    assert first is second


def test_shared_instance_loads_from_persistent_settings_on_first_call(mocker: MockerFixture) -> None:
    """``shared_identity_settings`` loads its value from ``persistent_settings()`` the first time
    it's constructed.

    **Test steps:**

    * pre-populate a fake settings store and mock ``persistent_settings`` to return it
    * call the accessor
    * verify the returned instance reflects the pre-populated username
    """
    fake = FakeSettings()
    IdentitySettings(username="alice").save(fake)  # type: ignore[arg-type]
    mocker.patch.object(identity_settings, "persistent_settings", return_value=fake)

    instance = shared_identity_settings()

    assert instance.username == "alice"
