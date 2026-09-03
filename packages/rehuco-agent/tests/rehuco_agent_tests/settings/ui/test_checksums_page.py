"""Tests for ChecksumsPage: the Checksums settings category page (#242)."""

from collections.abc import Iterator
from typing import Any

from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.settings import checksum_settings as checksum_settings_module
from rehuco_agent.settings.checksum_settings import ChecksumSettings, shared_checksum_settings
from rehuco_agent.settings.ui import checksums_page
from rehuco_agent.settings.ui.checksums_page import ChecksumsPage
from rehuco_agent.settings.ui.settings_page import SettingsPage
from rehuco_core import CHECKSUM_ALGORITHMS, DEFAULT_CHECKSUM_ALGORITHM


# region fixtures
# Mirrors test_tasks_page.py's FakeSettings exactly -- kept as a separate copy, matching this
# codebase's settings-test convention.
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
def fake_persistent_settings(mocker: MockerFixture) -> Iterator[FakeSettings]:
    """Stand in for ``persistent_settings()`` so save/load never touch real storage.

    Patched in both modules that read it: the page's own, and the settings module behind the shared
    instance the page's Save writes onto.

    :returns: the stand-in both see.
    """
    fake = FakeSettings()
    mocker.patch.object(checksums_page, "persistent_settings", return_value=fake)
    mocker.patch.object(checksum_settings_module, "persistent_settings", return_value=fake)
    shared_checksum_settings.cache_clear()
    yield fake
    shared_checksum_settings.cache_clear()


@fixture
def page(qtbot: QtBot) -> ChecksumsPage:
    """Provide a page seeded from the (empty) fake storage.

    :param qtbot: pytest-qt bot.
    :returns: the page.
    """
    built = ChecksumsPage()
    qtbot.addWidget(built)
    return built


def ui(page: ChecksumsPage) -> Any:
    """Reach a page's generated UI object.

    :param page: the page to read.
    :returns: the UI object.
    """
    return page._ChecksumsPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access


def algorithm_buttons(page: ChecksumsPage) -> list[Any]:
    """The algorithm radios, in the order they were built.

    :param page: the page to read.
    :returns: the radio buttons.
    """
    group = page._ChecksumsPage__algorithms  # type: ignore[attr-defined]  # pylint: disable=protected-access
    return [group.button(index) for index in range(len(CHECKSUM_ALGORITHMS))]


def check_algorithm(page: ChecksumsPage, name: str) -> None:
    """Select an algorithm the way clicking its radio would.

    :param page: the page to edit.
    :param name: the algorithm to select.
    """
    algorithm_buttons(page)[list(CHECKSUM_ALGORITHMS).index(name)].setChecked(True)


# endregion

# region the page contract


def test_satisfies_the_settings_page_protocol(page: ChecksumsPage) -> None:
    """It is a settings page in the structural sense the dialog registers.

    **Test steps:**

    * build the page
    * verify it satisfies the `SettingsPage` protocol and titles itself "Checksums"
    """
    assert isinstance(page, SettingsPage)
    assert page.title == "Checksums"


def test_a_fresh_page_is_not_dirty(page: ChecksumsPage) -> None:
    """Seeding from storage must not read as an edit, or Apply would always look available.

    **Test steps:**

    * build the page against empty storage
    * verify it reports nothing staged
    """
    assert not page.is_dirty()


# endregion

# region the algorithm radios


def test_there_is_one_radio_per_shipped_algorithm(page: ChecksumsPage) -> None:
    """Built from the core registry, so an algorithm added there is offerable without touching the ``.ui``.

    **Test steps:**

    * build the page
    * verify the radios' texts are exactly the registry's labels, in its order
    """
    assert [button.text() for button in algorithm_buttons(page)] == [
        algorithm.label for algorithm in CHECKSUM_ALGORITHMS.values()
    ]


def test_the_saved_algorithm_is_the_checked_one(page: ChecksumsPage, fake_persistent_settings: FakeSettings) -> None:
    """A page opened after a save must show what was saved, not the shipped default.

    **Test steps:**

    * save a non-default algorithm to storage and re-seed the page
    * verify that algorithm's radio is the checked one
    """
    ChecksumSettings(algorithm="crc32").save(fake_persistent_settings)  # pyright: ignore[reportArgumentType]

    page.drop_changes()

    checked = algorithm_buttons(page)[list(CHECKSUM_ALGORITHMS).index("crc32")]
    assert checked.isChecked()


def test_the_default_algorithm_is_checked_on_a_fresh_install(page: ChecksumsPage) -> None:
    """Nothing stored means the shipped default, which must be a *checked* radio rather than none.

    **Test steps:**

    * build the page against empty storage
    * verify the default algorithm's radio is checked
    """
    checked = algorithm_buttons(page)[list(CHECKSUM_ALGORITHMS).index(DEFAULT_CHECKSUM_ALGORITHM)]
    assert checked.isChecked()


