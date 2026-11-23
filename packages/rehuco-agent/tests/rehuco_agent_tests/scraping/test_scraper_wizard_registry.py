"""Tests for `ScraperWizardRegistry` and the saved queue's way back to a library scan (#683).

The scraper registry, whose scripts the wizards are found in, is tested by its own suite and stood in for here: a
module is a list of classes defined in this file.
"""

from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

from pytest_mock import MockerFixture
from rehuco_agent.scraping.library_scan_job import LIBRARY_SCAN_KIND, LibraryScanJob, LibraryScanTarget
from rehuco_agent.scraping.registry import (
    BUILTIN_SOURCE_LABEL,
    NOTHING_DECLARED_WARNING,
    LoadedScraperModule,
    ScraperRegistry,
    ScraperRow,
)
from rehuco_agent.scraping.role_report import RoleState
from rehuco_agent.scraping.scraper_wizard import ScraperWizard
from rehuco_agent.scraping.scraper_wizard_registry import (
    ScraperWizardRegistry,
    register_library_scan_kind,
    shared_scraper_wizard_registry,
)
from rehuco_core import PersistableTaskJob, TaskJobRegistry

# stand-ins for what a script defines: the protocol's members are the whole of each
# pylint: disable=missing-function-docstring,too-few-public-methods


class ShopWizard:
    """A wizard that is a site too."""

    key = "shop"
    label = "Folder Shop"
    name = "Folder Shop"

    def create_job(self, target: LibraryScanTarget) -> PersistableTaskJob:
        raise NotImplementedError

    def session(self, lease: object) -> object:
        raise NotImplementedError


class PlainWizard:
    """A wizard that names no library."""

    key = "plain"
    label = "Plain"

    def create_job(self, target: LibraryScanTarget) -> PersistableTaskJob:
        raise NotImplementedError


class BuiltinShop(PlainWizard):  # pylint: disable=abstract-method
    """A shipped wizard sharing the folder wizard's key."""

    key = "shop"
    label = "Built-in Shop"


class OtherBuiltin(PlainWizard):  # pylint: disable=abstract-method
    """A shipped wizard of a key of its own."""

    key = "other"
    label = "Other Shop"


class NeedsArgs(PlainWizard):  # pylint: disable=abstract-method
    """Cannot be built bare."""

    key = "args"

    def __init__(self, required: str) -> None:
        self.required = required


class NoLabel:
    """Declares itself a wizard and has no label."""

    key = "nolabel"

    def create_job(self, target: LibraryScanTarget) -> PersistableTaskJob:
        raise NotImplementedError


class NumberKey(PlainWizard):  # pylint: disable=abstract-method
    """Its key is no text."""

    key = 7  # pyright: ignore[reportAssignmentType]


class BrokenShop(PlainWizard):  # pylint: disable=abstract-method
    """Claims the shop's key and has no usable label."""

    key = "shop"
    label = ""


class Helper:
    """Never meant to be a wizard."""

    key = "helper"


# pylint: enable=missing-function-docstring,too-few-public-methods


def key_of(candidate: type) -> str:
    """A class's identity, as both registries spell it.

    :param candidate: the class.
    :returns: its key.
    """
    return f"{candidate.__module__}.{candidate.__qualname__}"


def module(name: str, *classes: type) -> LoadedScraperModule:
    """A script the scraper registry loaded, defining ``classes``.

    :param name: the file's name.
    :param classes: the classes it defines.
    :returns: the module.
    """
    return LoadedScraperModule(path=Path(name), scrapers=(), error=None, classes=classes)


def scripts_of(*modules: LoadedScraperModule) -> Mock:
    """A scraper registry that loaded ``modules``.

    :param modules: the scripts.
    :returns: the stand-in.
    """
    scripts = Mock(spec=ScraperRegistry)
    scripts.modules = modules
    return scripts


