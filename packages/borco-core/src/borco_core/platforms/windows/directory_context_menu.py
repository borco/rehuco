"""Generic Windows HKCU folder/directory-background shell-verb ("Open in <App>") registration.

Two independent verbs, mirroring Explorer's own distinction:

- **Folder** -- right-click a folder itself; registered under ``Directory\\shell``, launched as
  ``command "%1"`` (``%1`` is the clicked folder).
- **Background** -- right-click empty space inside a folder (no item under the cursor); registered
  under ``Directory\\Background\\shell``, launched as ``command "%V"`` (``%V`` is the background
  hive's own folder -- there is no clicked item to pass as ``%1`` there).

Same per-user (``HKEY_CURRENT_USER``), no-elevation approach as
:mod:`borco_core.platforms.windows.file_association`.
"""

import logging
from typing import Final

from . import hkcu_registry

LOG: Final = logging.getLogger(__name__)


class DirectoryContextMenu:
    """Namespace for HKCU folder/directory-background context-menu registration.

    Grouped as a class, not module-level functions, for symmetry with
    :class:`~borco_core.platforms.windows.file_association.FileAssociation` -- there's no
    per-instance state, so every method is a ``classmethod``.
    """

    __DIRECTORY_ROOT: Final = r"Software\Classes\Directory\shell"
    __BACKGROUND_ROOT: Final = r"Software\Classes\Directory\Background\shell"

    @classmethod
    def register_folder(cls, sub_key: str, text: str, command: str, icon: str) -> None:
        """Add a "right-click a folder" shell verb under HKCU.

        :param sub_key: registry sub-key name to create under ``Directory\\shell``.
        :param text: menu label Explorer shows for this entry.
        :param command: the launch command, without the trailing path argument, e.g.
            ``'"C:\\...\\app.exe"'`` -- ``"%1"`` (the clicked folder) is appended here.
        :param icon: ``Icon`` value shown for this entry, e.g. ``"C:\\...\\app.exe,0"``.
        """
        hkcu_registry.write_verb(rf"{cls.__DIRECTORY_ROOT}\{sub_key}", text, icon, f'{command} "%1"')
        hkcu_registry.notify_shell()
        LOG.info("registered folder context menu %r", sub_key)

    @classmethod
    def is_folder_registered(cls, sub_key: str, text: str, command: str, icon: str) -> bool:
        """Whether the "right-click a folder" verb :meth:`register_folder` with these same
        arguments would write already matches what's currently in HKCU.

        :param sub_key: same as :meth:`register_folder`.
        :param text: same as :meth:`register_folder`.
        :param command: same as :meth:`register_folder` (without the trailing path argument).
        :param icon: same as :meth:`register_folder`.
        :returns: ``True`` iff every value :meth:`register_folder` would write already matches.
        """
        return hkcu_registry.matches_verb(rf"{cls.__DIRECTORY_ROOT}\{sub_key}", text, icon, f'{command} "%1"')

    @classmethod
    def unregister_folder(cls, sub_key: str) -> None:
        """Remove the folder shell-verb key tree.

        :param sub_key: the sub-key previously passed to :meth:`register_folder`.
        """
        hkcu_registry.delete_key_tree(rf"{cls.__DIRECTORY_ROOT}\{sub_key}")
        hkcu_registry.notify_shell()
        LOG.info("unregistered folder context menu %r", sub_key)

    @classmethod
    def register_background(cls, sub_key: str, text: str, command: str, icon: str) -> None:
        """Add a "right-click inside a folder's background" shell verb under HKCU.

        :param sub_key: registry sub-key name to create under ``Directory\\Background\\shell``.
        :param text: menu label Explorer shows for this entry.
        :param command: the launch command, without the trailing path argument, e.g.
            ``'"C:\\...\\app.exe"'`` -- ``"%V"`` (the folder you're inside) is appended here.
        :param icon: ``Icon`` value shown for this entry, e.g. ``"C:\\...\\app.exe,0"``.
        """
        hkcu_registry.write_verb(rf"{cls.__BACKGROUND_ROOT}\{sub_key}", text, icon, f'{command} "%V"')
        hkcu_registry.notify_shell()
        LOG.info("registered folder-background context menu %r", sub_key)

    @classmethod
    def is_background_registered(cls, sub_key: str, text: str, command: str, icon: str) -> bool:
        """Whether the "right-click inside a folder's background" verb :meth:`register_background`
        with these same arguments would write already matches what's currently in HKCU.

        :param sub_key: same as :meth:`register_background`.
        :param text: same as :meth:`register_background`.
        :param command: same as :meth:`register_background` (without the trailing path argument).
        :param icon: same as :meth:`register_background`.
        :returns: ``True`` iff every value :meth:`register_background` would write already matches.
        """
        return hkcu_registry.matches_verb(rf"{cls.__BACKGROUND_ROOT}\{sub_key}", text, icon, f'{command} "%V"')

    @classmethod
    def unregister_background(cls, sub_key: str) -> None:
        """Remove the folder-background shell-verb key tree.

        :param sub_key: the sub-key previously passed to :meth:`register_background`.
        """
        hkcu_registry.delete_key_tree(rf"{cls.__BACKGROUND_ROOT}\{sub_key}")
        hkcu_registry.notify_shell()
        LOG.info("unregistered folder-background context menu %r", sub_key)
