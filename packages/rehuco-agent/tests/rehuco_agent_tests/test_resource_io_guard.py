"""The agent reaches a resource's files only through the access seam (#415, [[nodes#access-seam]]).

A root a node owns cannot be read by path, so every direct ``open``, ``stat``, directory listing, archive or image read
on a resource's path in ``rehuco_agent`` is a place a remote resource would break -- and so is a call into rehuco-core
that does one of those for the agent (``load_tc``, ``rename_rehu_resource``, a checksum job...), which is where most
of the migration happens. The allowlist below starts at today's sites; a migration issue moves a group of them behind
``ResourceAccess`` and deletes their entries from :data:`TO_MIGRATE`, and nothing is ever added to it -- a new site
fails the test, and so does an entry that no longer matches one, so the list can only shrink.

The access adapters themselves live in ``rehuco_core.access``, outside what is scanned.
"""

from pathlib import Path
from typing import Final

import pytest
import rehuco_agent

from rehuco_agent_tests.resource_io_sites import compare_with_allowed, scan_folder, scan_source

AGENT_DIR: Final = Path(rehuco_agent.__file__).parent

TO_MIGRATE: Final = {
    # RecordOps (#416)
    "documents/document_registry.py::load_or_locked::rehuco_core.RehuDocument.load": 1,
    "documents/document_registry.py::load_or_locked::rehuco_core.load_tc": 1,
    "documents/rehu_document_model.py::RehuDocumentModel.__stamp_disk::.stat": 1,
    "documents/source_views.py::OnDiskView.__read_on_disk::.read_text": 1,
    "rehuco/roots_preview.py::RootsPreview.__read_record::.stat": 1,
    "rehuco/roots_preview.py::RootsPreview.__read_record::rehuco_core.RehuDocument.load": 1,
    "rehuco/roots_preview.py::RootsPreview.__read_record::rehuco_core.load_tc": 1,
    # CatalogOps (#417)
    "rehuco/add_root_dialog.py::AddRootDialog.__browse::.is_dir": 1,
    "rehuco/root_catalog.py::RootCatalog.__run_stat::.stat": 1,
    # Catalog scans as jobs (#427)
    "rehuco/root_catalog.py::RootCatalog.remove_root::rehuco_core.RemoveCatalogRootJob": 1,
    "rehuco/root_catalog.py::RootCatalog.scan::rehuco_core.ScanCatalogRootJob": 1,
    # FileOps (#423)
    "documents/checksum_actions.py::ChecksumActions.__has_something_to_verify::.exists": 1,
    "documents/checksum_rows.py::read_checksum_rows::rehuco_core.enumerate_content_files": 1,
    "documents/document_fields.py::build_document_form.measure_size_on_disk::rehuco_core.content_size_on_disk": 1,
    "documents/files_rows.py::FilesRowsReader.__init__::rehuco_core.DirectoryClassifier": 1,
    "main_window.py::MainWindow.open_path::.is_dir": 1,
    "rehuco/root_catalog.py::RootCatalog.__run_verify::rehuco_core.check_records": 1,
    "rehuco/roots_management.py::managing_record::.exists": 1,
    "rehuco/roots_panel.py::RootsPanel.__refresh::rehuco_core.RootFolderLister": 1,
    # ScreenshotOps reads (#424)
    "documents/rehu_document_image_scanner.py::RehuDocumentImageScanner.screenshots::rehuco_core.other_record_stems": 1,
    "documents/rehu_document_image_scanner.py::markdown_viewer_image::.exists": 1,
    "documents/rehu_document_image_scanner.py::markdown_viewer_image::QImageReader": 1,
    "documents/tc_conversion_outcomes.py::scan_after_conversion::rehuco_core.scan_tc_screenshots": 1,
    "fields/widgets/image_selector.py::ScreenshotListModel.metrics::.open": 1,
    "fields/widgets/image_selector.py::ScreenshotListModel.metrics::.stat": 1,
    "fields/widgets/image_selector.py::read_preview::QImage": 1,
    "fields/widgets/image_source.py::PathImageSource.describe::.stat": 1,
    "fields/widgets/image_source.py::PathImageSource.read::.read_bytes": 1,
    "fields/widgets/image_source.py::ScreenshotKey.of::.stat": 1,
    "fields/widgets/image_source.py::image_size_at::QImageReader": 1,
    "rehuco/roots_preview.py::RootsPreview.__read_image::QImageReader": 1,
    "scraping/image_pipeline.py::acquire::.read_bytes": 1,
    # ContentOps (#425)
    "documents/content_images/archive_cache.py::ArchiveCache.__open::zipfile.ZipFile": 1,
    "documents/content_images/archive_cache.py::ArchiveCache.__read_through_handle::.open": 1,
    "documents/content_images/content_images_model.py::EnumerateJob.run::rehuco_core.enumerate_content_images": 1,
    "documents/document_fields.py::build_document_form.measure_content_images::rehuco_core.enumerate_content_images": 1,
    "documents/document_fields.py::build_document_form.measure_duration::rehuco_core.content_duration": 1,
    "rehuco/roots_lightbox.py::ListingJob.run::rehuco_core.list_archive_images": 1,
    "rehuco/roots_preview.py::RootsPreview.__read_archive::rehuco_core.read_archive_facts": 1,
    # JobOps and checksums (#426)
    (
        "dialogs/import_legacy_catalog_wizard.py::ImportLegacyCatalogWizard.__enqueue_check::"
        "rehuco_core.GenerateChecksumsJob"
    ): 1,
    (
        "dialogs/import_legacy_catalog_wizard.py::ImportLegacyCatalogWizard.__enqueue_check::"
        "rehuco_core.VerifyChecksumsJob"
    ): 1,
    "documents/checksum_actions.py::ChecksumActions.__has_something_to_verify::rehuco_core.legacy_manifest_for": 1,
    "documents/checksum_actions.py::ChecksumActions.forget::rehuco_core.forget_checksums": 1,
    "documents/checksum_rows.py::read_checksum_rows::rehuco_core.load_checksum_record": 1,
    "documents/files_rows.py::FileChecksumStates.read::rehuco_core.load_checksum_record": 1,
    "documents/rehu_document_model.py::RehuDocumentModel.__take_enclosing_claims::rehuco_core.take_enclosing_claims": 1,
    "main_window.py::MainWindow.__on_sweep_checksums::rehuco_core.SweepChecksumsJob": 1,
    # MutationOps (#428)
    "asking_deleter.py::AskingDeleter.delete::rehuco_core.DEFAULT_DELETER.delete": 1,
    "documents/rehu_document_model.py::RehuDocumentModel.__renamed::rehuco_core.rename_rehu_resource": 1,
    "documents/rehu_document_model.py::RehuDocumentModel.rename_conflicts::rehuco_core.rehu_rename_conflict": 1,
    "documents/rename_holders.py::RenameHolderReport.__resource_files::.is_file": 1,
    "documents/rename_holders.py::RenameHolderReport.__resource_files::.iterdir": 1,
    "documents/rename_holders.py::RenameHolderReport.__resource_files::.rglob": 1,
    "recycle_bin_deleter.py::RecycleBinDeleter.delete::borco_pyside.recycle_bin.recycle_bin": 1,
    # ScreenshotOps writes (#429)
    "documents/rehu_document_image_organizer.py::RehuDocumentImageOrganizer.acquire::rehuco_core.save_screenshot": 1,
    "documents/rehu_document_image_organizer.py::RehuDocumentImageOrganizer.convert::rehuco_core.convert_screenshot": 1,
    "documents/rehu_document_image_organizer.py::RehuDocumentImageOrganizer.remove::rehuco_core.delete_screenshot": 1,
    (
        "documents/rehu_document_image_organizer.py::RehuDocumentImageOrganizer.remove::"
        "rehuco_core.renumber_screenshots"
    ): 1,
    (
        "documents/rehu_document_image_organizer.py::RehuDocumentImageOrganizer.reorder::"
        "rehuco_core.renumber_screenshots"
    ): 1,
    # Local-only features behind capabilities (#430)
    "dialogs/conversion_backups_dialog.py::ScanWorker.run::rehuco_core.scan_conversion_backups": 1,
    (
        "dialogs/import_legacy_catalog_wizard.py::ImportLegacyCatalogWizard.__begin_import::"
        "rehuco_core.RetireLegacyManifestJob"
    ): 1,
    "dialogs/import_legacy_catalog_wizard.py::ImportLegacyCatalogWizard.__begin_import::rehuco_core.TcImportJob": 1,
    "dialogs/import_legacy_catalog_wizard.py::_ScanWorker.run::rehuco_core.plan_tc_conversion": 1,
    (
        "documents/conversion_backup_actions.py::ConversionBackupActions.discard::"
        "rehuco_core.discard_conversion_backups"
    ): 1,
    "documents/conversion_backup_actions.py::ConversionBackupActions.refresh::rehuco_core.conversion_backups": 1,
    "documents/document_sub_docks.py::DocumentSubDocks.__on_convert_triggered::.exists": 1,
    "documents/document_sub_docks.py::DocumentSubDocks.__on_convert_triggered::rehuco_core.originals_to_back_up": 1,
    "documents/documents_dock.py::DocumentsDock.__open_companion::.exists": 2,
    "documents/rehu_document_model.py::RehuDocumentModel.convert::rehuco_core.convert_tc": 1,
    "rehuco/roots_management.py::companion_found::.exists": 1,
}
"""Direct accesses to a resource's files, and calls into rehuco-core that make them for the agent, each waiting for the
operation group that will take it over (the issue named beside it). Never add to it."""

