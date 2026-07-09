"""Generic Windows HKCU per-file-extension shell-verb ("right-click a file -> run <App>") registration.

Registers under ``SystemFileAssociations\\<ext>\\shell`` -- unlike a ProgID association
(:mod:`~borco_core.platforms.windows.file_association`), this adds a right-click verb to every file
of the given extension(s) without claiming the double-click/default-open behavior.
"""

import logging
from collections.abc import Sequence
from typing import Final

from borco_core.platforms.windows import hkcu_registry

LOG: Final = logging.getLogger(__name__)


class FileExtensionContextMenu:
    """Namespace for HKCU per-file-extension context-menu registration.

    Grouped as a class, not module-level functions, for symmetry with
    :class:`~borco_core.platforms.windows.directory_context_menu.DirectoryContextMenu` -- there's no
    per-instance state, so every method is a ``classmethod``.
    """

    __ROOT: Final = r"Software\Classes\SystemFileAssociations"

    @classmethod
    def register(cls, extensions: Sequence[str], sub_key: str, text: str, command: str, icon: str) -> None:
        """Add a right-click shell verb to every file of each extension in ``extensions``.

        :param extensions: file extensions, each including the leading dot (e.g. ``".zip"``).
        :param sub_key: registry sub-key name to create under each extension's ``shell`` key.
        :param text: menu label Explorer shows for this entry.
        :param command: the launch command, without the trailing path argument, e.g.
            ``'"C:\\...\\app.exe"'`` -- ``"%1"`` (the clicked file) is appended here.
        :param icon: ``Icon`` value shown for this entry, e.g. ``"C:\\...\\app.exe,0"``.
        """
        for extension in extensions:
            hkcu_registry.write_verb(rf"{cls.__ROOT}\{extension}\shell\{sub_key}", text, icon, f'{command} "%1"')
        hkcu_registry.notify_shell()
        LOG.info("registered file-extension context menu %r for %s", sub_key, extensions)

    @classmethod
    def unregister(cls, extensions: Sequence[str], sub_key: str) -> None:
        """Remove the shell-verb key tree from every extension in ``extensions``.

        :param extensions: file extensions previously passed to :meth:`register`.
        :param sub_key: the sub-key previously passed to :meth:`register`.
        """
        for extension in extensions:
            hkcu_registry.delete_key_tree(rf"{cls.__ROOT}\{extension}\shell\{sub_key}")
        hkcu_registry.notify_shell()
        LOG.info("unregistered file-extension context menu %r for %s", sub_key, extensions)
