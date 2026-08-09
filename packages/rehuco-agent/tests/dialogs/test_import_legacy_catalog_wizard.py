"""Tests for the `File ▸ Import Legacy Catalog…` wizard (#192).

The scan step runs :func:`~rehuco_core.plan_tc_conversion` for real, against a mocked filesystem, for
one test that proves the wizard's own driving of it touches no file; every other test hands the wizard
a canned :class:`~rehuco_core.TcConversionTreePlan` by patching the function directly, since the walk's
own correctness is `test_tc_conversion_plan`'s subject. The import step always runs against a **real**
:class:`~rehuco_core.TaskQueue`, with only :func:`~rehuco_core.convert_tc` mocked -- the same discipline
`test_checksum_actions` follows, since "a click enqueues" is only worth asserting against the engine
that would actually run it.
"""

# five wizard steps over one dialog, and the later ones are only meaningful read against the earlier:
# what Import enqueues depends on what the plan step checked, and what Retry Failed re-enqueues on what
# the result step recorded. One cohesive module per subject, so the length cap is lifted here.
# pylint: disable=too-many-lines

from collections.abc import Iterator
from pathlib import Path
from threading import Event
from typing import Any, Final

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QGuiApplication
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.dialogs.import_legacy_catalog_wizard import ImportLegacyCatalogWizard
from rehuco_agent.dialogs.tc_conversion_plan_table_model import CHECKED_COLUMN
from rehuco_agent.settings.import_legacy_catalog_wizard_settings import ImportLegacyCatalogWizardSettings
from rehuco_core import (
    ChecksumJob,
    ChecksumReport,
    GenerateChecksumsJob,
    JobState,
    StrandedManifestPlan,
    TaskQueue,
    TcConversionPlan,
    TcConversionTreePlan,
    VerifyChecksumsJob,
)

ROOT: Final = Path("/fake/library")

TIMEOUT: Final = 5000
"""How long a test waits for the worker thread, in milliseconds."""

# mirrors `test_tc_conversion_plan_table_model`'s own FLAG_DEFAULTS/plan() exactly -- kept as a
# separate copy rather than shared, this codebase's settings/fixture-test convention
# pylint: disable=duplicate-code
FLAG_DEFAULTS: Final = {
    "tie_break": False,
    "rehu_exists": False,
    "stale_backup": False,
    "size_unparsed": False,
    "duration_present": False,
    "unmapped_keys": (),
    "suspect_mtime": False,
}


def plan(name: str, **flags: Any) -> TcConversionPlan:
    """Build one minimal plan record under a subdirectory of :data:`ROOT`.

    :param name: the resource's subdirectory name, holding ``info.tc``.
    :param flags: overrides over :data:`FLAG_DEFAULTS`.
    :returns: the plan.
    """
    values = {**FLAG_DEFAULTS, **flags}
    return TcConversionPlan(
        tc_path=ROOT / name / "info.tc", rehu_path=ROOT / name / "info.rehu", data={}, renames=(), **values
    )


# pylint: enable=duplicate-code

CLEAN_A: Final = plan("a")
CLEAN_B: Final = plan("b")
BLOCKED: Final = plan("c", rehu_exists=True)
WITH_MANIFEST: Final = plan("m", legacy_manifest=ROOT / "m" / "info.sfv")
"""A resource carrying the legacy `.sfv` its conversion would seed a record from (#256) -- which is what
decides whether checking it means verifying a claim or baselining today's bytes."""

STRANDED: Final = StrandedManifestPlan(rehu_path=ROOT / "s" / "info.rehu", manifest=ROOT / "s" / "info.sfv")
"""An already-converted resource still carrying the manifest its `.checksum` was made from (#259)."""


# the core walk's own fake -- kept as a separate copy rather than shared, this codebase's
# fake-filesystem convention
# pylint: disable=duplicate-code
class FakeDirEntry:
    """A stand-in for :class:`os.DirEntry`, which cannot be constructed outside a real directory read."""

    def __init__(self, name: str, *, directory: bool = False) -> None:
        self.name: Final = name
        self.__directory: Final = directory

    def is_dir(self, *, follow_symlinks: bool = True) -> bool:
        """Whether the test declared this entry a directory."""
        del follow_symlinks
        return self.__directory

    def is_file(self, *, follow_symlinks: bool = True) -> bool:
        """Whether the test declared this entry a regular file."""
        del follow_symlinks
        return not self.__directory


class FakeScandir:
    """What :func:`os.scandir` returns: an iterator that is also a context manager."""

    def __init__(self, entries: list[FakeDirEntry]) -> None:
        self.__entries: Final = entries

    def __enter__(self) -> Any:
        return iter(self.__entries)

    def __exit__(self, *_exception: object) -> None:
        return None


# pylint: enable=duplicate-code


# a second, array-capable stand-in -- mirrors `test_import_legacy_catalog_wizard_settings`'s own
# FakeSettings exactly (`ImportLegacyCatalogWizardSettings.load`/`save` need the array API for
# recent_roots), kept as a separate copy rather than shared, this codebase's settings-test convention
# pylint: disable=duplicate-code
class FakeSettings:  # pylint: disable=invalid-name,missing-function-docstring,redefined-builtin
    """A minimal in-memory stand-in for the ``QSettings`` group/array/value API."""

    def __init__(self) -> None:
        self.__data: dict[str, Any] = {}
        self.__group = ""
        self.__array_key = ""
        self.__array_index = 0
        self.__in_array = False

    def beginGroup(self, name: str) -> None:  # noqa: N802  (Qt API name)
        self.__group = f"{name}/"

    def endGroup(self) -> None:  # noqa: N802
        self.__group = ""

    def beginWriteArray(self, key: str) -> None:  # noqa: N802
        self.__array_key = self.__group + key
        self.__in_array = True
        self.__data[f"{self.__array_key}/size"] = 0  # pylint: disable=unsupported-assignment-operation

    def beginReadArray(self, key: str) -> int:  # noqa: N802
        self.__array_key = self.__group + key
        self.__in_array = True
        return self.__data.get(f"{self.__array_key}/size", 0)

    def setArrayIndex(self, index: int) -> None:  # noqa: N802
        self.__array_index = index
        size_key = f"{self.__array_key}/size"
        self.__data[size_key] = max(self.__data.get(size_key, 0), index + 1)  # pylint: disable=unsupported-assignment-operation

    def setValue(self, key: str, value: Any) -> None:  # noqa: N802
        self.__data[self.__full_key(key)] = value  # pylint: disable=unsupported-assignment-operation

    def value(self, key: str, default: Any = None, type: Any = None) -> Any:  # noqa: A002, N802
        del type
        return self.__data.get(self.__full_key(key), default)

    def endArray(self) -> None:  # noqa: N802
        self.__in_array = False
        self.__array_key = ""

    def __full_key(self, key: str) -> str:
        """The storage key for ``key``: array-indexed while inside an array, else group-scoped."""
        if self.__in_array:
            return f"{self.__array_key}/{self.__array_index}/{key}"
        return self.__group + key


