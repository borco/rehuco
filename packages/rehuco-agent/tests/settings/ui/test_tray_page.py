"""Tests for TrayPage: the Tray settings category page (#47, #76, #205)."""

from typing import Any

from PySide6.QtWidgets import QSystemTrayIcon
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.settings import tray_settings
from rehuco_agent.settings.tray_settings import shared_tray_settings
from rehuco_agent.settings.ui import tray_page
from rehuco_agent.settings.ui.tray_page import TrayPage


# region fixtures
# Mirrors test_descriptions_page.py's FakeSettings exactly -- kept as a separate copy rather than a
# shared import, matching this codebase's settings-test convention.
# pylint: disable=duplicate-code
class FakeSettings:  # pylint: disable=invalid-name,missing-function-docstring,redefined-builtin
    """A minimal in-memory stand-in for the ``QSettings`` group/value API."""

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
    (used by :func:`shared_tray_settings`'s lazy load) and the page module itself (used by
    :meth:`TrayPage.save_changes`).
    """
    fake = FakeSettings()
    mocker.patch.object(tray_settings, "persistent_settings", return_value=fake)
    mocker.patch.object(tray_page, "persistent_settings", return_value=fake)
    return fake


# endregion


def test_starts_with_the_shared_settings_current_value(qtbot: QtBot) -> None:
    """A freshly-built page's checkbox reflects the shared settings' current value.

    **Test steps:**

    * seed the shared settings ``enabled``
    * build the page
    * verify the checkbox is checked
    """
    shared_tray_settings().enabled = True

    page = TrayPage()
    qtbot.addWidget(page)

    ui = page._TrayPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert ui.enabled_check_box.isChecked() is True


def test_is_dirty_is_false_right_after_construction(qtbot: QtBot) -> None:
    """A freshly-built page (nothing edited yet) is not dirty.

    **Test steps:**

    * build the page
    * verify ``is_dirty`` is ``False``
    """
    page = TrayPage()
    qtbot.addWidget(page)

    assert page.is_dirty() is False


def test_is_dirty_is_true_after_toggling_the_checkbox(qtbot: QtBot) -> None:
    """Toggling the checkbox makes the page dirty.

    **Test steps:**

    * build the page and check the box
    * verify ``is_dirty`` is ``True``
    """
    page = TrayPage()
    qtbot.addWidget(page)
    ui = page._TrayPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access

    ui.enabled_check_box.setChecked(True)

    assert page.is_dirty() is True


def test_save_changes_updates_the_shared_settings_and_persists(
    qtbot: QtBot, fake_persistent_settings: FakeSettings
) -> None:
    """``save_changes`` pushes the staged checkbox into the shared settings object and persists it.

    **Test steps:**

    * build the page and check the box
    * call ``save_changes``
    * verify the shared settings object reflects the change
    * verify a fresh load from the persisted store reflects it too
    """
    page = TrayPage()
    qtbot.addWidget(page)
    ui = page._TrayPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access
    ui.enabled_check_box.setChecked(True)

    page.save_changes()

    settings = shared_tray_settings()
    assert settings.enabled is True

    reloaded = type(settings)()
    reloaded.load(fake_persistent_settings)  # type: ignore[arg-type]
    assert reloaded.enabled is True


def test_save_changes_clears_dirty(qtbot: QtBot) -> None:
    """After ``save_changes``, the page is no longer dirty.

    **Test steps:**

    * build the page, check the box, save
    * verify ``is_dirty`` is now ``False``
    """
    page = TrayPage()
    qtbot.addWidget(page)
    ui = page._TrayPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access
    ui.enabled_check_box.setChecked(True)

    page.save_changes()

    assert page.is_dirty() is False


def test_drop_changes_reverts_the_checkbox(qtbot: QtBot) -> None:
    """``drop_changes`` reverts the checkbox back to the shared settings' current value.

    **Test steps:**

    * build the page and check the box
    * call ``drop_changes``
    * verify the checkbox is back to the (unsaved, still-default) shared settings value
    """
    page = TrayPage()
    qtbot.addWidget(page)
    ui = page._TrayPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access
    ui.enabled_check_box.setChecked(True)

    page.drop_changes()

    assert ui.enabled_check_box.isChecked() is False
    assert page.is_dirty() is False


def test_title_is_tray(qtbot: QtBot) -> None:
    """The page's category-tree title is "Tray" (#76).

    **Test steps:**

    * construct the page
    * verify ``title``
    """
    page = TrayPage()
    qtbot.addWidget(page)

    assert page.title == "Tray"


def test_unavailable_label_hidden_when_a_tray_is_available(qtbot: QtBot, mocker: MockerFixture) -> None:
    """The "no system tray" note is hidden when a tray is actually available.

    **Test steps:**

    * mock tray availability as ``True``
    * build the page
    * verify the note is hidden
    """
    mocker.patch.object(QSystemTrayIcon, "isSystemTrayAvailable", return_value=True)

    page = TrayPage()
    qtbot.addWidget(page)

    ui = page._TrayPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert ui.unavailable_label.isHidden() is True


def test_unavailable_label_shown_when_no_tray_is_available(qtbot: QtBot, mocker: MockerFixture) -> None:
    """The "no system tray" note is shown when no tray is available (bare Linux sessions, chiefly).

    **Test steps:**

    * mock tray availability as ``False``
    * build the page
    * verify the note is not hidden
    """
    mocker.patch.object(QSystemTrayIcon, "isSystemTrayAvailable", return_value=False)

    page = TrayPage()
    qtbot.addWidget(page)

    ui = page._TrayPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert ui.unavailable_label.isHidden() is False
