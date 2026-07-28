"""Rehuco's own Linux XDG desktop-entry/MIME identity and registration (#209).

The mirror image of `rehuco_agent.windows_registration`: shared by the CLI's
``--register``/``--unregister`` (``__main__.py``) and the settings dialog's Desktop Integration
page, both driving the same identity constants through the same register/unregister/is_registered
orchestration.

Unlike the Windows module this one is importable everywhere -- it is ``pathlib``/``subprocess``
underneath, not ``winreg`` -- so no call site has to gate its import. Its *effects* are still
Linux-only, and both call sites reach it only from a ``sys.platform == "linux"`` branch.

**On Linux this is the only association path there is.** No Briefcase Linux backend emits a
``MimeType=`` line or a MIME package, and neither shipping channel -- ``uv tool install`` or the
AppImage -- registers anything by itself ([[packaging-deployment#linux-format]]). So "double-click
a ``.rehu`` and it opens" on Linux is exactly what this module does, rather than a convenience on
top of an installer that already did it.
"""

import logging
import os
import sys
from pathlib import Path
from typing import Final

from borco_core.platforms.linux.desktop_entry import DesktopEntry
from borco_core.platforms.linux.icon_theme import IconTheme
from borco_core.platforms.linux.mime_package import MimePackage

LOG: Final = logging.getLogger(__name__)

DESKTOP_FILE_NAME: Final = "io.github.borco.rehuco-agent"
"""Desktop file id: the ``.desktop`` basename, the icon name, and the ``StartupWMClass``.

Reverse-DNS, matching Briefcase's ``bundle`` plus app name -- the same identity the macOS bundle
identifier is built from ([[packaging-deployment#app-identity]]). It is also what
``QGuiApplication.setDesktopFileName()`` is given (`rehuco_agent.app`), which is what lets the
Wayland ``app_id`` and the X11 ``WM_CLASS`` resolve back to the entry this module writes."""

APPLICATION_NAME: Final = "Rehuco"
"""User-visible application name in the launcher -- matching Briefcase's ``formal_name``."""

COMMENT: Final = "View and edit rehuco resource documents"
"""One-line description shown as the launcher entry's tooltip."""

CATEGORIES: Final = ("Utility",)
"""Freedesktop menu categories the launcher entry is filed under."""

MIME_TYPE: Final = "application/x-rehuco"
"""MIME type defined for ``.rehu``/``.tc`` -- the same value Briefcase's macOS ``document_type``
declares, so the two platforms name the format identically."""

MIME_FILE_NAME: Final = "application-x-rehuco"
"""Basename of the MIME package XML: :data:`MIME_TYPE` with its slash replaced, by convention."""

MIME_COMMENT: Final = "Rehuco Resource"
"""Human-readable type name file managers show -- the counterpart of Windows' ``FRIENDLY_NAME``."""

EXTENSIONS: Final = ("rehu", "tc")
"""File extensions (each without the leading dot) claimed by :data:`MIME_TYPE` -- ``.tc`` gets the
same handler as ``.rehu`` so a legacy file opens straight into its locked view
([[acquisition-tooling#tc-to-rehu]]), exactly as on Windows."""

ICON_RESOURCE: Final = ":/icons/rehuco-agent.svg"
"""qrc path to the app icon installed into the ``hicolor`` theme under :data:`DESKTOP_FILE_NAME`."""

APPIMAGE_VARIABLE: Final = "APPIMAGE"
"""Environment variable an AppImage runtime exports: the absolute path of the file the user ran."""

SNAP_VARIABLE: Final = "SNAP"
"""Environment variable set inside a Snap's confinement."""

FLATPAK_MARKER: Final = Path("/.flatpak-info")
"""File present inside a Flatpak sandbox and nowhere else."""

SANDBOXED_BLOCKER: Final = (
    "Cannot register/unregister -- running inside {sandbox}, where the desktop entry belongs to "
    "the package rather than to the app."
)
"""Why registration is refused inside a sandbox, with the sandbox's name."""

NOT_AN_EXECUTABLE_BLOCKER: Final = (
    "Cannot register/unregister from {path} -- not an executable; run `uv sync` first, or use the "
    "installed rehuco-agent command, not `python -m rehuco_agent`."
)
"""Why registration is refused from a source checkout with no venv shim to fall back to, with the
offending path."""