# pylint: enable=duplicate-code


# region fixtures


@fixture(autouse=True, name="fake_settings")
def fixture_fake_settings(mocker: MockerFixture) -> FakeSettings:
    """Stand in for ``persistent_settings()`` so the wizard's geometry/recent-roots load and save never
    touch real ``QSettings`` storage.

    :param mocker: pytest-mock fixture.
    :returns: the in-memory stand-in, for a test that wants to seed it or read what was written.
    """
    settings = FakeSettings()
    mocker.patch("rehuco_agent.dialogs.import_legacy_catalog_wizard.persistent_settings", return_value=settings)
    return settings


@fixture(name="queue")
def fixture_queue(qapp: Any) -> Iterator[TaskQueue]:
    """A real queue, shut down after the test.

    :param qapp: pytest-qt's application fixture -- the wizard builds `QAction`-adjacent widgets, which
        need one to exist before they are constructed.
    :returns: the queue the wizard enqueues into.
    """
    del qapp
    queue = TaskQueue()
    yield queue
    queue.shutdown()


@fixture(name="wizard")
def fixture_wizard(qtbot: QtBot, queue: TaskQueue) -> ImportLegacyCatalogWizard:
    """The wizard under test, over a real queue.

    :param qtbot: pytest-qt fixture.
    :param queue: the queue to enqueue into.
    :returns: the wizard.
    """
    wizard = ImportLegacyCatalogWizard(queue, username="alice")
    qtbot.addWidget(wizard)
    return wizard


def pages(wizard: ImportLegacyCatalogWizard) -> Any:
    """The wizard's private page objects, the way `test_unsaved_changes_dialog` reaches a dialog's own
    internals -- there is no public API for "which page is showing" beyond the stack itself.

    :param wizard: the wizard to inspect.
    :returns: an object exposing ``root``/``scan``/``plan``/``import_``/``result`` and ``stack``.
    """

    class Pages:  # pylint: disable=too-few-public-methods
        """The wizard's pages and nav buttons, for a test's own reading -- see :func:`pages`."""

        root = wizard._ImportLegacyCatalogWizard__root_page  # type: ignore[attr-defined]  # pylint: disable=protected-access
        scan = wizard._ImportLegacyCatalogWizard__scan_page  # type: ignore[attr-defined]  # pylint: disable=protected-access
        plan_ = wizard._ImportLegacyCatalogWizard__plan_page  # type: ignore[attr-defined]  # pylint: disable=protected-access
        import_ = wizard._ImportLegacyCatalogWizard__import_page  # type: ignore[attr-defined]  # pylint: disable=protected-access
        result = wizard._ImportLegacyCatalogWizard__result_page  # type: ignore[attr-defined]  # pylint: disable=protected-access
        stack = wizard._ImportLegacyCatalogWizard__ui.page_stack  # type: ignore[attr-defined]  # pylint: disable=protected-access
        back_button = wizard._ImportLegacyCatalogWizard__ui.back_button  # type: ignore[attr-defined]  # pylint: disable=protected-access
        next_button = wizard._ImportLegacyCatalogWizard__ui.next_button  # type: ignore[attr-defined]  # pylint: disable=protected-access
        cancel_button = wizard._ImportLegacyCatalogWizard__ui.cancel_button  # type: ignore[attr-defined]  # pylint: disable=protected-access

    return Pages()


def go_to_plan(
    qtbot: QtBot, wizard: ImportLegacyCatalogWizard, mocker: MockerFixture, tree: TcConversionTreePlan
) -> None:
    """Drive the wizard from the root step to the plan step, with the scan mocked.

    :param qtbot: pytest-qt fixture, for waiting on the worker thread.
    :param wizard: the wizard to drive.
    :param mocker: pytest-mock fixture.
    :param tree: what the mocked scan returns.
    """
    mocker.patch("rehuco_agent.dialogs.import_legacy_catalog_wizard.plan_tc_conversion", return_value=tree)
    widgets = pages(wizard)
    widgets.root.ui.root_edit.setText(str(ROOT))
    wizard._ImportLegacyCatalogWizard__set_root(ROOT)  # type: ignore[attr-defined]  # pylint: disable=protected-access
    widgets.next_button.click()
    qtbot.waitUntil(lambda: widgets.stack.currentWidget() is widgets.plan_, timeout=TIMEOUT)


