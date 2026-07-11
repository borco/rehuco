"""Rehuco's own Windows HKCU file-association + context-menu identity and registration (#43, #47).

Shared by the CLI's ``--register``/``--unregister`` (``__main__.py``) and the settings dialog's
Registry page (#47) -- both drive the same identity constants through the same four-call
register/unregister/is_registered orchestration; duplicating that risked the two drifting apart
(e.g. a new registration type added to one call site and forgotten in the other).

Windows-only: imports ``borco_core.platforms.windows.*``, which do ``import winreg`` at module
scope. Both call sites import this module lazily, only inside an ``if sys.platform == "win32":``
branch, mirroring the gate those lower-level modules already require.
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Final

from borco_core.platforms.windows.directory_context_menu import DirectoryContextMenu
from borco_core.platforms.windows.file_association import FileAssociation
from borco_core.platforms.windows.file_extension_context_menu import FileExtensionContextMenu

PROGID: Final = "Rehuco.Document"
"""HKCU ProgID under ``Software\\Classes`` that owns the ``.rehu`` association."""

EXTENSION: Final = "rehu"
"""File extension (without the leading dot) registered to :data:`PROGID`."""

AUMID: Final = "borco.rehuco.agent"
"""Application User Model ID the running process declares via ``SetCurrentProcessExplicitAppUserModelID``."""

FRIENDLY_NAME: Final = "Rehuco Resource"
"""Human-readable type name shown in Explorer's Type column."""

DIRECTORY_SUB_KEY: Final = "Rehuco.OpenFolder"
"""HKCU sub-key under both ``Directory\\shell`` and ``Directory\\Background\\shell`` (#43)."""

DIRECTORY_MENU_TEXT: Final = "Open with Rehuco"
"""Menu label shown for both the folder and folder-background shell verbs."""

ARCHIVE_SUB_KEY: Final = "Rehuco.AddInfo"
"""HKCU sub-key under each archive extension's own ``SystemFileAssociations\\<ext>\\shell`` (#43)."""

ARCHIVE_MENU_TEXT: Final = "Create or Open Rehuco Info"
"""Menu label shown for the archive-file shell verb -- static (not per-file, see #43's discussion of
why a dynamic "Open foo.rehu"/"Create foo.rehu" label would need a full COM shell extension)."""


def is_running_from_exe(exe_path: Path) -> bool:
    """Whether ``exe_path`` looks like a real executable rather than a ``.py`` source path.

    ``python -m rehuco_agent`` (or running ``__main__.py`` directly) makes ``sys.argv[0]`` the
    source file, not a real ``.exe`` -- registering that would write a ``shell\\open\\command``
    Windows cannot meaningfully run and a ``DefaultIcon`` with no icon resource to extract from.

    :param exe_path: the path to check, typically ``Path(sys.argv[0]).resolve()``.
    :returns: whether ``exe_path``'s suffix is ``.exe``.
    """
    return exe_path.suffix.lower() == ".exe"


def register(exe_path: Path, archive_extensions: Sequence[str]) -> None:
    """Register ``exe_path`` as the ``.rehu`` handler, plus the folder/folder-background and
    archive-file shell verbs (#43).

    No separate icon path: falls back to ``exe_path``'s own icon (``DefaultIcon`` ``{exe_path},0``)
    -- correct either way, since the dev trampoline embeds this same icon in its own PE resources
    and the real packaged exe has no icon to fall back to regardless
    ([[packaging-deployment#app-identity]], deferred distribution polish).

    :param exe_path: the resolved path of the exe to register (the running one, or the one about to
        launch this app), e.g. ``Path(sys.argv[0]).resolve()``.
    :param archive_extensions: archive file extensions (each including the leading dot) that get
        the "Create or Open Rehuco Info" shell verb (``rehuco_agent.main_window.ARCHIVE_EXTENSIONS``).
    """
    icon = f"{exe_path},0"
    file_command = f'"{exe_path}" "%1"'
    directory_command = f'"{exe_path}"'
    FileAssociation.register(PROGID, EXTENSION, FRIENDLY_NAME, file_command, icon, AUMID)
    DirectoryContextMenu.register_folder(DIRECTORY_SUB_KEY, DIRECTORY_MENU_TEXT, directory_command, icon)
    DirectoryContextMenu.register_background(DIRECTORY_SUB_KEY, DIRECTORY_MENU_TEXT, directory_command, icon)
    FileExtensionContextMenu.register(archive_extensions, ARCHIVE_SUB_KEY, ARCHIVE_MENU_TEXT, directory_command, icon)


def unregister(archive_extensions: Sequence[str]) -> None:
    """Remove the ``.rehu`` handler and the folder/folder-background and archive-file shell verbs.

    :param archive_extensions: same as :func:`register`.
    """
    FileAssociation.unregister(PROGID, EXTENSION)
    DirectoryContextMenu.unregister_folder(DIRECTORY_SUB_KEY)
    DirectoryContextMenu.unregister_background(DIRECTORY_SUB_KEY)
    FileExtensionContextMenu.unregister(archive_extensions, ARCHIVE_SUB_KEY)


def is_registered(exe_path: Path, archive_extensions: Sequence[str]) -> bool:
    """Whether every registration :func:`register` with these same arguments would write is
    already exactly in place.

    :param exe_path: same as :func:`register`.
    :param archive_extensions: same as :func:`register`.
    :returns: ``True`` iff the file association, both directory verbs, and every archive
        extension's verb all already match.
    """
    icon = f"{exe_path},0"
    file_command = f'"{exe_path}" "%1"'
    directory_command = f'"{exe_path}"'
    return (
        FileAssociation.is_registered(PROGID, EXTENSION, FRIENDLY_NAME, file_command, icon, AUMID)
        and DirectoryContextMenu.is_folder_registered(DIRECTORY_SUB_KEY, DIRECTORY_MENU_TEXT, directory_command, icon)
        and DirectoryContextMenu.is_background_registered(
            DIRECTORY_SUB_KEY, DIRECTORY_MENU_TEXT, directory_command, icon
        )
        and FileExtensionContextMenu.is_registered(
            archive_extensions, ARCHIVE_SUB_KEY, ARCHIVE_MENU_TEXT, directory_command, icon
        )
    )