def executable_path() -> Path:
    """The path a desktop entry's ``Exec`` must launch to start this app again.

    Resolved from :data:`APPIMAGE_VARIABLE` when set; failing that, from ``sys.argv[0]`` -- upgraded
    to the venv's own ``rehuco-agent`` console-script shim when ``sys.argv[0]`` is a ``.py`` source
    path (``python -m rehuco_agent``, or running ``__main__.py`` directly) and that shim exists.
    ``uv sync``/``pip install -e .`` always installs it next to the interpreter actually running
    this process (``sys.executable``), so this is never a guess -- if it is there, it is the real
    console-script entry point, already runnable, no build step involved
    ([[packaging-deployment#linux-format]]).

    Inside an AppImage both ``sys.executable`` and ``__file__`` point into ``$APPDIR``, a temporary
    mount that ceases to exist when the process exits -- an entry written from either is dead the
    moment it is written. Outside one, ``sys.argv[0]`` is the installed ``rehuco-agent`` shim (e.g.
    ``~/.local/bin/rehuco-agent``), never ``uvx``, so a double-click resolves no version and touches
    no network.

    The AppImage path is taken verbatim rather than resolved: it is already absolute, and it is the
    file the *user* launched -- resolving it through a symlink would record a path they never chose.

    :returns: the AppImage's own path, the venv's console-script shim, or the resolved ``sys.argv[0]``.
    """
    appimage = os.environ.get(APPIMAGE_VARIABLE)
    if appimage:
        return Path(appimage)
    argv0 = Path(sys.argv[0]).resolve()
    if argv0.suffix == ".py":
        venv_shim = Path(sys.executable).with_name("rehuco-agent")
        if os.access(venv_shim, os.X_OK):
            return venv_shim
    return argv0


def is_running_from_executable(exe_path: Path) -> bool:
    """Whether ``exe_path`` is something a desktop entry could actually launch.

    The Linux counterpart of Windows' "not running from a real ``.exe``": ``python -m rehuco_agent``
    (or running ``__main__.py`` directly) makes ``sys.argv[0]`` the source file, and an ``Exec=``
    pointing at a non-executable ``.py`` is an entry the desktop silently fails to start. Both
    halves are checked -- the suffix catches the source-checkout case even where the file happens
    to carry the execute bit.

    :param exe_path: the path to check, typically :func:`executable_path`'s result.
    :returns: whether ``exe_path`` is a non-``.py`` file the user may execute.
    """
    return exe_path.suffix != ".py" and os.access(exe_path, os.X_OK)


def sandbox_name() -> str | None:
    """The sandbox confining this process, if any.

    Inside Flatpak or Snap the app cannot write the host's XDG directories at all, and association
    is the package's job instead -- so registration must say so rather than write files into the
    sandbox and report success. Neither is a format rehuco ships
    ([[packaging-deployment#linux-format]] rules both out), but nothing stops a third party from
    repackaging, and a false "Registered." is worse than an honest refusal.

    :returns: ``"Flatpak"``, ``"Snap"``, or ``None`` when unconfined.
    """
    if FLATPAK_MARKER.exists():
        return "Flatpak"
    if os.environ.get(SNAP_VARIABLE):
        return "Snap"
    return None


def registration_blocker(exe_path: Path) -> str | None:
    """Why registering from ``exe_path`` cannot work here, as a sentence, or ``None`` when it can.

    Shared by both call sites so the CLI's stderr message and the settings page's status label
    cannot drift: the page disables its buttons and shows this text, the CLI prints it and exits
    non-zero.

    :param exe_path: the path that would be registered, typically :func:`executable_path`'s result.
    :returns: the reason registration is refused, or ``None`` if nothing blocks it.
    """
    blocker = unregistration_blocker()
    if blocker is not None:
        return blocker
    if not is_running_from_executable(exe_path):
        return NOT_AN_EXECUTABLE_BLOCKER.format(path=exe_path)
    return None


def unregistration_blocker() -> str | None:
    """Why unregistering cannot work here, as a sentence, or ``None`` when it can.

    Unlike :func:`registration_blocker`, this never depends on an executable path -- :func:`unregister`
    itself takes none, since it only removes fixed per-user files. Only the sandbox check applies:
    inside Flatpak/Snap the app cannot touch the host's XDG directories at all, register or not.

    :returns: the reason unregistering is refused, or ``None`` if nothing blocks it.
    """
    sandbox = sandbox_name()
    if sandbox is not None:
        return SANDBOXED_BLOCKER.format(sandbox=sandbox)
    return None