def drive_checked_import(
    mocker: MockerFixture,
    qtbot: QtBot,
    wizard: ImportLegacyCatalogWizard,
    queue: TaskQueue,
    *resources: TcConversionPlan,
) -> list[ChecksumJob]:
    """Import ``resources`` with *Check the content of every converted resource* ticked (#256).

    Both runs are mocked away -- what this is about is which job the wizard built and how, not what
    hashing a mocked filesystem would establish -- while the queue itself stays real, so the jobs come
    back off an engine that would have run them.

    :param mocker: pytest-mock fixture.
    :param qtbot: pytest-qt fixture, for waiting on the queue.
    :param wizard: the wizard to drive.
    :param queue: the queue it enqueues into.
    :param resources: the plan records to import; every row is checked by default.
    :returns: the check jobs, in the order they were enqueued.
    """
    mocker.patch.object(Path, "exists", autospec=True, return_value=True)
    mocker.patch("rehuco_core.tc_import_job.convert_tc", return_value=mocker.MagicMock())
    mocker.patch("rehuco_core.checksum_jobs.verify_checksums", return_value=ChecksumReport())
    mocker.patch("rehuco_core.checksum_jobs.generate_checksums", return_value=ChecksumReport())
    enqueue = mocker.patch.object(queue, "enqueue", wraps=queue.enqueue)
    go_to_plan(qtbot, wizard, mocker, TcConversionTreePlan(ROOT, resources))
    pages(wizard).plan_.ui.verify_content_check.setChecked(True)

    pages(wizard).next_button.click()

    qtbot.waitUntil(lambda: pages(wizard).stack.currentWidget() is pages(wizard).result, timeout=TIMEOUT)
    return [call.args[0] for call in enqueue.call_args_list if isinstance(call.args[0], ChecksumJob)]


# endregion


# region Step 1 -- root


def test_next_is_disabled_until_a_root_is_chosen(wizard: ImportLegacyCatalogWizard) -> None:
    """Next is offered only once a root is chosen.

    **Test steps:**

    * build the wizard fresh
    * verify Next starts disabled
    """
    assert not pages(wizard).next_button.isEnabled()


def test_browsing_sets_the_root_and_enables_next(mocker: MockerFixture, wizard: ImportLegacyCatalogWizard) -> None:
    """Choosing a folder through the browse button sets the root and enables Next.

    **Test steps:**

    * mock the folder chooser to return a path
    * click Browse
    * verify the root is set and Next is enabled
    """
    mocker.patch(
        "rehuco_agent.dialogs.import_legacy_catalog_wizard.QFileDialog.getExistingDirectory",
        return_value=str(ROOT),
    )

    pages(wizard).root.ui.browse_button.click()

    assert wizard.root == ROOT
    assert pages(wizard).next_button.isEnabled()


def test_cancelling_the_browse_dialog_leaves_the_root_unset(
    mocker: MockerFixture, wizard: ImportLegacyCatalogWizard
) -> None:
    """Cancelling the folder chooser sets nothing.

    **Test steps:**

    * mock the folder chooser to return nothing (cancelled)
    * click Browse
    * verify the root is still unset
    """
    mocker.patch("rehuco_agent.dialogs.import_legacy_catalog_wizard.QFileDialog.getExistingDirectory", return_value="")

    pages(wizard).root.ui.browse_button.click()

    assert wizard.root is None


def test_a_recent_root_can_be_chosen_from_the_combo(
    fake_settings: FakeSettings, qtbot: QtBot, queue: TaskQueue
) -> None:
    """A previously scanned root shows up in the recent-roots combo and can be re-chosen.

    **Test steps:**

    * seed the wizard's settings with one recent root, then build a wizard
    * choose it from the combo
    * verify the root is set
    """
    seed = ImportLegacyCatalogWizardSettings()
    seed.record_root(ROOT)
    seed.save(fake_settings)  # type: ignore[arg-type]
    wizard = ImportLegacyCatalogWizard(queue, username="alice")
    qtbot.addWidget(wizard)
    combo = pages(wizard).root.ui.recent_roots_combo

    assert combo.count() == 1
    combo.activated.emit(0)

    # ImportLegacyCatalogWizardSettings.load resolves each stored root (see RecentFilesSettings, #64)
    assert wizard.root == ROOT.resolve()


# endregion


# region Step 2 -- scan


def test_the_scan_step_produces_the_plan_without_touching_any_file(
    mocker: MockerFixture, qtbot: QtBot, wizard: ImportLegacyCatalogWizard
) -> None:
    """The scan runs the real walk (#191) against a mocked filesystem and writes nothing.

    **Test steps:**

    * mock a tree holding one `.tc` resource
    * drive the wizard from root to plan
    * verify the plan table was populated and no rename/unlink ever happened
    """
    listing = {
        ROOT: [FakeDirEntry("a", directory=True)],
        ROOT / "a": [FakeDirEntry("info.tc")],
    }
    mocker.patch("rehuco_core.tc_conversion_plan.os.scandir", side_effect=lambda d: FakeScandir(listing[Path(d)]))
    mocker.patch.object(Path, "read_text", autospec=True, return_value="type: Tutorial\ntitle: X\n")
    mocker.patch.object(Path, "exists", autospec=True, return_value=False)
    mocker.patch.object(Path, "stat", autospec=True, return_value=mocker.MagicMock(st_mtime=1700000000.0))
    mocker.patch("rehuco_core.tc_conversion_plan.scan_tc_screenshots", return_value=[])
    mock_rename = mocker.patch.object(Path, "rename", autospec=True)
    mock_unlink = mocker.patch.object(Path, "unlink", autospec=True)
    widgets = pages(wizard)
    widgets.root.ui.root_edit.setText(str(ROOT))
    wizard._ImportLegacyCatalogWizard__set_root(ROOT)  # type: ignore[attr-defined]  # pylint: disable=protected-access

    widgets.next_button.click()
    qtbot.waitUntil(lambda: widgets.stack.currentWidget() is widgets.plan_, timeout=TIMEOUT)

    assert [row.path for row in wizard.model.rows()] == [ROOT / "a/info.tc"]
    mock_rename.assert_not_called()
    mock_unlink.assert_not_called()


def test_cancelling_mid_scan_returns_to_the_root_step(
    mocker: MockerFixture, qtbot: QtBot, wizard: ImportLegacyCatalogWizard
) -> None:
    """Cancel during the scan stops it and returns the wizard to step 1.

    **Test steps:**

    * mock a scan that raises when its progress callback is asked to check for a cancel, simulating a
      real one that noticed the request at its next resource
    * begin the scan, then cancel immediately
    * verify the wizard is back on the root step
    """

    def slow_scan(root: Path, *, username: str, progress: Any) -> Any:
        del root, username
        while True:
            progress(1)

    mocker.patch("rehuco_agent.dialogs.import_legacy_catalog_wizard.plan_tc_conversion", side_effect=slow_scan)
    widgets = pages(wizard)
    wizard._ImportLegacyCatalogWizard__set_root(ROOT)  # type: ignore[attr-defined]  # pylint: disable=protected-access
    widgets.next_button.click()
    qtbot.waitUntil(lambda: widgets.stack.currentWidget() is widgets.scan, timeout=TIMEOUT)

    widgets.cancel_button.click()

    qtbot.waitUntil(lambda: widgets.stack.currentWidget() is widgets.root, timeout=TIMEOUT)


