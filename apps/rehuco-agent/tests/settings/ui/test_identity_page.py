"""Tests for IdentityPage: the Identity settings category page (#99)."""

from collections.abc import Iterator
from typing import Any

from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.settings import identity_settings
from rehuco_agent.settings.identity_settings import IdentitySettings, shared_identity_settings
from rehuco_agent.settings.ui import identity_page
from rehuco_agent.settings.ui.identity_page import IdentityPage
from rehuco_agent.settings.ui.settings_frame_filter import SettingsFrameFilter


# region fixtures
# Mirrors test_identity_settings.py's (and conftest.py's) FakeSettings exactly -- kept as a
# separate copy rather than a shared import, matching this codebase's settings-test convention.
# pylint: disable=duplicate-code
class FakeSettings:  # pylint: disable=invalid-name,missing-function-docstring,redefined-builtin
    """A minimal in-memory stand-in for the ``QSettings`` group/value API (see
    ``test_identity_settings.py`` for the full rationale)."""

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


# pylint: enable=duplicate-code


@fixture(autouse=True)
def fake_persistent_settings(mocker: MockerFixture) -> FakeSettings:
    """Stand in for ``persistent_settings()`` so save/load never touch real storage.

    Patched on both modules that imported their own reference to it: the shared settings module
    (used by :func:`shared_identity_settings`'s lazy load) and the page module itself (used by
    :meth:`IdentityPage.save_changes`).
    """
    fake = FakeSettings()
    mocker.patch.object(identity_settings, "persistent_settings", return_value=fake)
    mocker.patch.object(identity_page, "persistent_settings", return_value=fake)
    return fake


@fixture(autouse=True)
def clear_shared_instance_cache() -> Iterator[None]:
    """Clear the shared settings singleton before and after every test (see
    ``test_markdown_rendering_settings.py`` for the full rationale)."""
    shared_identity_settings.cache_clear()
    yield
    shared_identity_settings.cache_clear()


# endregion


def test_starts_with_the_shared_settings_current_username(qtbot: QtBot) -> None:
    """A freshly-built page's field reflects the shared settings' current username.

    **Test steps:**

    * seed the shared settings with a known username
    * build the page
    * verify the field shows it
    """
    shared_identity_settings().username = "alice"

    page = IdentityPage()
    qtbot.addWidget(page)

    ui = page._IdentityPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert ui.username_edit.text() == "alice"


def test_is_dirty_is_false_right_after_construction(qtbot: QtBot) -> None:
    """A freshly-built page (nothing edited yet) is not dirty.

    **Test steps:**

    * build the page
    * verify ``is_dirty`` is ``False``
    """
    page = IdentityPage()
    qtbot.addWidget(page)

    assert page.is_dirty() is False


def test_is_dirty_is_true_after_an_edit(qtbot: QtBot) -> None:
    """Editing the username makes the page dirty.

    **Test steps:**

    * build the page and change the username field
    * verify ``is_dirty`` is ``True``
    """
    page = IdentityPage()
    qtbot.addWidget(page)
    ui = page._IdentityPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access

    ui.username_edit.setText("alice")

    assert page.is_dirty() is True


def test_save_changes_updates_the_shared_settings_and_persists(
    qtbot: QtBot, fake_persistent_settings: FakeSettings
) -> None:
    """``save_changes`` pushes the staged username into the shared settings object and persists it.

    **Test steps:**

    * build the page and edit the username
    * call ``save_changes``
    * verify the shared settings object reflects it, cleared dirty, and a fresh load does too
    """
    page = IdentityPage()
    qtbot.addWidget(page)
    ui = page._IdentityPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access
    ui.username_edit.setText("alice")

    page.save_changes()

    assert shared_identity_settings().username == "alice"
    assert page.is_dirty() is False

    reloaded = IdentitySettings()
    reloaded.load(fake_persistent_settings)  # type: ignore[arg-type]
    assert reloaded.username == "alice"


def test_a_blank_staged_username_saves_as_the_os_login_default(qtbot: QtBot, mocker: MockerFixture) -> None:
    """A blank (whitespace-only) staged username stands for "no name" and saves as the OS-login
    default instead -- an identity is never saved empty ([[field-schema#per-user-shared]]).

    **Test steps:**

    * build the page, blank the field, and save
    * verify the shared settings hold the (mocked) OS login name
    """
    mocker.patch("getpass.getuser", return_value="alice")
    page = IdentityPage()
    qtbot.addWidget(page)
    ui = page._IdentityPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access
    ui.username_edit.setText("   ")

    page.save_changes()

    assert shared_identity_settings().username == "alice"


def test_drop_changes_reverts_the_edit(qtbot: QtBot) -> None:
    """``drop_changes`` reverts the field back to the shared settings' current username.

    **Test steps:**

    * seed the shared settings, build the page, and edit the field
    * call ``drop_changes``
    * verify the field is back to the shared settings' value and the page is clean
    """
    shared_identity_settings().username = "alice"
    page = IdentityPage()
    qtbot.addWidget(page)
    ui = page._IdentityPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access
    ui.username_edit.setText("unsaved-edit")

    page.drop_changes()

    assert ui.username_edit.text() == "alice"
    assert page.is_dirty() is False


def test_title_is_identity(qtbot: QtBot) -> None:
    """The page's category-tree title is "Identity".

    **Test steps:**

    * construct the page
    * verify ``title``
    """
    page = IdentityPage()
    qtbot.addWidget(page)

    assert page.title == "Identity"


def test_frame_filter_discovers_the_pages_frame_and_its_text(qtbot: QtBot) -> None:
    """A `SettingsFrameFilter` finds the page's labeled frame and filters it by its text (#67).

    Guards the page's ``.ui`` frame structure: the identity frame must be a discoverable top-level
    frame whose gathered caption text (including the "Username" field label) drives the filter.

    **Test steps:**

    * build a frame filter over the page, then filter by the username label's text
    * verify the identity frame stays shown; filter by a non-matching term and verify it hides
    """
    page = IdentityPage()
    qtbot.addWidget(page)
    frame_filter = SettingsFrameFilter(page, page.title)
    ui = page._IdentityPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access

    frame_filter.apply("username", show_full_on_title_match=False)
    assert ui.identity_frame.isVisibleTo(page) is True

    frame_filter.apply("no-such-term", show_full_on_title_match=False)
    assert ui.identity_frame.isVisibleTo(page) is False