APP_LOCAL: Final = {
    # settings, state, logs, crash dumps, the task queue
    "__main__.py::apply_settings_dir::.exists": 1,
    "__main__.py::apply_settings_dir::.is_dir": 1,
    "__main__.py::apply_settings_dir::.mkdir": 1,
    "crash_dumps.py::clear_dumps::.unlink": 1,
    "crash_dumps.py::dump_files::.glob": 1,
    "crash_dumps.py::dump_files::.is_dir": 1,
    "run_log.py::RunLog.__enable_faulthandler::.open": 1,
    "run_log.py::RunLog.__warn_about_a_leftover_sentinel::.read_text": 1,
    "run_log.py::RunLog.finish::.unlink": 1,
    "run_log.py::RunLog.start::.mkdir": 1,
    "settings/catalog_state_store.py::CatalogStateStore.save::.mkdir": 1,
    "settings/state_file.py::read_json_file::.read_text": 1,
    "settings/state_file.py::write_state_file::.mkdir": 1,
    "settings/ui/logs_page.py::LogsPage.__show_log_file::.exists": 1,
    "settings/ui/registry_page.py::RegistryPage.__refresh_dumps_usage::.stat": 1,
    "settings/ui/registry_page.py::RegistryPage.__show_dumps_folder::.exists": 1,
    "tasks/task_queue_store.py::TaskQueueStore.save::.mkdir": 1,
    # the machine: Flatpak's marker, browsers and their profiles, the scrapers folder, packaged data
    "linux_registration.py::sandbox_name::.exists": 1,
    "scraping/browser_drivers.py::find_browser_binary::.is_file": 1,
    "scraping/browser_drivers.py::login_command::.mkdir": 1,
    "scraping/browser_drivers.py::start_driver::.mkdir": 1,
    "scraping/browser_fetcher.py::PersonaBrowser.reset::shutil.rmtree": 1,
    "scraping/registry.py::ScraperRegistry.__scan::.glob": 1,
    "scraping/registry.py::ScraperRegistry.__scan::.is_dir": 1,
    "scraping/results.py::<module>::.read_text": 1,
    # files the user names for the app to write: a `.rehuco` view, an exported report, a scrape's JSON
    "dialogs/import_legacy_catalog_wizard.py::ImportLegacyCatalogWizard.__on_save::.write_text": 1,
    "main_window.py::MainWindow.__on_new_rehuco::.exists": 1,
    "scraping/cli.py::scrape_url_to_json::.write_text": 1,
    "scraping/cli.py::write_scrape_schema::.write_text": 1,
}
"""Out of scope: files the app keeps for itself or the user names for it, not a resource's files."""