def test_a_scan_failure_is_shown_on_the_scan_page(
    mocker: MockerFixture, qtbot: QtBot, wizard: ImportLegacyCatalogWizard
) -> None:
    """A scan that raises reports the failure on the scan page rather than crashing the wizard.

    **Test steps:**

    * mock the scan to raise
    * begin the scan
    * verify the status label names the failure
    """
    mocker.patch(
        "rehuco_agent.dialogs.import_legacy_catalog_wizard.plan_tc_conversion",
        side_effect=OSError("mount is away"),
    )
    widgets = pages(wizard)
    wizard._ImportLegacyCatalogWizard__set_root(ROOT)  # type: ignore[attr-defined]  # pylint: disable=protected-access

    widgets.next_button.click()

    qtbot.waitUntil(lambda: "Scan failed" in widgets.scan.ui.status_label.text(), timeout=TIMEOUT)
    assert "mount is away" in widgets.scan.ui.status_label.text()


def test_closing_the_wizard_mid_scan_stops_the_worker_thread(
    mocker: MockerFixture, qtbot: QtBot, wizard: ImportLegacyCatalogWizard
) -> None:
    """Closing the wizard while a scan is in flight stops the worker rather than leaving it detached.

    **Test steps:**

    * begin a scan that never finishes on its own
    * close the wizard
    * verify it closed without hanging and the worker thread is no longer running
    """

    def slow_scan(root: Path, *, username: str, progress: Any) -> Any:
        del root, username
        while True:
            progress(1)

    mocker.patch("rehuco_agent.dialogs.import_legacy_catalog_wizard.plan_tc_conversion", side_effect=slow_scan)
    widgets = pages(wizard)
    wizard._ImportLegacyCatalogWizard__set_root(ROOT)  # type: ignore[attr-defined]  # pylint: disable=protected-access
    widgets.next_button.click()
    qtbot.waitUntil(lambda: widgets.stack.currentWidget() is widgets.scan, timeout=TIMEOUT)

    wizard.done(0)

    thread = wizard._ImportLegacyCatalogWizard__thread  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert thread is not None
    assert not thread.isRunning()


# endregion


# region Step 3 -- plan


def test_blocked_rows_are_unchecked_and_clean_rows_are_checked(
    mocker: MockerFixture, qtbot: QtBot, wizard: ImportLegacyCatalogWizard
) -> None:
    """Blocked rows are unchecked and cannot be selected without the explicit opt-in -- but the
    checkbox itself is never disabled, since checking it *is* the opt-in.

    **Test steps:**

    * drive the wizard to the plan step over a clean and a blocked resource
    * verify the checkbox states
    """
    go_to_plan(qtbot, wizard, mocker, TcConversionTreePlan(ROOT, (CLEAN_A, BLOCKED)))

    rows = wizard.model.rows()

    assert rows[0].checked is True
    assert rows[1].checked is False


def test_the_summary_line_matches_the_table(
    mocker: MockerFixture, qtbot: QtBot, wizard: ImportLegacyCatalogWizard
) -> None:
    """The header summary counts match the table's own clean/flagged/blocked counts.

    **Test steps:**

    * drive the wizard to the plan step over one clean and one blocked resource
    * verify the summary label names both counts
    """
    go_to_plan(qtbot, wizard, mocker, TcConversionTreePlan(ROOT, (CLEAN_A, BLOCKED)))

    text = pages(wizard).plan_.ui.summary_label.text()

    assert "1 clean" in text
    assert "1 blocked" in text


def test_next_is_disabled_with_nothing_checked(
    mocker: MockerFixture, qtbot: QtBot, wizard: ImportLegacyCatalogWizard
) -> None:
    """Import cannot be started with no rows selected.

    **Test steps:**

    * drive the wizard to the plan step over a single blocked (unchecked) resource
    * verify Next is disabled
    """
    go_to_plan(qtbot, wizard, mocker, TcConversionTreePlan(ROOT, (BLOCKED,)))

    assert not pages(wizard).next_button.isEnabled()


def test_back_returns_from_the_plan_step_to_the_root_step(
    mocker: MockerFixture, qtbot: QtBot, wizard: ImportLegacyCatalogWizard
) -> None:
    """Back gives up the scan and lets a different root be chosen.

    **Test steps:**

    * drive the wizard to the plan step
    * click Back
    * verify the wizard is back on the root step
    """
    go_to_plan(qtbot, wizard, mocker, TcConversionTreePlan(ROOT, (CLEAN_A,)))

    pages(wizard).back_button.click()

    assert pages(wizard).stack.currentWidget() is pages(wizard).root


def test_the_summary_names_suspect_mtimes_and_unreadable_folders(
    mocker: MockerFixture, qtbot: QtBot, wizard: ImportLegacyCatalogWizard
) -> None:
    """A resource flagged `suspect_mtime` and an unreadable branch are both called out on their own
    line, not buried as one flag among six (#192's notes).

    **Test steps:**

    * drive the wizard to the plan step over a suspect resource, with one unreadable folder reported
    * verify the summary names both
    """
    suspect = plan("s", suspect_mtime=True)
    tree = TcConversionTreePlan(ROOT, (suspect,), unreadable=(ROOT / "away",))
    go_to_plan(qtbot, wizard, mocker, tree)

    text = pages(wizard).plan_.ui.summary_label.text()

    assert "near-identical timestamps" in text
    assert "1 folder(s) could not be read" in text


# endregion


# region Step 4 -- import


