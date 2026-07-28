"""Tests for IconTheme: installing, checking and removing an icon in the per-user hicolor theme."""

from typing import Final

from borco_core.platforms.linux import icon_theme
from borco_core.platforms.linux.icon_theme import IconTheme

from .conftest import DATA_HOME, FakeXdg

NAME: Final = "org.example.app"
DATA: Final = b'<svg xmlns="http://www.w3.org/2000/svg"/>'


def test_path_follows_the_theme_layout(fake_xdg: FakeXdg) -> None:
    """A scalable application icon lands in ``<data home>/icons/hicolor/scalable/apps/<name>.svg``.

    **Test steps:**

    * ask for the icon's path with the defaults
    * verify every level of the theme layout is in it
    """
    del fake_xdg

    expected = (
        DATA_HOME
        / icon_theme.DIRECTORY
        / icon_theme.THEME
        / icon_theme.SCALABLE_SIZE
        / icon_theme.APPLICATIONS_CONTEXT
        / f"{NAME}.{icon_theme.SVG_EXTENSION}"
    )
    assert IconTheme.path(NAME) == expected


def test_path_honours_a_different_size_and_context(fake_xdg: FakeXdg) -> None:
    """A raster icon in another context goes where those arguments say.

    **Test steps:**

    * ask for a ``48x48`` ``mimetypes`` PNG
    * verify the size, context and extension all changed
    """
    del fake_xdg

    path = IconTheme.path(NAME, size="48x48", context="mimetypes", extension="png")

    assert path.parent.name == "mimetypes"
    assert path.parent.parent.name == "48x48"
    assert path.name == f"{NAME}.png"


def test_install_writes_the_icon(fake_xdg: FakeXdg) -> None:
    """``install`` writes the bytes verbatim to the themed path.

    **Test steps:**

    * install the icon
    * verify the file holds exactly the bytes given
    """
    IconTheme.install(NAME, DATA)

    assert fake_xdg.files[IconTheme.path(NAME)] == DATA


def test_install_refreshes_no_cache(fake_xdg: FakeXdg) -> None:
    """Installing an icon runs no update command -- a per-user hicolor directory is read directly.

    **Test steps:**

    * install the icon
    * verify no cache-refresh command was invoked
    """
    IconTheme.install(NAME, DATA)

    assert fake_xdg.update_calls == []


def test_is_installed_is_true_after_install(fake_xdg: FakeXdg) -> None:
    """A freshly-installed icon reports itself installed.

    **Test steps:**

    * install the icon
    * verify ``is_installed`` reports ``True`` for the same bytes
    """
    del fake_xdg

    IconTheme.install(NAME, DATA)

    assert IconTheme.is_installed(NAME, DATA)


def test_is_installed_is_false_when_nothing_is_there(fake_xdg: FakeXdg) -> None:
    """An icon that was never installed reports ``False`` rather than raising.

    **Test steps:**

    * verify ``is_installed`` reports ``False`` against an empty data home
    """
    del fake_xdg

    assert not IconTheme.is_installed(NAME, DATA)


def test_is_installed_is_false_when_the_bytes_differ(fake_xdg: FakeXdg) -> None:
    """An icon left by an older version doesn't count as installed -- re-registering refreshes it.

    **Test steps:**

    * install the icon, then check against different bytes
    * verify ``is_installed`` reports ``False``
    """
    del fake_xdg
    IconTheme.install(NAME, DATA)

    assert not IconTheme.is_installed(NAME, b"<svg/>")


def test_remove_deletes_the_icon(fake_xdg: FakeXdg) -> None:
    """``remove`` deletes exactly the installed file.

    **Test steps:**

    * install the icon, then remove it
    * verify the file is gone
    """
    IconTheme.install(NAME, DATA)

    IconTheme.remove(NAME)

    assert IconTheme.path(NAME) not in fake_xdg.files
