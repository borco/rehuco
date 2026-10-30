"""The stub settings pages and platform frames a `MainWindow` is built over in a test of anything but its settings
pages (#545); with the fixtures that install them, imported by name into the package's ``conftest.py``."""

from typing import Final

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QWidget
from pytest import FixtureRequest, fixture
from pytest_mock import MockerFixture

SETTINGS_PAGE_CLASSES: Final = (
    "ChecksumsPage",
    "DescriptionsPage",
    "FilesPage",
    "IdentityPage",
    "ImagesDisplayPage",
    "ImagesFilesPage",
    "LocationReplacementsPage",
    "LocationTemplatesPage",
    "LogsPage",
    "RootCatalogPage",
    "ScrapersPage",
    "ScreenshotPatternsPage",
    "SessionPage",
    "ShortcutsPage",
    "SystemIntegrationPage",
    "TasksPage",
    "ToolsPage",
    "VideosPage",
)
"""The settings pages `MainWindow` registers, by their names in :mod:`rehuco_agent.main_window`."""

PLATFORM_FRAME_CLASSES: Final = (
    "rehuco_agent.settings.ui.crash_dumps_frame_windows.CrashDumpsFrameWindows",
    "rehuco_agent.settings.ui.registration_frame_linux.RegistrationFrameLinux",
    "rehuco_agent.settings.ui.registration_frame_windows.RegistrationFrameWindows",
)
"""The platform frames `MainWindow` imports lazily for the System Integration page, by their full paths."""


class StubSettingsPage(QWidget):
    """An empty settings page: what `MainWindow` registers in a test of anything but its settings pages (#545)."""

    tools_requested = Signal()
    """What `VideosPage` has, which `MainWindow` connects."""

    def __init__(self, *_args: object) -> None:
        super().__init__()

    def is_dirty(self) -> bool:
        """Never dirty: there is nothing on it."""
        return False

    def save_changes(self) -> None:
        """Nothing to save."""

    def drop_changes(self) -> None:
        """Nothing to drop."""

    def seed_defaults(self) -> None:
        """Nothing to seed."""


class StubPlatformFrame:  # pylint: disable=too-few-public-methods  # a frame holder, as the real ones are
    """An empty platform frame for the System Integration page (#545)."""

    def __init__(self, *_args: object) -> None:
        self.frame: Final = QFrame()


@fixture(name="real_settings_pages")
def fixture_real_settings_pages() -> None:
    """Build every `MainWindow` of the test with its real settings pages -- for a test of which pages it registers
    and how the dialog shows them; every other window test gets :class:`StubSettingsPage`
    (:func:`fixture_stub_settings_pages`)."""


@fixture(name="stub_settings_pages")
def fixture_stub_settings_pages(request: FixtureRequest, mocker: MockerFixture) -> None:
    """Make every settings page a `MainWindow` registers an empty stub, unless the test asks for
    ``real_settings_pages`` (#545) -- for the modules that build windows, each of which uses it module-wide.

    Each page is tested on its own (``settings/ui``); building all of them made up most of a window's construction,
    which every window test paid. The pages are replaced at :mod:`rehuco_agent.main_window`'s names; the platform
    frames, which it imports when it builds the page, at their own modules' -- why this is not used suite-wide, where
    the frames' own tests would get the stub.

    **Every platform's frames are replaced, not this platform's alone**: a test fakes ``sys.platform`` to build the
    window as another platform's, and a real frame built then is handed to a stub page that never parents it -- a
    bare widget held only by its own signal connections, left to the cyclic collector, which frees it on whichever
    thread allocates next, and ``~QObject`` on the tool-discovery thread deadlocks against the GUI thread (#529,
    #571). A frame module this box cannot import is one the window cannot build here either, so it needs no stub.

    :param request: the test's request, to see whether it asked for the real pages.
    :param mocker: pytest-mock fixture.
    """
    if "real_settings_pages" in request.fixturenames:
        return
    for name in SETTINGS_PAGE_CLASSES:
        mocker.patch(f"rehuco_agent.main_window.{name}", StubSettingsPage)
    for target in PLATFORM_FRAME_CLASSES:
        try:
            mocker.patch(target, StubPlatformFrame)
        except ImportError:  # another platform's module, which this box cannot import
            continue