def row(source: str, candidate: type | None = None, **fields: object) -> ScraperRow:
    """A row as the scraper registry builds one.

    :param source: the file's name, or the built-ins' label.
    :param candidate: the class the row is of; ``None`` for a file's own row.
    :param fields: the fields that differ from an empty row's.
    :returns: the row.
    """
    empty = ScraperRow(
        key=None,
        label="",
        publisher="",
        site_name="",
        site_url="",
        source=source,
        needs_browser=False,
        error=None,
        class_key=None if candidate is None else key_of(candidate),
    )
    return replace(empty, **fields)


# region Finding a wizard


def test_a_wizard_is_found_by_its_key_and_listed_for_the_dialog() -> None:
    """The built-ins are the wizards a registry over no script offers (#683).

    **Test steps:**

    * build a registry over two built-in wizards and no script
    * verify the wizards are listed in order and each is found by its key
    * verify an unknown key finds none
    """
    registry = ScraperWizardRegistry(scripts_of(), builtins=(BuiltinShop, OtherBuiltin))

    assert [wizard.label for wizard in registry.wizards] == ["Built-in Shop", "Other Shop"]
    assert isinstance(registry.find("other"), OtherBuiltin)
    assert isinstance(registry.find("shop"), ScraperWizard)
    assert registry.find("nothing") is None


def test_a_folder_wizard_wins_over_a_built_in_of_the_same_key() -> None:
    """The user's script is offered in place of the shipped wizard it shares a key with (#683).

    **Test steps:**

    * build a registry over a script whose wizard's key a built-in has too
    * verify the key finds the script's wizard, and the dialog lists it once, then the other built-in
    """
    scripts = scripts_of(module("shop.py", ShopWizard))

    registry = ScraperWizardRegistry(scripts, builtins=(BuiltinShop, OtherBuiltin))

    assert isinstance(registry.find("shop"), ShopWizard)
    assert [wizard.label for wizard in registry.wizards] == ["Folder Shop", "Other Shop"]


def test_a_class_that_cannot_be_a_wizard_is_not_offered_and_stops_nothing() -> None:
    """A wizard needing arguments, one lacking a member, one whose key is no text and a class never meant as one
    are none of them offered, and the wizard after them still is (#683).

    **Test steps:**

    * build a registry over a script defining those four and a good one
    * verify only the good wizard is offered
    """
    scripts = scripts_of(module("mixed.py", Helper, NeedsArgs, NoLabel, NumberKey, PlainWizard))

    registry = ScraperWizardRegistry(scripts, builtins=())

    assert [wizard.key for wizard in registry.wizards] == ["plain"]


def test_the_scripts_are_looked_through_again_once_the_scraper_registry_reloaded() -> None:
    """A wizard added to the folder is offered after the scraper registry's reload, with no call of this registry's
    own; until then the wizards found are kept (#683).

    **Test steps:**

    * build a registry over one script and find its wizard twice
    * verify the same object is found both times
    * have the scraper registry hold a new scan with a second script
    * verify the new wizard is found, and the first is built anew
    """
    scripts = scripts_of(module("shop.py", ShopWizard))
    registry = ScraperWizardRegistry(scripts, builtins=())
    first = registry.find("shop")
    assert first is not None
    assert registry.find("shop") is first

    scripts.modules = (module("plain.py", PlainWizard), module("shop.py", ShopWizard))

    assert registry.find("plain") is not None
    assert registry.find("shop") is not first


def test_the_scan_reads_through_a_wizard_that_is_a_site() -> None:
    """The site lookup a scan is built with answers a wizard that names a library, and no other (#683).

    **Test steps:**

    * build a registry over a wizard with a site's members and one without
    * verify the first is found as a site, the second and an unknown key are not
    """
    registry = ScraperWizardRegistry(scripts_of(module("both.py", PlainWizard, ShopWizard)), builtins=())

    site = registry.site("shop")

    assert site is not None
    assert site.name == "Folder Shop"
    assert registry.find("plain") is not None
    assert registry.site("plain") is None
    assert registry.site("nothing") is None


# endregion

# region The Scrapers table's rows