def test_import_enqueues_one_job_per_selected_resource_and_none_for_unselected(
    mocker: MockerFixture, qtbot: QtBot, wizard: ImportLegacyCatalogWizard, queue: TaskQueue
) -> None:
    """Only the checked rows become jobs; the rest are marked skipped without ever running.

    **Test steps:**

    * drive the wizard to the plan step over two clean resources, uncheck the second
    * click Import
    * verify exactly one job reached the queue, and the unchecked row reads skipped
    """
    mocker.patch.object(Path, "exists", autospec=True, return_value=True)
    convert = mocker.patch("rehuco_core.tc_import_job.convert_tc", return_value=mocker.MagicMock())
    go_to_plan(qtbot, wizard, mocker, TcConversionTreePlan(ROOT, (CLEAN_A, CLEAN_B)))
    proxy = pages(wizard).plan_.ui.plan_table_view.model()
    proxy.setData(proxy.index(1, CHECKED_COLUMN), Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)

    pages(wizard).next_button.click()

    qtbot.waitUntil(lambda: pages(wizard).stack.currentWidget() is pages(wizard).result, timeout=TIMEOUT)
    assert len(queue.jobs()) == 1
    convert.assert_called_once()
    by_path = {row.path: row for row in wizard.model.rows()}
    assert by_path[CLEAN_B.tc_path].outcome == "skipped"
    assert by_path[CLEAN_A.tc_path].outcome == "converted"


def test_a_blocked_row_checked_by_the_user_is_enqueued_with_overwrite(
    mocker: MockerFixture, qtbot: QtBot, wizard: ImportLegacyCatalogWizard, queue: TaskQueue
) -> None:
    """Checking a `rehu_exists` row is the explicit opt-in, and its job is told to overwrite.

    **Test steps:**

    * drive the wizard to the plan step over one blocked resource and check it
    * click Import
    * verify `convert_tc` was asked to overwrite
    """
    mocker.patch.object(Path, "exists", autospec=True, return_value=True)
    convert = mocker.patch("rehuco_core.tc_import_job.convert_tc", return_value=mocker.MagicMock())
    go_to_plan(qtbot, wizard, mocker, TcConversionTreePlan(ROOT, (BLOCKED,)))
    proxy = pages(wizard).plan_.ui.plan_table_view.model()
    proxy.setData(proxy.index(0, CHECKED_COLUMN), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)

    pages(wizard).next_button.click()

    qtbot.waitUntil(lambda: bool(queue.jobs()) and queue.jobs()[0].state is JobState.DONE, timeout=TIMEOUT)
    assert convert.call_args.kwargs["overwrite"] is True


def test_cancel_mid_import_leaves_every_resource_converted_or_untouched(
    mocker: MockerFixture, qtbot: QtBot, wizard: ImportLegacyCatalogWizard
) -> None:
    """Cancelling stops every job still waiting its turn outright; the one already running finishes on
    its own -- never a resource left half-converted (#192's whole safety argument).

    **Test steps:**

    * block the first of three jobs on an event, drive the wizard to import all three, wait for the
      first to start, then cancel
    * verify the first still finishes and the other two never call `convert_tc` at all
    """
    mocker.patch.object(Path, "exists", autospec=True, return_value=True)
    entered = Event()
    release = Event()

    def slow_convert(*_args: Any, **_kwargs: Any) -> Any:
        entered.set()
        assert release.wait(5.0)
        return mocker.MagicMock()

    convert = mocker.patch("rehuco_core.tc_import_job.convert_tc", side_effect=slow_convert)
    third = plan("d")
    go_to_plan(qtbot, wizard, mocker, TcConversionTreePlan(ROOT, (CLEAN_A, CLEAN_B, third)))

    pages(wizard).next_button.click()
    assert entered.wait(TIMEOUT / 1000)
    pages(wizard).cancel_button.click()
    release.set()

    qtbot.waitUntil(lambda: pages(wizard).stack.currentWidget() is pages(wizard).result, timeout=TIMEOUT)
    assert convert.call_count == 1
    by_path = {row.path: row for row in wizard.model.rows()}
    assert by_path[CLEAN_A.tc_path].outcome == "converted"
    assert by_path[CLEAN_B.tc_path].outcome == "cancelled"
    assert by_path[third.tc_path].outcome == "cancelled"


# endregion


# region Step 4 -- the content check (#256)


def test_no_check_is_queued_unless_the_option_is_ticked(
    mocker: MockerFixture, qtbot: QtBot, wizard: ImportLegacyCatalogWizard, queue: TaskQueue
) -> None:
    """Off is the default, because on reads the whole library -- the conversion still carries the claim.

    **Test steps:**

    * import one resource that has a manifest, with the option left alone
    * verify the queue holds the conversion and nothing else
    """
    mocker.patch.object(Path, "exists", autospec=True, return_value=True)
    mocker.patch("rehuco_core.tc_import_job.convert_tc", return_value=mocker.MagicMock())
    go_to_plan(qtbot, wizard, mocker, TcConversionTreePlan(ROOT, (WITH_MANIFEST,)))

    pages(wizard).next_button.click()

    qtbot.waitUntil(lambda: pages(wizard).stack.currentWidget() is pages(wizard).result, timeout=TIMEOUT)
    assert len(queue.jobs()) == 1


def test_a_ticked_import_verifies_where_a_manifest_made_a_claim(
    mocker: MockerFixture, qtbot: QtBot, wizard: ImportLegacyCatalogWizard, queue: TaskQueue
) -> None:
    """The conversion seeded the record from the manifest, so the check tests that record and no more.

    **Test steps:**

    * tick the option and import one resource whose plan names a manifest
    * verify the second job is a verify over the `.rehu`, forbidden to seed or to create
    """
    checks = drive_checked_import(mocker, qtbot, wizard, queue, WITH_MANIFEST)

    assert len(checks) == 1
    job = checks[0]
    assert isinstance(job, VerifyChecksumsJob)
    assert job.source == WITH_MANIFEST.rehu_path
    assert job.seed_legacy is False
    assert job.create_if_missing is False


