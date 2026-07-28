"""Tests for MimePackage: rendering, installing and removing a shared-mime-info package."""

from typing import Final

from borco_core.platforms.linux import mime_package
from borco_core.platforms.linux.mime_package import MimePackage

from .conftest import DATA_HOME, FakeXdg

FILE_NAME: Final = "application-x-example"
MIME_TYPE: Final = "application/x-example"


def package(comment: str = "Example Resource") -> MimePackage:
    """The package under test.

    :param comment: the human-readable type name, so one test can pass text needing XML escaping.
    :returns: a package defining :data:`MIME_TYPE` over two globs.
    """
    return MimePackage(file_name=FILE_NAME, mime_type=MIME_TYPE, comment=comment, globs=("*.example", "*.ex"))


def test_path_is_under_the_per_user_mime_packages_directory(fake_xdg: FakeXdg) -> None:
    """A package lands in ``<data home>/mime/packages/<file name>.xml``.

    **Test steps:**

    * ask for the package's path
    * verify it is the per-user packages directory plus the suffixed file name
    """
    del fake_xdg

    expected = DATA_HOME / mime_package.DIRECTORY / mime_package.PACKAGES_DIRECTORY
    assert MimePackage.path(FILE_NAME) == expected / f"{FILE_NAME}{mime_package.SUFFIX}"


def test_database_directory_is_what_the_update_command_wants(fake_xdg: FakeXdg) -> None:
    """``update-mime-database`` takes the database root, not the packages directory inside it.

    **Test steps:**

    * ask for the database directory
    * verify it is ``<data home>/mime``, one level above the packages directory
    """
    del fake_xdg

    assert MimePackage.database_directory() == DATA_HOME / mime_package.DIRECTORY
    assert MimePackage.directory().parent == MimePackage.database_directory()


def test_content_declares_the_type_and_every_glob(fake_xdg: FakeXdg) -> None:
    """The rendered XML declares the namespace, the type, its comment and one glob per pattern.

    **Test steps:**

    * render the package
    * verify the declaration, namespace, type, comment and both globs are present
    """
    del fake_xdg

    content = package().content()

    assert content.startswith('<?xml version="1.0" encoding="UTF-8"?>\n')
    assert f'xmlns="{mime_package.NAMESPACE}"' in content
    assert f'<mime-type type="{MIME_TYPE}">' in content
    assert "<comment>Example Resource</comment>" in content
    assert '<glob pattern="*.example"/>' in content
    assert '<glob pattern="*.ex"/>' in content


def test_content_escapes_the_comment(fake_xdg: FakeXdg) -> None:
    """A comment containing XML metacharacters is escaped rather than emitted raw.

    **Test steps:**

    * render a package whose comment holds ``&`` and angle brackets
    * verify they arrive escaped and the raw form is absent
    """
    del fake_xdg

    content = package(comment="Fish & <chips>").content()

    assert "<comment>Fish &amp; &lt;chips&gt;</comment>" in content
    assert "<chips>" not in content


def test_install_writes_the_package_and_recompiles_the_database(fake_xdg: FakeXdg) -> None:
    """``install`` writes the rendered XML and recompiles the per-user MIME database.

    **Test steps:**

    * install the package
    * verify the file holds exactly its rendered content
    * verify the recompile ran over the database root
    """
    installed = package()

    installed.install()

    assert fake_xdg.files[MimePackage.path(FILE_NAME)] == installed.content().encode("utf-8")
    assert fake_xdg.update_calls == [(mime_package.UPDATE_COMMAND, (str(MimePackage.database_directory()),))]


def test_is_installed_is_true_after_install(fake_xdg: FakeXdg) -> None:
    """A freshly-installed package reports itself installed.

    **Test steps:**

    * install the package
    * verify ``is_installed`` reports ``True``
    """
    del fake_xdg
    installed = package()

    installed.install()

    assert installed.is_installed()


def test_is_installed_is_false_when_the_comment_differs(fake_xdg: FakeXdg) -> None:
    """A package installed by an older version, with a different comment, is not "already registered".

    **Test steps:**

    * install the package, then build the same identity with a different comment
    * verify ``is_installed`` reports ``False``
    """
    del fake_xdg
    package().install()

    assert not package(comment="Renamed Resource").is_installed()


def test_remove_deletes_the_package_and_recompiles_the_database(fake_xdg: FakeXdg) -> None:
    """``remove`` deletes exactly the installed file and recompiles the database.

    **Test steps:**

    * install the package, then remove it
    * verify the file is gone and a second recompile ran
    """
    package().install()

    MimePackage.remove(FILE_NAME)

    assert MimePackage.path(FILE_NAME) not in fake_xdg.files
    assert len(fake_xdg.update_calls) == 2