# endregion

# region the migration label


def test_the_migration_checkbox_names_the_selected_algorithm(page: ChecksumsPage) -> None:
    """The label promises a specific migration, so it has to name the algorithm it would migrate to.

    **Test steps:**

    * build the page against empty storage
    * verify the checkbox names the default algorithm's label
    """
    expected = CHECKSUM_ALGORITHMS[DEFAULT_CHECKSUM_ALGORITHM].label
    assert ui(page).migrate_check_box.text() == f"Update checksums to {expected} on verify"


def test_the_migration_checkbox_follows_a_radio_change(page: ChecksumsPage) -> None:
    """A label naming the wrong algorithm after a change is worse than a vague one.

    **Test steps:**

    * select a different algorithm
    * verify the checkbox's text now names that one
    """
    check_algorithm(page, "crc32")

    assert ui(page).migrate_check_box.text() == f"Update checksums to {CHECKSUM_ALGORITHMS['crc32'].label} on verify"


# endregion

# region the staleness window


def test_the_window_offers_the_range_the_issue_specifies(page: ChecksumsPage) -> None:
    """0--1000 days, and a zero that says out loud what it means.

    **Test steps:**

    * read the spin box's range, suffix and special value
    * verify they match the specified window
    """
    spin_box = ui(page).stale_days_spin_box
    assert spin_box.minimum() == 0
    assert spin_box.maximum() == 1000
    assert spin_box.suffix() == " days"
    assert spin_box.specialValueText() == "Nothing is ever fresh"


# endregion

# region staging, saving and dropping


def test_every_control_stages_an_edit(page: ChecksumsPage) -> None:
    """Each of the four is compared against storage, so each on its own marks the page dirty.

    **Test steps:**

    * change one control at a time, dropping the edit in between
    * verify each change alone made the page dirty
    """
    for edit in (
        lambda: check_algorithm(page, "crc32"),
        lambda: ui(page).migrate_check_box.setChecked(True),
        lambda: ui(page).create_missing_check_box.setChecked(True),
        lambda: ui(page).stale_days_spin_box.setValue(7),
    ):
        edit()
        assert page.is_dirty()
        page.drop_changes()
        assert not page.is_dirty()


def test_saving_writes_both_storage_and_the_shared_instance(
    page: ChecksumsPage, fake_persistent_settings: FakeSettings
) -> None:
    """The shared object is what the next enqueued run reads, so a Save that only hit the ini would
    take effect on the next launch rather than the next run (#242).

    **Test steps:**

    * stage all four values and save
    * verify the shared instance carries them, and so does a settings object loaded from storage
    """
    check_algorithm(page, "crc32")
    ui(page).migrate_check_box.setChecked(True)
    ui(page).create_missing_check_box.setChecked(True)
    ui(page).stale_days_spin_box.setValue(7)

    page.save_changes()

    shared = shared_checksum_settings()
    stored = ChecksumSettings()
    stored.load(fake_persistent_settings)  # pyright: ignore[reportArgumentType]
    for settings in (shared, stored):
        assert settings.algorithm == "crc32"
        assert settings.migrate_on_verify
        assert settings.create_missing_on_verify
        assert settings.stale_days == 7


def test_saving_keeps_the_last_swept_folder(page: ChecksumsPage, fake_persistent_settings: FakeSettings) -> None:
    """No control here edits it, and the page must not drop what the sweep wrote (#242).

    **Test steps:**

    * record a swept folder on the shared instance
    * save the page
    * verify the folder survived, in the shared instance and in storage
    """
    shared_checksum_settings().last_sweep_root = "/fake/library"

    page.save_changes()

    stored = ChecksumSettings()
    stored.load(fake_persistent_settings)  # pyright: ignore[reportArgumentType]
    assert shared_checksum_settings().last_sweep_root == "/fake/library"
    assert stored.last_sweep_root == "/fake/library"


def test_dropping_reverts_every_control(page: ChecksumsPage, fake_persistent_settings: FakeSettings) -> None:
    """Including the migration label, which is text rather than a control's value.

    **Test steps:**

    * save a set of values, then stage different ones
    * drop the edits
    * verify every control, and the label, is back to what was saved
    """
    ChecksumSettings(algorithm="crc32", migrate_on_verify=True, stale_days=7).save(
        fake_persistent_settings  # pyright: ignore[reportArgumentType]
    )
    page.drop_changes()
    check_algorithm(page, DEFAULT_CHECKSUM_ALGORITHM)
    ui(page).migrate_check_box.setChecked(False)
    ui(page).stale_days_spin_box.setValue(365)

    page.drop_changes()

    assert not page.is_dirty()
    assert ui(page).stale_days_spin_box.value() == 7
    assert ui(page).migrate_check_box.isChecked()
    assert ui(page).migrate_check_box.text() == f"Update checksums to {CHECKSUM_ALGORITHMS['crc32'].label} on verify"


# endregion