def test_a_ticked_import_baselines_where_no_manifest_made_one(
    mocker: MockerFixture, qtbot: QtBot, wizard: ImportLegacyCatalogWizard, queue: TaskQueue
) -> None:
    """With nothing to check against, adopting today's bytes is what it is -- and it says so.

    **Test steps:**

    * tick the option and import one resource whose plan names no manifest
    * verify the second job is a generate over the `.rehu`
    """
    checks = drive_checked_import(mocker, qtbot, wizard, queue, CLEAN_A)

    assert len(checks) == 1
    assert isinstance(checks[0], GenerateChecksumsJob)
    assert checks[0].source == CLEAN_A.rehu_path


def test_the_result_summary_says_the_checks_outlive_the_wizard(
    mocker: MockerFixture, qtbot: QtBot, wizard: ImportLegacyCatalogWizard, queue: TaskQueue
) -> None:
    """The conversions are done and these are not; silence would read as *the import is finished*.

    **Test steps:**

    * tick the option and import two resources
    * verify the result summary names how many checks were queued
    """
    drive_checked_import(mocker, qtbot, wizard, queue, CLEAN_A, CLEAN_B)

    assert "2 content check(s) were queued" in pages(wizard).result.ui.summary_label.text()


def test_cancelling_an_import_cancels_the_checks_it_queued(
    mocker: MockerFixture, qtbot: QtBot, wizard: ImportLegacyCatalogWizard, queue: TaskQueue
) -> None:
    """Stopping an import means stopping the hashing too, or it reads the library for hours afterwards.

    **Test steps:**

    * block the first conversion, tick the option, import two resources, then cancel mid-run
    * verify no check ever ran and every one of them is cancelled
    """
    mocker.patch.object(Path, "exists", autospec=True, return_value=True)
    verify = mocker.patch("rehuco_core.checksum_jobs.verify_checksums", return_value=ChecksumReport())
    entered = Event()
    release = Event()

    def slow_convert(*_args: Any, **_kwargs: Any) -> Any:
        entered.set()
        assert release.wait(5.0)
        return mocker.MagicMock()

    mocker.patch("rehuco_core.tc_import_job.convert_tc", side_effect=slow_convert)
    go_to_plan(qtbot, wizard, mocker, TcConversionTreePlan(ROOT, (WITH_MANIFEST, CLEAN_B)))
    pages(wizard).plan_.ui.verify_content_check.setChecked(True)

    pages(wizard).next_button.click()
    assert entered.wait(TIMEOUT / 1000)
    pages(wizard).cancel_button.click()
    release.set()

    qtbot.waitUntil(lambda: pages(wizard).stack.currentWidget() is pages(wizard).result, timeout=TIMEOUT)
    verify.assert_not_called()
    serials = {status.serial for status in queue.jobs() if not str(status.label).startswith("Import")}
    assert len(serials) == 2
    qtbot.waitUntil(
        lambda: all(status.state is JobState.CANCELLED for status in queue.jobs() if status.serial in serials),
        timeout=TIMEOUT,
    )


# endregion


# region Step 4 -- stranded manifests (#259)


def test_a_stranded_row_enqueues_a_retirement_and_reports_it_as_retired(
    qtbot: QtBot, mocker: MockerFixture, wizard: ImportLegacyCatalogWizard, queue: TaskQueue
) -> None:
    """The second kind of row, end to end: its own job, its own word on the result table.

    **Test steps:**

    * scan a tree holding one conversion and one stranded manifest, then import
    * verify one job of each kind was enqueued, and the two rows read *converted* and *retired*
    """
    mocker.patch.object(Path, "exists", autospec=True, return_value=True)
    mocker.patch("rehuco_core.tc_import_job.convert_tc", return_value=mocker.MagicMock())
    remediate = mocker.patch("rehuco_core.legacy_manifest_jobs.remediate_legacy_manifest", return_value=None)
    enqueue = mocker.patch.object(queue, "enqueue", wraps=queue.enqueue)
    go_to_plan(qtbot, wizard, mocker, TcConversionTreePlan(ROOT, (CLEAN_A,), (), (STRANDED,)))

    pages(wizard).next_button.click()

    qtbot.waitUntil(lambda: pages(wizard).stack.currentWidget() is pages(wizard).result, timeout=TIMEOUT)
    enqueued = [call.args[0] for call in enqueue.call_args_list]
    assert [type(job).__name__ for job in enqueued] == ["TcImportJob", "RetireLegacyManifestJob"]
    remediate.assert_called_once_with(STRANDED.rehu_path, excluded_patterns=mocker.ANY)
    by_path = {row.path: row for row in wizard.model.rows()}
    assert by_path[CLEAN_A.tc_path].outcome == "converted"
    assert by_path[STRANDED.rehu_path].outcome == "retired"
    assert "1 manifest(s) retired" in pages(wizard).result.ui.summary_label.text()


def test_the_plan_step_says_how_many_stranded_manifests_the_scan_found(
    qtbot: QtBot, mocker: MockerFixture, wizard: ImportLegacyCatalogWizard
) -> None:
    """A reader who came to convert a tree is told the run will also tidy up after an earlier one.

    **Test steps:**

    * scan a tree holding one conversion and one stranded manifest
    * verify the plan summary names them on their own line
    """
    go_to_plan(qtbot, wizard, mocker, TcConversionTreePlan(ROOT, (CLEAN_A,), (), (STRANDED,)))

    assert "1 converted resource(s) still carry the legacy manifest" in pages(wizard).plan_.ui.summary_label.text()


def test_a_stranded_row_is_never_given_a_content_check(
    qtbot: QtBot, mocker: MockerFixture, wizard: ImportLegacyCatalogWizard, queue: TaskQueue
) -> None:
    """It reads no bytes and its record lands dateless, so the option has nothing to buy here.

    **Test steps:**

    * import a stranded-only tree with *Check the content of every converted resource* ticked
    * verify no checksum job was enqueued
    """
    mocker.patch.object(Path, "exists", autospec=True, return_value=True)
    mocker.patch("rehuco_core.legacy_manifest_jobs.remediate_legacy_manifest", return_value=None)
    enqueue = mocker.patch.object(queue, "enqueue", wraps=queue.enqueue)
    go_to_plan(qtbot, wizard, mocker, TcConversionTreePlan(ROOT, (), (), (STRANDED,)))
    pages(wizard).plan_.ui.verify_content_check.setChecked(True)

    pages(wizard).next_button.click()

    qtbot.waitUntil(lambda: pages(wizard).stack.currentWidget() is pages(wizard).result, timeout=TIMEOUT)
    assert not [call.args[0] for call in enqueue.call_args_list if isinstance(call.args[0], ChecksumJob)]