def launch_command(exe_path: Path) -> str:
    """The ``Exec`` value launching ``exe_path`` with the files the user opened.

    ``%F`` (a list of local paths), not ``%U``: every path this app opens is a local file, a
    resource directory or an archive ([[data-model#resource-scoping]]), and a URL it cannot read
    would only fail later. The path is quoted because the desktop-entry spec requires quoting for
    reserved characters and permits it otherwise, so one form is correct for every path.

    :param exe_path: the executable to launch.
    :returns: the full ``Exec`` value.
    """
    return f'"{exe_path}" %F'


def icon_data() -> bytes:
    """The app icon's bytes, read from the compiled Qt resources.

    Imported lazily, and only by the two functions that write or compare the installed icon: the
    icon lives nowhere but ``main_rc``, so reading it costs a ``PySide6.QtCore``/``QtGui`` import.
    The CLI's ``--register`` pays that on Linux where the Windows one does not -- there is no
    installer post-install script here to keep quiet and fast, only a user who typed the command
    ([[appendices.briefcase-packaging#windows]]).

    :returns: the icon file's full contents.
    """
    # pylint: disable-next=import-outside-toplevel
    from borco_pyside.theming import read_resource_bytes

    # pylint: disable-next=import-outside-toplevel,unused-import
    from . import main_rc  # noqa: F401  # registers :/icons/... resources

    return read_resource_bytes(ICON_RESOURCE)


def desktop_entry(exe_path: Path) -> DesktopEntry:
    """Rehuco's launcher entry, as it should look when registered to ``exe_path``.

    :param exe_path: the executable the entry launches.
    :returns: the entry -- built rather than written, so callers can install it or compare it.
    """
    return DesktopEntry(
        file_name=DESKTOP_FILE_NAME,
        name=APPLICATION_NAME,
        exec_command=launch_command(exe_path),
        comment=COMMENT,
        icon=DESKTOP_FILE_NAME,
        mime_types=(MIME_TYPE,),
        categories=CATEGORIES,
        startup_wm_class=DESKTOP_FILE_NAME,
    )


def mime_package() -> MimePackage:
    """Rehuco's MIME package, defining :data:`MIME_TYPE` over every extension in :data:`EXTENSIONS`.

    :returns: the package -- built rather than written, like :func:`desktop_entry`.
    """
    return MimePackage(
        file_name=MIME_FILE_NAME,
        mime_type=MIME_TYPE,
        comment=MIME_COMMENT,
        globs=tuple(f"*.{extension}" for extension in EXTENSIONS),
    )


def register(exe_path: Path) -> None:
    """Register ``exe_path`` as the ``.rehu``/``.tc`` handler for this user.

    Writes all three files a Linux association needs -- the desktop entry, the MIME package that
    makes its ``MimeType`` mean something, and the icon its ``Icon=`` names -- and refreshes both
    caches. Re-registering is the fix for every way the entry can go stale: a moved or renamed
    AppImage, a second install, or an app update that changed the icon.

    :param exe_path: the executable to register, typically :func:`executable_path`'s result.
    """
    IconTheme.install(DESKTOP_FILE_NAME, icon_data())
    mime_package().install()
    desktop_entry(exe_path).install()
    LOG.info("registered %s as the %s handler", exe_path, MIME_TYPE)


def unregister() -> None:
    """Remove exactly the three files :func:`register` wrote, and refresh both caches."""
    DesktopEntry.remove(DESKTOP_FILE_NAME)
    MimePackage.remove(MIME_FILE_NAME)
    IconTheme.remove(DESKTOP_FILE_NAME)
    LOG.info("unregistered the %s handler", MIME_TYPE)


def is_registered(exe_path: Path) -> bool:
    """Whether everything :func:`register` with this same ``exe_path`` would write is already in place.

    :param exe_path: same as :func:`register`.
    :returns: ``True`` iff the desktop entry, the MIME package and the icon all already match.
    """
    return (
        desktop_entry(exe_path).is_installed()
        and mime_package().is_installed()
        and IconTheme.is_installed(DESKTOP_FILE_NAME, icon_data())
    )


def registered_command() -> str | None:
    """The ``Exec`` value of the currently-installed desktop entry, if there is one.

    What distinguishes "not registered" from "registered, but pointing somewhere else" -- the
    ordinary state for an AppImage, which the user is free to move, rename or replace with a newer
    download, each of which silently invalidates the recorded path.

    :returns: the installed ``Exec`` value, or ``None`` when no entry is installed.
    """
    return DesktopEntry.installed_value(DESKTOP_FILE_NAME, "Exec")
