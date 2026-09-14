"""Tests for DocksPage: the Docks settings category page (#279)."""

from collections.abc import Iterator
from typing import Any

from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.settings import docks_settings
from rehuco_agent.settings.docks_settings import (
    DEFAULT_PIN_SIDE,
    GROUP,
    PIN_SIDE_KEY,
    SIDE_LABELS,
    DockPinSide,
    shared_docks_settings,
)
from rehuco_agent.settings.ui import docks_page
from rehuco_agent.settings.ui.docks_page import DocksPage
from rehuco_agent.settings.ui.settings_page import SettingsPage


# region fixtures
# Mirrors test_logs_page.py's (and conftest.py's) FakeSettings exactly -- kept as a separate copy
# rather than a shared import, matching this codebase's settings-test convention.
# pylint: disable=duplicate-code
class FakeSettings:  # pylint: disable=invalid-name,missing-function-docstring,redefined-builtin
    """A minimal in-memory stand-in for the ``QSettings`` group/value API (see
    ``test_docks_settings.py`` for the full rationale)."""

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
def fake_persistent_settings(mocker: MockerFixture) -> Iterator[FakeSettings]:
    """Stand in for ``persistent_settings()`` so save/load never touch real storage.

    Patched in both modules that reach for it -- the page (which persists on save) and the settings
    section (which the shared instance loads through) -- and the shared instance is dropped either
    side, so neither this test's values nor another's leak.

    :returns: the stand-in both modules see.
    """
    fake = FakeSettings()
    shared_docks_settings.cache_clear()
    mocker.patch.object(docks_page, "persistent_settings", return_value=fake)
    mocker.patch.object(docks_settings, "persistent_settings", return_value=fake)
    yield fake
    shared_docks_settings.cache_clear()


@fixture
def page(qtbot: QtBot) -> DocksPage:
    """Provide a page seeded from the (empty) fake storage.

    :param qtbot: pytest-qt bot.
    :returns: the page.
    """
    docks_settings_page = DocksPage()
    qtbot.addWidget(docks_settings_page)
    return docks_settings_page


def ui(page: DocksPage) -> Any:
    """Reach a page's generated UI object.

    :param page: the page to read.
    :returns: the UI object.
    """
    return page._DocksPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access


# endregion


# region the page contract


def test_satisfies_the_settings_page_protocol(page: DocksPage) -> None:
    """It is a settings page in the structural sense the dialog registers.

    **Test steps:**

    * Assert the page satisfies `SettingsPage`.
    """
    assert isinstance(page, SettingsPage)


def test_offers_every_side(page: DocksPage) -> None:
    """The combo box is built from the sides themselves, so all four are reachable.

    **Test steps:**

    * Assert the combo box holds one item per `DockPinSide`, with that side as its data.
    """
    combo = ui(page).pin_side_combo_box

    sides = [combo.itemData(index) for index in range(combo.count())]

    assert sides == list(SIDE_LABELS)


def test_starts_showing_the_saved_side(page: DocksPage) -> None:
    """A freshly opened page shows the side the docks are actually pinning to.

    **Test steps:**

    * Assert the combo box holds the default from empty storage.
    """
    assert ui(page).pin_side_combo_box.currentData() == DEFAULT_PIN_SIDE


def test_is_clean_until_a_side_is_picked(page: DocksPage) -> None:
    """Nothing staged is nothing to save.

    **Test steps:**

    * Assert the page is not dirty.
    """
    assert not page.is_dirty()


def test_reports_a_different_side_as_dirty(page: DocksPage) -> None:
    """A picked side is a staged change.

    **Test steps:**

    * Pick a side other than the saved one.
    * Assert the page is dirty.
    """
    ui(page).pin_side_combo_box.setCurrentIndex(list(SIDE_LABELS).index(DockPinSide.RIGHT))

    assert page.is_dirty()


# endregion


# region saving and dropping


def test_saving_pushes_the_side_into_the_shared_settings(page: DocksPage) -> None:
    """Save is what every open dock re-points off -- so it lands on the shared object.

    **Test steps:**

    * Pick the bottom side and save.
    * Assert the shared settings hold it, and the page is clean again.
    """
    ui(page).pin_side_combo_box.setCurrentIndex(list(SIDE_LABELS).index(DockPinSide.BOTTOM))

    page.save_changes()

    assert shared_docks_settings().pin_side == DockPinSide.BOTTOM
    assert not page.is_dirty()


def test_saving_persists_the_side(page: DocksPage, fake_persistent_settings: FakeSettings) -> None:
    """Save reaches storage, not only the shared object -- the next launch reads the same side.

    **Test steps:**

    * Pick the top side and save.
    * Assert the stored value is that side's own word.
    """
    ui(page).pin_side_combo_box.setCurrentIndex(list(SIDE_LABELS).index(DockPinSide.TOP))

    page.save_changes()

    assert fake_persistent_settings.value(f"{GROUP}/{PIN_SIDE_KEY}") == DockPinSide.TOP.value


def test_dropping_re_seeds_from_the_shared_settings(page: DocksPage) -> None:
    """Reset puts back what is actually in force, discarding the staged pick.

    **Test steps:**

    * Pick a side other than the saved one.
    * Drop the changes.
    * Assert the combo box shows the saved side again, and the page is clean.
    """
    ui(page).pin_side_combo_box.setCurrentIndex(list(SIDE_LABELS).index(DockPinSide.RIGHT))

    page.drop_changes()

    assert ui(page).pin_side_combo_box.currentData() == DEFAULT_PIN_SIDE
    assert not page.is_dirty()


# endregion
