"""pytest fixtures for rehuco-agent, and the one import every one of its tests depends on.

``main_rc`` is imported below for its side effect, not for a name: importing it is what registers the
``:/icons/...`` Qt resources, and any widget carrying a themed icon -- a `LogWidget`, hence every
`DocumentWidget`, hence every `MainWindow` -- raises ``cannot open ':/icons/...' for reading`` without
it. It belongs here rather than in the modules that need it, because "the modules that need it" is not
a knowable set: a widget three levels down acquiring an icon silently adds one. Ten test modules each
carried their own copy of this import and the rest were green only by collection accident -- whichever
module ran first registered the resources for the whole process. That accident does not survive
pytest-xdist, where each worker is its own process with its own subset of modules: running
``test_documents_dock.py`` under ``-n 4`` failed 72 of its 81 tests, and the full parallel suite failed
a different 33 depending on how the scheduler happened to split the work (#262).
"""

import logging
from collections.abc import Iterator
from typing import Any

from borco_pyside.logging import LogBridge
from pytest import fixture
from pytest_mock import MockerFixture
from rehuco_agent import main_rc  # noqa: F401  # pylint: disable=unused-import  # registers :/icons/... resources
from rehuco_agent.app_logging import shared_log_bridge
from rehuco_agent.dialogs import conversion_backups_dialog
from rehuco_agent.documents import document_widget
from rehuco_agent.fields.widgets.markdown_view import render_markdown
from rehuco_agent.settings import (
    checksum_settings,
    default_layout_settings,
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
from rehuco_agent.settings.default_layout_settings import shared_default_layout_settings
from rehuco_agent.settings.excluded_files_settings import shared_excluded_files_settings
from rehuco_agent.settings.identity_settings import shared_identity_settings
from rehuco_agent.settings.image_viewer_settings import shared_image_viewer_settings
from rehuco_agent.settings.logs_settings import shared_logs_settings
from rehuco_agent.settings.markdown_rendering_settings import shared_markdown_rendering_settings
from rehuco_agent.settings.reference_images_settings import shared_reference_images_settings
from rehuco_agent.settings.tray_settings import shared_tray_settings
from rehuco_agent.settings.ui import checksums_page, settings_dialog, tasks_page, tray_block
from rehuco_agent.settings.videos_settings import shared_videos_settings


# Mirrors every dedicated settings test's own FakeSettings exactly (see e.g.
# test_markdown_rendering_settings.py) -- kept as a separate copy rather than a shared import,
# matching this codebase's settings-test convention.
# pylint: disable=duplicate-code
class FakeSettings:  # pylint: disable=invalid-name,missing-function-docstring,redefined-builtin
    """An in-memory stand-in for the ``QSettings`` group, value and array API.

    Groups nest on a prefix stack rather than being replaced, which is what ``QSettings`` itself does
    and what the array support below needs: an array opened inside a group writes under both. Every
    section that uses this opens one group at a time, so nothing existing reads differently for it.

    The array half exists for `ConversionBackupsDialogSettings`, the only section here storing a list
    ([[appendices.code-conventions]]), and follows ``QSettings``' own layout -- ``<prefix>/<n>/<key>``
    numbered from one, alongside a ``<prefix>/size`` written when the array closes. Faithful enough
    that the dialog's save-then-load round trip reads back exactly what it wrote, which is what its
    remembered-geometry and recent-roots tests assert on.
    """

    def __init__(self) -> None:
        self.__data: dict[str, Any] = {}
        self.__prefixes: list[str] = []
        self.__arrays: list[list[Any]] = []

    @property
    def __prefix(self) -> str:
        return "".join(self.__prefixes)

    def beginGroup(self, name: str) -> None:  # noqa: N802
        self.__prefixes.append(f"{name}/")

    def endGroup(self) -> None:  # noqa: N802
        if self.__prefixes:
            self.__prefixes.pop()

    def setValue(self, key: str, value: Any) -> None:  # noqa: N802
        self.__data[self.__prefix + key] = value

    def value(self, key: str, default: Any = None, type: Any = None) -> Any:  # noqa: A002, N802
        del type
        return self.__data.get(self.__prefix + key, default)

    def beginWriteArray(self, prefix: str, size: int = -1) -> None:  # noqa: N802
        del size
        self.__arrays.append([prefix, self.__prefix, 0])
        self.__prefixes.append(f"{prefix}/")

    def beginReadArray(self, prefix: str) -> int:  # noqa: N802
        stored = self.__data.get(f"{self.__prefix}{prefix}/size", 0)
        size = int(stored) if stored else 0
        self.__arrays.append([prefix, self.__prefix, size])
        self.__prefixes.append(f"{prefix}/")
        return size

    def setArrayIndex(self, index: int) -> None:  # noqa: N802
        prefix, _, count = self.__arrays[-1]
        self.__prefixes[-1] = f"{prefix}/{index + 1}/"
        self.__arrays[-1][2] = max(count, index + 1)

    def endArray(self) -> None:  # noqa: N802
        prefix, outer, count = self.__arrays.pop()
        self.__prefixes.pop()
        self.__data[f"{outer}{prefix}/size"] = count


# pylint: enable=duplicate-code


@fixture(autouse=True, scope="session")
def warm_the_markdown_extension_cache() -> None:
    """Resolve Python-Markdown's extensions once, while the real filesystem is still visible (#262).

    ``markdown`` looks its extensions up through ``importlib.metadata`` entry points and memoises the
    result in a process-wide ``lru_cache`` -- deliberately, "only load extension entry_points once".
    Reading entry points means reading ``*.dist-info/entry_points.txt`` through ``Path.read_text``,
    and a great many tests here patch exactly that to serve a document's JSON from a fake path. Should
    the *first* render in a process happen under such a patch, the lookup sees a tutorial document
    where an entry-point table should be, caches the empty result forever, and every later render in
    that process dies on ``ModuleNotFoundError: No module named 'fenced_code'`` -- markdown's fallback
    of importing the bare extension name once the entry point is missing.

    Which tests that hits is pure collection order: the serial suite was green only because something
    rendered before anything mocked, while ``test_documents_dock.py`` on its own -- serially or under a
    pytest-xdist worker -- failed 72 of its 81 tests. Warming here happens before the first ``mocker``
    exists, so the cache is always populated from the real filesystem, which is what production does.
    """
    render_markdown("")


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
    fake = FakeSettings()
    mocker.patch.object(checksum_settings, "persistent_settings", return_value=fake)
    # `ChecksumsPage` reaches storage through its own import of `persistent_settings` rather than
    # through the shared instance, so patching the section alone left it on the real one. The settings
    # dialog asks every page whether it is dirty on each edit, and `is_dirty` builds a `QSettings` and
    # re-parses the developer's actual .ini every time it is asked: 2036 real reads of a real file in
    # one profiled run of the window and dock suites (#262). It shares this fixture's fake rather than
    # taking its own, so a Save made through the page is what the shared instance then reads.
    mocker.patch.object(checksums_page, "persistent_settings", return_value=fake)
    yield
    shared_checksum_settings.cache_clear()


@fixture(autouse=True)
def isolate_conversion_backups_dialog_settings(mocker: MockerFixture) -> FakeSettings:
    """Isolate every test building a `ConversionBackupsDialog` from real persistent storage (#262).

    The sharpest of these, because this one **wrote**. The dialog saves on close and again whenever a
    scan finishes, so a suite run appended the tests' own fake roots -- ``/fake/library`` and friends --
    to the developer's real recent-roots list and overwrote the geometry they had left the dialog at.
    Under ``make cov-parallel`` that became several worker processes writing one .ini at once, which is
    where a worker died mid-``load`` with a fatal fault rather than a test failure.

    Nothing patched it before: unlike its neighbours the dialog has no settings *page*, so it fell
    outside the section-by-section isolation above and was reached only through the dialog's own tests.

    :returns: the in-memory stand-in the dialog loads from and saves to -- the same object across one
        test, so its close-then-reopen geometry round trip still reads back what it wrote.
    """
    fake = FakeSettings()
    mocker.patch.object(conversion_backups_dialog, "persistent_settings", return_value=fake)
    return fake


@fixture(autouse=True)
def isolate_tasks_page_settings(mocker: MockerFixture) -> FakeSettings:
    """Isolate every test building a `TasksPage` from real persistent storage (#262).

    `TasksSettings` is read where it is needed rather than held as a process-wide singleton, so unlike
    its neighbours above there is no cache to clear -- but the page still reaches storage through its
    own import of ``persistent_settings``, and the settings dialog asks it whether it is dirty on every
    edit. Each ask built a ``QSettings`` over the developer's real ``.ini`` and re-parsed it: 2372 real
    reads in one profiled run, and the second-largest such leak after `ChecksumsPage`.

    :returns: the in-memory stand-in the page loads from and saves to, for a test that wants to seed it
        or assert on what was written.
    """
    fake = FakeSettings()
    mocker.patch.object(tasks_page, "persistent_settings", return_value=fake)
    return fake


@fixture(autouse=True)
def isolate_shared_default_layout_settings(mocker: MockerFixture) -> Iterator[None]:
    """Isolate every test from the process-wide `DefaultLayoutSettings` singleton (#62).

    Same rationale as :func:`isolate_shared_markdown_rendering_settings`: every `DocumentsDock` reads
    this when it builds a new document dock, and every `DocumentWidget`'s "Save current layout as
    default"/"Reset default layout" actions write it. Without this, whichever test first opened a
    document would pin an instance loaded from the developer's real on-disk settings for the rest of
    the session -- and could overwrite the layout they actually saved as their default.
    """
    shared_default_layout_settings.cache_clear()
    fake = FakeSettings()
    mocker.patch.object(default_layout_settings, "persistent_settings", return_value=fake)
    # the widget's own import site too, same as the tray fixture below: the Save/Reset actions call
    # ``settings.save(persistent_settings())`` through document_widget's import, so an unpatched one
    # would write the developer's real settings file from any test that triggers either action
    mocker.patch.object(document_widget, "persistent_settings", return_value=fake)
    yield
    shared_default_layout_settings.cache_clear()


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
