"""Tests for DesktopEntry: rendering, installing, reading back and removing a ``.desktop`` entry."""

from typing import Final

from borco_core.platforms.linux import desktop_entry
from borco_core.platforms.linux.desktop_entry import DesktopEntry

from .conftest import DATA_HOME, FakeXdg

FILE_NAME: Final = "org.example.app"
EXEC_COMMAND: Final = '"/fake/bin/app" %F'


def full_entry() -> DesktopEntry:
    """An entry with every optional field filled in.

    :returns: the entry under test.
    """
    return DesktopEntry(
        file_name=FILE_NAME,
        name="App",
        exec_command=EXEC_COMMAND,
        comment="An example application",
        icon=FILE_NAME,
        mime_types=("application/x-example",),
        categories=("Utility",),
        startup_wm_class=FILE_NAME,
    )


def minimal_entry() -> DesktopEntry:
    """An entry with only the fields a launcher entry cannot do without.

    :returns: the entry under test.
    """
    return DesktopEntry(file_name=FILE_NAME, name="App", exec_command=EXEC_COMMAND)


def test_path_is_under_the_per_user_applications_directory(fake_xdg: FakeXdg) -> None:
    """An entry lands in ``<data home>/applications/<file name>.desktop``.

    **Test steps:**

    * ask for the entry's path
    * verify it is the per-user applications directory plus the suffixed file name
    """
    del fake_xdg

    assert DesktopEntry.path(FILE_NAME) == DATA_HOME / desktop_entry.DIRECTORY / f"{FILE_NAME}{desktop_entry.SUFFIX}"


def test_content_renders_every_field(fake_xdg: FakeXdg) -> None:
    """A fully-specified entry renders the group header and one line per field.

    **Test steps:**

    * render a full entry
    * verify each key/value line is present
    """
    del fake_xdg

    content = full_entry().content()

    assert content.startswith(f"{desktop_entry.SECTION}\n")
    assert "Type=Application" in content
    assert "Name=App" in content
    assert "Comment=An example application" in content
    assert f"Exec={EXEC_COMMAND}" in content
    assert f"Icon={FILE_NAME}" in content
    assert "Categories=Utility;" in content
    assert "MimeType=application/x-example;" in content
    assert f"StartupWMClass={FILE_NAME}" in content
    assert content.endswith("StartupNotify=true\n")


def test_content_omits_the_optional_fields_when_empty(fake_xdg: FakeXdg) -> None:
    """An unset optional field is left out entirely, not written blank.

    ``Icon=`` with no value is a lookup for the empty icon name, not "no icon" -- so the key has
    to be absent rather than empty.

    **Test steps:**

    * render an entry with only the required fields
    * verify none of the optional keys appear at all
    """
    del fake_xdg

    content = minimal_entry().content()

    assert "Comment=" not in content
    assert "Icon=" not in content
    assert "Categories=" not in content
    assert "MimeType=" not in content
    assert "StartupWMClass=" not in content


def test_install_writes_the_entry_and_refreshes_the_cache(fake_xdg: FakeXdg) -> None:
    """``install`` writes the rendered content and rebuilds the MIME-to-application cache.

    **Test steps:**

    * install a full entry
    * verify the file holds exactly its rendered content
    * verify the cache-refresh command ran over the applications directory
    """
    entry = full_entry()

    entry.install()

    assert fake_xdg.files[DesktopEntry.path(FILE_NAME)] == entry.content().encode("utf-8")
    assert fake_xdg.update_calls == [(desktop_entry.UPDATE_COMMAND, (str(DesktopEntry.directory()),))]


def test_is_installed_is_true_after_install(fake_xdg: FakeXdg) -> None:
    """A freshly-installed entry reports itself installed.

    **Test steps:**

    * install a full entry
    * verify ``is_installed`` reports ``True``
    """
    del fake_xdg
    entry = full_entry()

    entry.install()

    assert entry.is_installed()


def test_is_installed_is_false_when_nothing_is_there(fake_xdg: FakeXdg) -> None:
    """An entry that was never installed reports ``False`` rather than raising.

    **Test steps:**

    * verify ``is_installed`` reports ``False`` against an empty data home
    """
    del fake_xdg

    assert not full_entry().is_installed()


def test_is_installed_is_false_when_the_content_differs(fake_xdg: FakeXdg) -> None:
    """An entry installed with a different ``Exec`` is not "already registered".

    This is what makes a moved AppImage detectable: the file is there, but not the one this
    identity would write.

    **Test steps:**

    * install an entry, then build the same identity with a different launch command
    * verify ``is_installed`` reports ``False``
    """
    del fake_xdg
    full_entry().install()

    moved = DesktopEntry(file_name=FILE_NAME, name="App", exec_command='"/somewhere/else/app" %F')

    assert not moved.is_installed()


def test_installed_value_reads_a_key_back(fake_xdg: FakeXdg) -> None:
    """``installed_value`` reads one key out of whatever entry is currently installed.

    **Test steps:**

    * install a full entry
    * read ``Exec`` back
    * verify it is the launch command that was written
    """
    del fake_xdg
    full_entry().install()

    assert DesktopEntry.installed_value(FILE_NAME, "Exec") == EXEC_COMMAND


def test_installed_value_is_none_when_nothing_is_installed(fake_xdg: FakeXdg) -> None:
    """With no entry on disk, every key reads as ``None`` -- the "not registered at all" signal.

    **Test steps:**

    * read ``Exec`` against an empty data home
    * verify it is ``None``
    """
    del fake_xdg

    assert DesktopEntry.installed_value(FILE_NAME, "Exec") is None


def test_installed_value_is_none_for_an_absent_key(fake_xdg: FakeXdg) -> None:
    """A key the installed entry never wrote reads as ``None``.

    **Test steps:**

    * install a minimal entry (no ``Icon``)
    * read ``Icon`` back
    * verify it is ``None``
    """
    del fake_xdg
    minimal_entry().install()

    assert DesktopEntry.installed_value(FILE_NAME, "Icon") is None


def test_remove_deletes_the_entry_and_refreshes_the_cache(fake_xdg: FakeXdg) -> None:
    """``remove`` deletes exactly the installed file and rebuilds the cache.

    **Test steps:**

    * install a full entry, then remove it
    * verify the file is gone and a second cache refresh ran
    """
    full_entry().install()

    DesktopEntry.remove(FILE_NAME)

    assert DesktopEntry.path(FILE_NAME) not in fake_xdg.files
    assert len(fake_xdg.update_calls) == 2
