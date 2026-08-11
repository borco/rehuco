"""pytest fixtures for rehuco-agent."""

import logging
from collections.abc import Iterator
from typing import Any

from borco_pyside.logging import LogBridge
from pytest import fixture
from pytest_mock import MockerFixture
from rehuco_agent.app_logging import shared_log_bridge
from rehuco_agent.settings import (
    checksum_settings,
    excluded_files_settings,
    identity_settings,
    image_viewer_settings,
    logs_settings,
    markdown_rendering_settings,
    reference_images_settings,
    tray_settings,
    videos_settings,
)
from rehuco_agent.settings.checksum_settings import shared_checksum_settings
from rehuco_agent.settings.excluded_files_settings import shared_excluded_files_settings
from rehuco_agent.settings.identity_settings import shared_identity_settings
from rehuco_agent.settings.image_viewer_settings import shared_image_viewer_settings
from rehuco_agent.settings.logs_settings import shared_logs_settings
from rehuco_agent.settings.markdown_rendering_settings import shared_markdown_rendering_settings
from rehuco_agent.settings.reference_images_settings import shared_reference_images_settings
from rehuco_agent.settings.tray_settings import shared_tray_settings
from rehuco_agent.settings.ui import settings_dialog, tray_block
from rehuco_agent.settings.videos_settings import shared_videos_settings


# Mirrors every dedicated settings test's own FakeSettings exactly (see e.g.
# test_markdown_rendering_settings.py) -- kept as a separate copy rather than a shared import,
# matching this codebase's settings-test convention.
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
def isolate_shared_markdown_rendering_settings(mocker: MockerFixture) -> Iterator[None]:
    """Isolate every test from the process-wide `MarkdownRenderingSettings` singleton.

    Without this, whichever test first calls ``shared_markdown_rendering_settings()`` (directly,
    or indirectly via ``DescriptionField.make_viewer``, which every test building a document's
    fields touches) would pin its instance -- and whatever it loaded from real persistent storage
    -- for the rest of the whole test session: leaking state between tests, and reading the
    developer's actual on-disk settings file rather than a hermetic fake. A test that specifically
    exercises this settings object (e.g. ``test_markdown_rendering_settings.py``,
    ``test_descriptions_page.py``) patches ``persistent_settings`` itself, which simply
    overrides this default for its own module.
    """
    shared_markdown_rendering_settings.cache_clear()
    mocker.patch.object(markdown_rendering_settings, "persistent_settings", return_value=FakeSettings())
    yield
    shared_markdown_rendering_settings.cache_clear()


@fixture(autouse=True)
def isolate_shared_identity_settings(mocker: MockerFixture) -> Iterator[None]:
    """Isolate every test from the process-wide `IdentitySettings` singleton (#99).

    Same rationale as :func:`isolate_shared_markdown_rendering_settings`: whichever test first
    calls ``shared_identity_settings()`` (directly, or indirectly via ``DocumentsDock``'s open
    paths or ``MainWindow``'s `IdentityPage`) would otherwise pin an instance loaded from the
    developer's real on-disk settings for the rest of the session. Tests that specifically
    exercise the identity settings patch ``persistent_settings`` themselves.
    """
    shared_identity_settings.cache_clear()
    mocker.patch.object(identity_settings, "persistent_settings", return_value=FakeSettings())
    yield
    shared_identity_settings.cache_clear()


@fixture(autouse=True)
def isolate_shared_image_viewer_settings(mocker: MockerFixture) -> Iterator[None]:
    """Isolate every test from the process-wide `ImageViewerSettings` singleton (#160).

    Same rationale as :func:`isolate_shared_markdown_rendering_settings`: whichever test first
    clicks a thumbnail (or builds an `ImagesPage`) would otherwise pin an instance loaded from the
    developer's real on-disk settings for the rest of the session -- and decide, from that file,
    which surface every later test's viewer opens on.

    Tests that specifically exercise the image-viewer settings patch ``persistent_settings``
    themselves.
    """
    shared_image_viewer_settings.cache_clear()
    mocker.patch.object(image_viewer_settings, "persistent_settings", return_value=FakeSettings())
    yield
    shared_image_viewer_settings.cache_clear()


@fixture(autouse=True)
def isolate_shared_reference_images_settings(mocker: MockerFixture) -> Iterator[None]:
    """Isolate every test from the process-wide `ReferenceImagesSettings` singleton (#222).

    Same rationale as :func:`isolate_shared_markdown_rendering_settings`: whichever test first builds a
    `ImagesPage` (directly, or via ``MainWindow``) would otherwise pin an instance loaded from
    the developer's real on-disk settings for the rest of the session -- and decide, from that file, which
    archive entries every later test's enumeration counts.

    Tests that specifically exercise the reference-images settings patch ``persistent_settings``
    themselves.
    """
    shared_reference_images_settings.cache_clear()
    mocker.patch.object(reference_images_settings, "persistent_settings", return_value=FakeSettings())
    yield
    shared_reference_images_settings.cache_clear()


@fixture(autouse=True)
def isolate_shared_excluded_files_settings(mocker: MockerFixture) -> Iterator[None]:
    """Isolate every test from the process-wide `ExcludedFilesSettings` singleton (#226).

    Same rationale as :func:`isolate_shared_markdown_rendering_settings`: whichever test first builds an
    `ExcludedFilesPage` (directly, or via ``MainWindow``) would otherwise pin an instance loaded from the
    developer's real on-disk settings for the rest of the session -- and decide, from that file, which
    files every later test's size scan and checksum run leave out.

    Tests that specifically exercise the excluded-files settings patch ``persistent_settings``
    themselves.
    """
    shared_excluded_files_settings.cache_clear()
    mocker.patch.object(excluded_files_settings, "persistent_settings", return_value=FakeSettings())
    yield
    shared_excluded_files_settings.cache_clear()