# endregion


# region Step 5 -- result


def test_a_forced_failure_is_reported_and_retry_failed_reenqueues_exactly_it(
    mocker: MockerFixture, qtbot: QtBot, wizard: ImportLegacyCatalogWizard
) -> None:
    """A conversion that raises is reported failed with its message, and Retry Failed re-enqueues
    exactly the failed rows -- not the ones that already converted.

    **Test steps:**

    * mock one resource's conversion to raise and the other to succeed
    * import both, wait for both to finish
    * click Retry Failed, mock the conversion to succeed this time
    * verify only the failed one was retried and it now reads converted
    """
    mocker.patch.object(Path, "exists", autospec=True, return_value=True)
    calls: list[Path] = []

    def convert_side_effect(tc_path: Path, **_kwargs: Any) -> Any:
        calls.append(tc_path)
        if tc_path == CLEAN_B.tc_path:
            raise FileExistsError(tc_path)
        return mocker.MagicMock()

    convert = mocker.patch("rehuco_core.tc_import_job.convert_tc", side_effect=convert_side_effect)
    go_to_plan(qtbot, wizard, mocker, TcConversionTreePlan(ROOT, (CLEAN_A, CLEAN_B)))

    pages(wizard).next_button.click()
    qtbot.waitUntil(lambda: pages(wizard).stack.currentWidget() is pages(wizard).result, timeout=TIMEOUT)
    by_path = {row.path: row for row in wizard.model.rows()}
    assert by_path[CLEAN_B.tc_path].outcome == "failed"
    assert "FileExistsError" in (by_path[CLEAN_B.tc_path].message or "")
    assert by_path[CLEAN_A.tc_path].outcome == "converted"

    convert.side_effect = lambda tc_path, **_kwargs: (calls.append(tc_path), mocker.MagicMock())[1]
    pages(wizard).result.ui.retry_failed_button.click()
    qtbot.waitUntil(lambda: wizard.model.rows()[1].outcome == "converted", timeout=TIMEOUT)
    qtbot.waitUntil(lambda: pages(wizard).stack.currentWidget() is pages(wizard).result, timeout=TIMEOUT)

    assert calls == [CLEAN_A.tc_path, CLEAN_B.tc_path, CLEAN_B.tc_path]
    # the row that converted on the first run keeps its outcome through the retry -- stamping it
    # *skipped* would make the result table lie about work that genuinely happened
    assert wizard.model.rows()[0].outcome == "converted"
    assert "2 converted" in pages(wizard).result.ui.summary_label.text()


def test_the_result_summary_counts_match_the_table(
    mocker: MockerFixture, qtbot: QtBot, wizard: ImportLegacyCatalogWizard, queue: TaskQueue
) -> None:
    """The result step's header counts converted/failed/skipped, matching the rows.

    **Test steps:**

    * import one resource that succeeds and leave a second unchecked
    * verify the summary text
    """
    del queue
    mocker.patch.object(Path, "exists", autospec=True, return_value=True)
    mocker.patch("rehuco_core.tc_import_job.convert_tc", return_value=mocker.MagicMock())
    go_to_plan(qtbot, wizard, mocker, TcConversionTreePlan(ROOT, (CLEAN_A, CLEAN_B)))
    proxy = pages(wizard).plan_.ui.plan_table_view.model()
    proxy.setData(proxy.index(1, CHECKED_COLUMN), Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)

    pages(wizard).next_button.click()
    qtbot.waitUntil(lambda: pages(wizard).stack.currentWidget() is pages(wizard).result, timeout=TIMEOUT)

    text = pages(wizard).result.ui.summary_label.text()

    assert "1 converted" in text
    assert "1 skipped" in text


def test_retry_failed_with_nothing_failed_does_nothing(
    mocker: MockerFixture, qtbot: QtBot, wizard: ImportLegacyCatalogWizard
) -> None:
    """Retry Failed is a no-op when every row already converted.

    **Test steps:**

    * import one resource that succeeds
    * click Retry Failed
    * verify no second call was made
    """
    mocker.patch.object(Path, "exists", autospec=True, return_value=True)
    convert = mocker.patch("rehuco_core.tc_import_job.convert_tc", return_value=mocker.MagicMock())
    go_to_plan(qtbot, wizard, mocker, TcConversionTreePlan(ROOT, (CLEAN_A,)))
    pages(wizard).next_button.click()
    qtbot.waitUntil(lambda: pages(wizard).stack.currentWidget() is pages(wizard).result, timeout=TIMEOUT)

    pages(wizard).result.ui.retry_failed_button.click()

    convert.assert_called_once()


def test_copy_and_save_write_the_same_result_text(
    mocker: MockerFixture, qtbot: QtBot, wizard: ImportLegacyCatalogWizard
) -> None:
    """Copy puts the result report on the clipboard and Save writes the identical text to a file.

    **Test steps:**

    * import one resource that succeeds
    * click Copy, then Save with a mocked file chooser
    * verify the clipboard and the written file agree, and both name the resource and its outcome
    """
    mocker.patch.object(Path, "exists", autospec=True, return_value=True)
    mocker.patch("rehuco_core.tc_import_job.convert_tc", return_value=mocker.MagicMock())
    go_to_plan(qtbot, wizard, mocker, TcConversionTreePlan(ROOT, (CLEAN_A,)))
    pages(wizard).next_button.click()
    qtbot.waitUntil(lambda: pages(wizard).stack.currentWidget() is pages(wizard).result, timeout=TIMEOUT)

    pages(wizard).result.ui.copy_button.click()
    clipboard_text = QGuiApplication.clipboard().text()

    mocker.patch(
        "rehuco_agent.dialogs.import_legacy_catalog_wizard.QFileDialog.getSaveFileName",
        return_value=("/fake/report.txt", ""),
    )
    write = mocker.patch.object(Path, "write_text", autospec=True)
    pages(wizard).result.ui.save_button.click()

    assert str(CLEAN_A.tc_path) in clipboard_text
    assert "converted" in clipboard_text
    write.assert_called_once_with(Path("/fake/report.txt"), clipboard_text, encoding="utf-8")