def test_a_class_that_is_a_scraper_and_a_wizard_keeps_one_row() -> None:
    """The wizard's state joins the row the scraper registry made for the same class (#683).

    **Test steps:**

    * build a registry over a script whose class is a wizard
    * merge it into that class's scraper row
    * verify one row comes back, the scraper's, saying the wizard works
    """
    registry = ScraperWizardRegistry(scripts_of(module("shop.py", ShopWizard)), builtins=())
    scraper_row = row("shop.py", ShopWizard, key=key_of(ShopWizard), site_name="Shop", scraper=RoleState.OK)

    merged = registry.merged_rows((scraper_row,))

    assert merged == (
        row("shop.py", ShopWizard, key=key_of(ShopWizard), site_name="Shop", scraper=RoleState.OK, wizard=RoleState.OK),
    )


def test_a_class_that_is_only_a_wizard_gets_a_row_after_its_file_s_others() -> None:
    """A wizard beside a scraper in one file is listed after it and before the next file's rows, named by its
    label (#683).

    **Test steps:**

    * build a registry over a script defining a wizard, and a second script defining none
    * merge it into the first file's scraper row (of another class) and the second file's
    * verify the wizard's row sits between the two, with no scraper state and no key
    """
    registry = ScraperWizardRegistry(scripts_of(module("a.py", PlainWizard), module("b.py")), builtins=())
    first = row("a.py", Helper, key="a.Scraper", site_name="A", scraper=RoleState.OK)
    second = row("b.py", NoLabel, key="b.Scraper", site_name="B", scraper=RoleState.OK)

    merged = registry.merged_rows((first, second))

    assert merged == (first, row("a.py", PlainWizard, site_name="Plain", wizard=RoleState.OK), second)


def test_a_file_declaring_only_a_wizard_is_not_warned_of_declaring_nothing() -> None:
    """The warning row of a file with no scraper gives way to its wizard's row; a file with neither keeps it, and a
    file that failed to load keeps its error (#683).

    **Test steps:**

    * build a registry over a wizard-only script
    * merge it into three file rows: that script's warning, another's warning, a third's load error
    * verify the wizard's row replaced the first, and the other two are as they were
    """
    registry = ScraperWizardRegistry(scripts_of(module("shop.py", ShopWizard), module("empty.py")), builtins=())
    wizard_file = row("shop.py", warning=NOTHING_DECLARED_WARNING)
    empty_file = row("empty.py", warning=NOTHING_DECLARED_WARNING)
    broken_file = row("broken.py", error="SyntaxError: bad")

    merged = registry.merged_rows((broken_file, empty_file, wizard_file))

    assert merged == (broken_file, empty_file, row("shop.py", ShopWizard, site_name="Folder Shop", wizard=RoleState.OK))


def test_a_replaced_built_in_says_what_replaced_it() -> None:
    """A built-in whose key a script's wizard has is listed as replaced, with the script named as a note and no
    error; it is listed even when this build's scrapers have no row (#683).

    **Test steps:**

    * build a registry over a script's wizard and a built-in of the same key
    * merge it into no rows at all, and into the script's own warning row
    * verify the built-in's row both times: replaced, the note naming the script, no error
    """
    registry = ScraperWizardRegistry(scripts_of(module("shop.py", ShopWizard)), builtins=(BuiltinShop,))
    replaced = row(
        BUILTIN_SOURCE_LABEL,
        BuiltinShop,
        site_name="Built-in Shop",
        wizard=RoleState.OVERRIDDEN_OK,
        note="Replaced by the one in shop.py",
    )
    offered = row("shop.py", ShopWizard, site_name="Folder Shop", wizard=RoleState.OK)

    assert registry.merged_rows(()) == (offered, replaced)
    assert registry.merged_rows((row("shop.py", warning=NOTHING_DECLARED_WARNING),)) == (offered, replaced)


