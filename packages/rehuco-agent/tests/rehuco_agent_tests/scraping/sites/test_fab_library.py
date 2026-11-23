"""Tests for `FabLibrary` (#684): Fab as the wizard the dialog offers and the site a scan reads its library through."""

from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

from rehuco_agent.scraping.browser_fetcher import PersonaLease
from rehuco_agent.scraping.library_scan_job import LibraryScanJob, LibraryScanTarget
from rehuco_agent.scraping.library_site import LibrarySite
from rehuco_agent.scraping.registry import BUILTIN_SCRAPERS, ScraperRegistry
from rehuco_agent.scraping.role_report import RoleState
from rehuco_agent.scraping.scraper_wizard import ScraperWizard
from rehuco_agent.scraping.scraper_wizard_registry import BUILTIN_WIZARDS, ScraperWizardRegistry
from rehuco_agent.scraping.sites.fab_library import KEY, FabLibrary
from rehuco_agent.scraping.sites.fab_library_session import FabLibrarySession


def test_fab_is_a_wizard_and_a_site() -> None:
    """One class is the dialog's entry and the library the scan reads through.

    **Test steps:**

    * build the wizard
    * verify it satisfies both protocols, is saved under ``fab``, and names its site as the scraper's publisher
    """
    fab = FabLibrary()

    assert isinstance(fab, ScraperWizard) and isinstance(fab, LibrarySite)
    assert (fab.key, fab.label, fab.name) == ("fab", "Fab", "Fab")
    assert KEY == fab.key


def test_it_opens_a_library_session_on_the_lease() -> None:
    """A run's library is a session over the persona the scan leases.

    **Test steps:**

    * open the site's session on a lease
    * verify it is a Fab library session
    """
    assert isinstance(FabLibrary().session(Mock(spec=PersonaLease)), FabLibrarySession)


def test_it_creates_the_scan_job_that_reads_through_itself() -> None:
    """The job built for the dialog's choice scans the wizard chosen.

    **Test steps:**

    * create a job for a target
    * verify it is a library scan labeled for Fab and the root, and that it does not validate on its site: no folder
      is mapped to the root here, which is asked after the site is found
    """
    target = LibraryScanTarget("fab", uuid4(), "Assets", Path("assets.rehuroot"), Path("catalog.rehudb"))

    job = FabLibrary().create_job(target)

    assert isinstance(job, LibraryScanJob)
    assert job.label == "Scan the Fab library into Assets"
    assert "maps no folder" in str(job.validate())


def test_a_job_finds_no_other_site() -> None:
    """The job's lookup answers for Fab's key only.

    **Test steps:**

    * create a job for a target that names another site
    * verify it is told no such library scanner is installed
    """
    target = LibraryScanTarget("other", uuid4(), "Assets", Path("assets.rehuroot"), Path("catalog.rehudb"))

    assert "No library scanner named other" in str(FabLibrary().create_job(target).validate())


def test_this_build_ships_fab() -> None:
    """The dialog offers Fab with no script installed, and a scan finds it as its site.

    **Test steps:**

    * build a wizard registry over no scripts
    * verify Fab is the one built-in, offered under its key, and the registry's site for it is a `FabLibrary`
    """
    scripts = Mock(spec=ScraperRegistry)
    scripts.modules = ()
    registry = ScraperWizardRegistry(scripts)

    assert BUILTIN_WIZARDS == (FabLibrary,)
    assert [wizard.key for wizard in registry.wizards] == ["fab"]
    assert isinstance(registry.site("fab"), FabLibrary)


def test_fab_is_one_row_on_the_scrapers_page() -> None:
    """One class fills both roles, so the Scrapers table shows Fab once, as a scraper and a wizard.

    **Test steps:**

    * build the scraper registry over the built-ins and merge the wizard registry's rows into its own
    * verify one row is Fab's, and it is both a scraper and a wizard
    """
    scrapers = ScraperRegistry(builtins=BUILTIN_SCRAPERS)

    rows = ScraperWizardRegistry(scrapers).merged_rows(scrapers.rows)

    fab = [row for row in rows if row.site_name == "Fab"]
    assert len(fab) == 1
    assert fab[0].key is not None and fab[0].wizard is RoleState.OK