def test_the_report_carries_a_failure_s_message_beside_its_outcome(
    mocker: MockerFixture, qtbot: QtBot, wizard: ImportLegacyCatalogWizard
) -> None:
    """A failed row's line carries *why*, which is the one thing "failed" cannot say on its own -- and
    the reason the report is worth copying at all when something went wrong.

    **Test steps:**

    * import one resource whose conversion raises
    * click Copy
    * verify its line names the resource, the outcome and the message, one field each
    """
    mocker.patch.object(Path, "exists", autospec=True, return_value=True)
    mocker.patch("rehuco_core.tc_import_job.convert_tc", side_effect=FileExistsError(CLEAN_A.tc_path))
    go_to_plan(qtbot, wizard, mocker, TcConversionTreePlan(ROOT, (CLEAN_A,)))
    pages(wizard).next_button.click()
    qtbot.waitUntil(lambda: pages(wizard).stack.currentWidget() is pages(wizard).result, timeout=TIMEOUT)

    pages(wizard).result.ui.copy_button.click()

    path, outcome, message = QGuiApplication.clipboard().text().split("\t")
    assert path == str(CLEAN_A.tc_path)
    assert outcome == "failed"
    assert "FileExistsError" in message


def test_save_with_no_chosen_path_writes_nothing(
    mocker: MockerFixture, qtbot: QtBot, wizard: ImportLegacyCatalogWizard
) -> None:
    """Cancelling the save file chooser writes nothing.

    **Test steps:**

    * import one resource, cancel the save chooser
    * click Save
    * verify no write happened
    """
    mocker.patch.object(Path, "exists", autospec=True, return_value=True)
    mocker.patch("rehuco_core.tc_import_job.convert_tc", return_value=mocker.MagicMock())
    go_to_plan(qtbot, wizard, mocker, TcConversionTreePlan(ROOT, (CLEAN_A,)))
    pages(wizard).next_button.click()
    qtbot.waitUntil(lambda: pages(wizard).stack.currentWidget() is pages(wizard).result, timeout=TIMEOUT)
    mocker.patch("rehuco_agent.dialogs.import_legacy_catalog_wizard.QFileDialog.getSaveFileName", return_value=("", ""))
    write = mocker.patch.object(Path, "write_text", autospec=True)

    pages(wizard).result.ui.save_button.click()

    write.assert_not_called()


def test_next_on_the_result_step_accepts_the_wizard(
    mocker: MockerFixture, qtbot: QtBot, wizard: ImportLegacyCatalogWizard
) -> None:
    """Next reads Close on the result step, and finishes the wizard.

    **Test steps:**

    * import one resource that succeeds
    * click Next
    * verify the wizard was accepted
    """
    mocker.patch.object(Path, "exists", autospec=True, return_value=True)
    mocker.patch("rehuco_core.tc_import_job.convert_tc", return_value=mocker.MagicMock())
    go_to_plan(qtbot, wizard, mocker, TcConversionTreePlan(ROOT, (CLEAN_A,)))
    pages(wizard).next_button.click()
    qtbot.waitUntil(lambda: pages(wizard).stack.currentWidget() is pages(wizard).result, timeout=TIMEOUT)

    pages(wizard).next_button.click()

    assert wizard.result() == wizard.DialogCode.Accepted


# endregion


# region Miscellaneous


def test_cancel_on_the_root_step_rejects_the_wizard(wizard: ImportLegacyCatalogWizard) -> None:
    """Cancel anywhere but the scan or import steps just closes the wizard.

    **Test steps:**

    * click Cancel on the root step
    * verify the wizard was rejected
    """
    pages(wizard).cancel_button.click()

    assert wizard.result() == wizard.DialogCode.Rejected


def test_the_queue_listener_no_ops_do_nothing(wizard: ImportLegacyCatalogWizard) -> None:
    """`jobs_reordered`/`jobs_removed`/`queue_paused_changed` are no-ops -- this wizard tracks its own
    jobs' state changes only, through `job_enqueued`/`job_updated`.

    **Test steps:**

    * call all three directly
    * verify none of them raise
    """
    wizard.jobs_reordered([1, 2])
    wizard.jobs_removed([1])
    wizard.queue_paused_changed(True)


# endregion


# region Geometry


def test_geometry_round_trips_through_done(
    mocker: MockerFixture, qtbot: QtBot, fake_settings: FakeSettings, queue: TaskQueue
) -> None:
    """Closing the wizard persists its geometry, and the next one restores from exactly those bytes.

    Spies on ``restoreGeometry`` rather than comparing rendered window sizes: an offscreen platform's
    restored frame can differ from what was resized by a couple of pixels, which is a platform quirk
    this test has no business asserting on -- what #192 actually needs is that :meth:`__init__` calls
    ``restoreGeometry`` with exactly what :meth:`done` saved.

    **Test steps:**

    * build a wizard, resize it, close it
    * verify the persisted geometry blob is not empty
    * build a second wizard from the same settings, spying on ``restoreGeometry``
    * verify it was called with exactly that blob
    """
    first = ImportLegacyCatalogWizard(queue)
    qtbot.addWidget(first)
    first.resize(800, 600)

    first.done(0)

    saved = ImportLegacyCatalogWizardSettings()
    saved.load(fake_settings)  # type: ignore[arg-type]
    assert saved.geometry

    restore = mocker.patch.object(ImportLegacyCatalogWizard, "restoreGeometry")
    second = ImportLegacyCatalogWizard(queue)
    qtbot.addWidget(second)

    restore.assert_called_once_with(QByteArray(saved.geometry))
    second.done(0)


# endregion