@fixture(autouse=True)
def isolate_shared_checksum_settings(mocker: MockerFixture) -> Iterator[None]:
    """Isolate every test from the process-wide `ChecksumSettings` singleton (#242).

    Same rationale as :func:`isolate_shared_excluded_files_settings`, with one more reason to insist:
    this singleton decides which algorithm a run records under, whether a verify may create a record,
    and -- through ``last_sweep_root`` -- writes back to storage. A test that reached the developer's
    real ``.ini`` would both read their catalog's settings and overwrite the folder they last swept.
    """
    shared_checksum_settings.cache_clear()
    mocker.patch.object(checksum_settings, "persistent_settings", return_value=FakeSettings())
    yield
    shared_checksum_settings.cache_clear()


@fixture(autouse=True)
def isolate_shared_videos_settings(mocker: MockerFixture) -> Iterator[None]:
    """Isolate every test from the process-wide `VideosSettings` singleton (#225).

    Same rationale as :func:`isolate_shared_markdown_rendering_settings`: whichever test first builds a
    `VideosPage` (directly, or via ``MainWindow``) would otherwise pin an instance loaded from the
    developer's real on-disk settings for the rest of the session -- and decide, from that file, which
    backend every later test's duration scan would probe with.

    Tests that specifically exercise the videos settings patch ``persistent_settings`` themselves.
    """
    shared_videos_settings.cache_clear()
    mocker.patch.object(videos_settings, "persistent_settings", return_value=FakeSettings())
    yield
    shared_videos_settings.cache_clear()


@fixture(autouse=True)
def isolate_shared_logs_settings(mocker: MockerFixture) -> Iterator[None]:
    """Isolate every test from the process-wide `LogsSettings` singleton (#200).

    Same rationale as :func:`isolate_shared_markdown_rendering_settings`: whichever test first builds a
    log surface (directly, or via ``MainWindow`` or any ``DocumentWidget``) would otherwise pin an
    instance loaded from the developer's real on-disk settings for the rest of the session -- and decide,
    from that file, how many records every later test's log docks keep.

    Tests that specifically exercise the log settings patch ``persistent_settings`` themselves.
    """
    shared_logs_settings.cache_clear()
    mocker.patch.object(logs_settings, "persistent_settings", return_value=FakeSettings())
    yield
    shared_logs_settings.cache_clear()


@fixture(autouse=True)
def isolate_shared_tray_settings(mocker: MockerFixture) -> Iterator[None]:
    """Isolate every test from the process-wide `TraySettings` singleton (#205).

    Same rationale as :func:`isolate_shared_markdown_rendering_settings`: every `MainWindow` reads
    this at construction to decide whether to build a tray icon, so without this whichever test
    first built one would pin an instance loaded from the developer's real on-disk settings -- and a
    tray icon left enabled there would build (and never tear down) a real `QSystemTrayIcon` in every
    later test's window.

    Tests that specifically exercise the tray settings patch ``persistent_settings`` themselves.
    """
    shared_tray_settings.cache_clear()
    fake = FakeSettings()
    mocker.patch.object(tray_settings, "persistent_settings", return_value=fake)
    # the block's own import site too, unlike the other sections here: its Save is reachable from
    # every System Integration page (one per platform, #205), so an unpatched one would write the
    # developer's real settings file from any test that applies a settings page
    mocker.patch.object(tray_block, "persistent_settings", return_value=fake)
    yield
    shared_tray_settings.cache_clear()


@fixture(autouse=True)
def isolate_shared_log_bridge() -> Iterator[None]:
    """Isolate every test from the process-wide `LogBridge` (#200).

    Two reasons, and the second is the sharp one. The bridge subscribes to
    :func:`~rehuco_agent.settings.logs_settings.shared_logs_settings` for its limit, so a bridge built in
    one test would stay wired to the settings object that test's own isolation has already replaced.
    And it **installs itself on the root logger**: without this teardown every test that builds a window
    would leave another handler there, so by the end of a session one record would be cached dozens of
    times over by bridges nothing can reach.

    Any bridge is removed from the root logger and closed, not merely forgotten -- dropping the cached
    reference alone would leave the handler attached and `logging`'s own module-level handler list
    holding it.
    """
    shared_log_bridge.cache_clear()
    yield
    root = logging.getLogger()
    for handler in [handler for handler in root.handlers if isinstance(handler, LogBridge)]:
        root.removeHandler(handler)
        handler.close()
    shared_log_bridge.cache_clear()


@fixture(autouse=True)
def isolate_settings_dialog_settings(mocker: MockerFixture) -> FakeSettings:
    """Isolate every test building a `SettingsDialog` from real persistent storage (#76).

    The dialog restores its filter toggles on construction and saves them on every change, so
    without this any test constructing one (directly, or via ``MainWindow``) would read -- and
    overwrite -- the developer's own on-disk settings, and leak toggle state into later tests.

    :returns: the in-memory stand-in the dialog loads from and saves to, for a test that wants to
        seed it or assert on what was written.
    """
    fake = FakeSettings()
    mocker.patch.object(settings_dialog, "persistent_settings", return_value=fake)
    return fake