def test_a_broken_wizard_s_row_says_what_is_wrong() -> None:
    """A class that declares itself a wizard and cannot be one is listed with the reason as its error, named by its
    class when its label cannot be read; a fault of its scraper's is kept ahead (#683).

    **Test steps:**

    * build a registry over a script whose wizards need arguments, lack a label and name a number as key
    * merge it into a broken scraper's row of the first class
    * verify each row's state, name and error
    """
    registry = ScraperWizardRegistry(scripts_of(module("bad.py", NeedsArgs, NoLabel, NumberKey)), builtins=())
    scraper_row = row(
        "bad.py", NeedsArgs, site_name="NeedsArgs", scraper=RoleState.ERROR, error="NeedsArgs lacks matches"
    )

    rows = registry.merged_rows((scraper_row,))
    assert len(rows) == 3
    needs_args, no_label, number_key = rows[0], rows[1], rows[2]

    assert needs_args.wizard is RoleState.ERROR
    assert needs_args.scraper is RoleState.ERROR
    assert needs_args.error is not None
    assert needs_args.error.startswith("NeedsArgs lacks matches; NeedsArgs cannot be set up with no arguments")
    assert (no_label.site_name, no_label.wizard, no_label.error) == ("NoLabel", RoleState.ERROR, "NoLabel lacks label")
    assert (number_key.site_name, number_key.wizard) == ("Plain", RoleState.ERROR)
    assert number_key.error == "NumberKey's key is not a text"


def test_a_broken_wizard_whose_key_another_has_is_both_broken_and_replaced() -> None:
    """A wizard that cannot be used and whose key a working one claims is listed as both, its fault first (#683).

    **Test steps:**

    * build a registry over a working wizard and a later one of the same key with an empty label
    * verify the later one's row: broken and replaced, named by its class, the error saying both
    * verify the key still finds the working one
    """
    registry = ScraperWizardRegistry(scripts_of(module("a.py", ShopWizard), module("b.py", BrokenShop)), builtins=())

    rows = registry.merged_rows(())

    assert rows[1] == row(
        "b.py",
        BrokenShop,
        site_name="BrokenShop",
        wizard=RoleState.OVERRIDDEN_ERROR,
        error="BrokenShop's label is not a text; Replaced by the one in a.py",
    )
    assert isinstance(registry.find("shop"), ShopWizard)


# endregion

# region The saved queue


def test_a_saved_library_scan_is_restored_with_its_site_from_the_shared_registry(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    """The kind is registered, so the queue file brings a scan back reading through the installed wizard (#683).

    **Test steps:**

    * stand in a shared registry holding a wizard, and a registry of job kinds of its own
    * register the library scan kind twice
    * restore a saved scan of that wizard's key
    * verify one kind is registered, and the job is a scan whose row names the wizard's site
    """
    jobs = TaskJobRegistry()
    mocker.patch("rehuco_agent.scraping.scraper_wizard_registry.DEFAULT_TASK_JOB_REGISTRY", jobs)
    mocker.patch(
        "rehuco_agent.scraping.scraper_wizard_registry.shared_scraper_wizard_registry",
        return_value=ScraperWizardRegistry(scripts_of(module("shop.py", ShopWizard)), builtins=()),
    )
    state = LibraryScanTarget("shop", uuid4(), "Assets", tmp_path / ".rehuroot", tmp_path / ".rehudb").to_state()

    register_library_scan_kind()
    register_library_scan_kind()
    job = jobs.create(LIBRARY_SCAN_KIND, state)

    assert jobs.kinds == (LIBRARY_SCAN_KIND,)
    assert isinstance(job, LibraryScanJob)
    assert job.label == "Scan the Folder Shop library into Assets"


def test_shared_scraper_wizard_registry_is_a_singleton(mocker: MockerFixture) -> None:
    """The shared accessor returns the same instance every call, built over the shared scraper registry (#683).

    **Test steps:**

    * stand in the shared scraper registry, holding one wizard's script
    * call `shared_scraper_wizard_registry` twice
    * verify both calls return the same object, which finds that wizard
    """
    shared_scraper_wizard_registry.cache_clear()
    mocker.patch(
        "rehuco_agent.scraping.scraper_wizard_registry.shared_scraper_registry",
        return_value=scripts_of(module("shop.py", ShopWizard)),
    )

    try:
        shared = shared_scraper_wizard_registry()

        assert shared is shared_scraper_wizard_registry()
        assert shared.find("shop") is not None
    finally:
        shared_scraper_wizard_registry.cache_clear()


# endregion
