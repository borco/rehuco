"""One regression over every settings page: ``seed_defaults()`` leaves the widgets holding the section's
field defaults (#342).

Under the isolating fixtures every shared settings object holds exactly its factory values, so a page
freshly built shows those -- and ``seed_defaults()`` must leave it looking the same: nothing dirty at
either granularity the dialog reads. What this catches is a seed that writes the *wrong* value into a
fresh page (a stale constant, a field read from the loaded object instead of a fresh one) or one that
raises; a seed that silently skips a widget passes here, and is what each page module's own
``test_seed_defaults_stages_the_factory_values_over_saved_ones`` -- which saves a non-default first -- is
for. The three System Integration pages are covered in their own modules instead.
"""

from collections.abc import Callable
from typing import Any

from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.scraping.registry import ScraperRow
from rehuco_agent.settings.ui import scrapers_page, session_page
from rehuco_agent.settings.ui.checksums_page import ChecksumsPage
from rehuco_agent.settings.ui.descriptions_page import DescriptionsPage
from rehuco_agent.settings.ui.files_page import FilesPage
from rehuco_agent.settings.ui.identity_page import IdentityPage
from rehuco_agent.settings.ui.images_display_page import ImagesDisplayPage
from rehuco_agent.settings.ui.images_files_page import ImagesFilesPage
from rehuco_agent.settings.ui.location_templates_page import LocationTemplatesPage
from rehuco_agent.settings.ui.logs_page import LogsPage
from rehuco_agent.settings.ui.scrapers_page import ScrapersPage
from rehuco_agent.settings.ui.screenshot_patterns_page import ScreenshotPatternsPage
from rehuco_agent.settings.ui.session_page import SessionPage
from rehuco_agent.settings.ui.settings_frame_filter import SettingsFrameFilter
from rehuco_agent.settings.ui.settings_page import SettingsPage
from rehuco_agent.settings.ui.tasks_page import TasksPage
from rehuco_agent.settings.ui.videos_page import VideosPage


def tutorial_location_templates_page() -> LocationTemplatesPage:
    """The Locations page for one resource type -- the same class serves three, one instance each."""
    return LocationTemplatesPage("tutorial")


PAGE_FACTORIES: list[Callable[[], SettingsPage]] = [
    ChecksumsPage,
    DescriptionsPage,
    FilesPage,
    IdentityPage,
    ImagesDisplayPage,
    ImagesFilesPage,
    tutorial_location_templates_page,
    LogsPage,
    ScrapersPage,
    ScreenshotPatternsPage,
    SessionPage,
    TasksPage,
    VideosPage,
]
"""Every page `MainWindow` registers on every platform, in registration order."""


# region fixtures
class FakeSettings:  # pylint: disable=invalid-name,missing-function-docstring,redefined-builtin
    """A minimal in-memory stand-in for the ``QSettings`` group/value API (see
    ``test_markdown_rendering_settings.py`` for the full rationale)."""

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


class FakeRegistry:  # pylint: disable=missing-function-docstring,too-few-public-methods
    """Stands in for the shared `ScraperRegistry`, so `ScrapersPage` scans no real folder."""

    def __init__(self) -> None:
        self.rows: tuple[ScraperRow, ...] = (
            ScraperRow(
                key=None,
                label="",
                publisher="",
                site_name="",
                site_url="",
                source="foo_scraper.py",
                needs_browser=False,
                error=None,
            ),
        )

    def reload(self) -> None:
        pass


@fixture(autouse=True)
def isolate_the_pages_conftest_leaves_alone(mocker: MockerFixture) -> None:
    """The two pages ``conftest.py`` does not already isolate: `SessionPage` reads storage through its
    own module's ``persistent_settings``, and `ScrapersPage` scans the shared registry."""
    mocker.patch.object(session_page, "persistent_settings", return_value=FakeSettings())
    mocker.patch.object(scrapers_page, "shared_scraper_registry", return_value=FakeRegistry())


# endregion


@mark.parametrize("factory", PAGE_FACTORIES, ids=lambda factory: factory.__name__)
def test_seed_defaults_leaves_a_fresh_page_showing_its_field_defaults(
    qtbot: QtBot, factory: Callable[[], SettingsPage]
) -> None:
    """With nothing saved, a fresh page already shows its factory values, so seeding them again changes
    no widget: no frame is dirty against the snapshot taken before, and the page reports clean.

    **Test steps:**

    * build the page and snapshot every frame's values
    * call ``seed_defaults()``
    * verify no frame differs from the snapshot and ``is_dirty()`` is ``False``
    """
    page = factory()
    qtbot.addWidget(page)  # type: ignore[arg-type]  # every page is a QWidget
    frame_filter = SettingsFrameFilter(page, "")  # type: ignore[arg-type]

    page.seed_defaults()

    assert frame_filter.dirty_frames() == []
    assert page.is_dirty() is False