NOT_FILE_ACCESS: Final = {
    "fields/widgets/image_source.py::decode_image::QImageReader": 1,
    "fields/widgets/image_source.py::image_size::QImageReader": 1,
    "fields/widgets/image_source.py::reading_buffer::.open": 1,
    "rehuco/roots_management.py::_has_checksum::rehuco_core.DirectoryClassifier": 1,
    "rehuco/roots_management.py::_manages::rehuco_core.DirectoryClassifier": 1,
    "rehuco/roots_panel.py::RootsPanel.__run::.open": 1,
}
"""Calls the scanner cannot tell from a file access, though they read memory (a ``QBuffer``), open a view, or only
name a listing that was already read (``DirectoryClassifier.reclassify``)."""

ALLOWED: Final = {**TO_MIGRATE, **APP_LOCAL, **NOT_FILE_ACCESS}


def test_the_allowlists_do_not_share_a_site() -> None:
    """A site is allowed for one reason only.

    **Test steps:**

    * join the three allowlists
    * verify no key appears in more than one, so none can hide in the out-of-scope lists
    """
    assert len(ALLOWED) == len(TO_MIGRATE) + len(APP_LOCAL) + len(NOT_FILE_ACCESS)


def test_the_agent_makes_no_direct_resource_file_access_beyond_the_allowlist() -> None:
    """No agent module reads or touches a resource's files except where the allowlist says (#415).

    **Test steps:**

    * scan every hand-written module under ``rehuco_agent`` for the calls the issue names
    * verify none is beyond what the allowlists grant its file, scope and call
    * verify every allowlist entry still matches a site, so a migrated one has been deleted
    """
    unlisted, stale = compare_with_allowed(scan_folder(AGENT_DIR), ALLOWED)

    assert not unlisted, (
        "direct file access outside the access seam -- go through ResourceAccess, or (if it is not a resource's "
        "file) add it to APP_LOCAL with its reason:\n" + "\n".join(unlisted)
    )
    assert not stale, "allowlist entries that no longer match a site -- delete them:\n" + "\n".join(stale)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("open(path)", ["open"]),
        ("path.read_text()\npath.read_bytes()", [".read_text", ".read_bytes"]),
        ("folder.iterdir()\nfolder.rglob('*')\nfolder.glob('*')", [".iterdir", ".rglob", ".glob"]),
        ("path.stat()\npath.exists()\npath.is_file()\npath.is_dir()", [".stat", ".exists", ".is_file", ".is_dir"]),
        ("path.write_text('')\npath.mkdir()\npath.unlink()", [".write_text", ".mkdir", ".unlink"]),
        ("import os\nos.scandir(p)\nos.path.exists(p)\nos.getcwd()", ["os.scandir", "os.path.exists"]),
        ("import zipfile\nzipfile.ZipFile(p)", ["zipfile.ZipFile"]),
        ("import shutil\nshutil.move(a, b)\nshutil.which('x')", ["shutil.move"]),
        ("from zipfile import ZipFile\nZipFile(p)", ["zipfile.ZipFile"]),
        ("from shutil import copy2 as copy\ncopy(a, b)", ["shutil.copy2"]),
        (
            "QImage(path)\nQPixmap(str(path))\nQImageReader(path)\nQFile(path)",
            ["QImage", "QPixmap", "QImageReader", "QFile"],
        ),
        ("QImage(size, fmt)\nQPixmap(QSize(1, 2))\nQPixmap(1, 2)\nQImage()", []),
        ("LogScope.open(path)\nCatalogCache.open(path)", []),
        ("name.replace('a', 'b')\ncoordinator.rename(a, b)\nmove(a, b)\nos.environ.get('X')", []),
        ("from rehuco_core import load_tc\nload_tc(p)", ["rehuco_core.load_tc"]),
        ("from rehuco_core import RehuDocument\nRehuDocument.load(p)", ["rehuco_core.RehuDocument.load"]),
        ("from rehuco_core import DEFAULT_DELETER\nDEFAULT_DELETER.delete(p)", ["rehuco_core.DEFAULT_DELETER.delete"]),
        ("from rehuco_core import load_tc as load\nload(p)", ["rehuco_core.load_tc"]),
        ("from rehuco_core.tc_document import load_tc\nload_tc(p)", ["rehuco_core.load_tc"]),
        ("from rehuco_core import stage_image\nstage_image(folder, name, data)", []),
        ("import rehuco_core\nrehuco_core.load_tc(p)", ["rehuco_core.load_tc"]),
        ("from rehuco_core import checksum_record_path\nchecksum_record_path(p)", []),
        ("from rehuco_core import RehuDocument\nRehuDocument.new()", []),
        (
            "from borco_pyside.recycle_bin import recycle_bin\nrecycle_bin(p)",
            ["borco_pyside.recycle_bin.recycle_bin"],
        ),
    ],
)
def test_the_scanner_recognises_the_calls_the_issue_names(source: str, expected: list[str]) -> None:
    """The scanner flags each spelling of direct file access and nothing that merely looks like one.

    **Test steps:**

    * scan a snippet of source
    * verify the calls found are exactly the expected ones, in order
    """
    assert [site.call for site in scan_source(source, "module.py")] == expected


def test_a_site_is_named_by_its_scope_and_not_its_line() -> None:
    """A site's key carries the file, the enclosing classes and functions, and the call -- never the line.

    **Test steps:**

    * scan a snippet with a call at module level, in a function, and in a method of a class nested in a function
    * verify each key names its scope, so moving a line does not change it
    """
    source = (
        "path.stat()\n\ndef read():\n    path.stat()\n    class Reader:\n        def load(self):\n            open(p)\n"
    )

    assert [site.key for site in scan_source(source, "a/b.py")] == [
        "a/b.py::<module>::.stat",
        "a/b.py::read::.stat",
        "a/b.py::read.Reader.load::open",
    ]


def test_the_comparison_reports_a_new_site_and_a_stale_entry() -> None:
    """A site beyond its allowed count is reported, and so is an entry granting more than exists.

    **Test steps:**

    * scan a snippet making the same call twice in one scope and another call once
    * verify a count of one allows the first call and reports the second
    * verify an entry for a call the snippet never makes is reported stale
    """
    sites = scan_source("def read():\n    path.stat()\n    path.stat()\n    open(p)\n", "m.py")

    unlisted, stale = compare_with_allowed(
        sites, {"m.py::read::.stat": 1, "m.py::read::open": 1, "m.py::gone::.stat": 1}
    )

    assert unlisted == ["m.py:3: .stat in read"]
    assert stale == ["m.py::gone::.stat"]
