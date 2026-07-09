"""Shared per-user (``HKEY_CURRENT_USER``) registry write/delete/notify helpers.

Every HKCU-based registration in this package -- a file-type association, a folder shell verb --
reduces to the same three primitives: write a ``REG_SZ`` value, recursively delete a key tree on
unregister, and tell Explorer to refresh without a logoff.
"""

import ctypes
import logging
import winreg
from typing import Final

LOG: Final = logging.getLogger(__name__)

SHCNE_ASSOCCHANGED: Final = 0x08000000
"""``SHChangeNotify`` event id: a file-type association or shell-verb registration changed."""

SHCNF_IDLIST: Final = 0x0000
"""``SHChangeNotify`` flag: the two data pointers are ``None`` (not an ``ITEMIDLIST``/path pair)."""


def set_value(key_path: str, name: str, value: str) -> None:
    """Create ``key_path`` under HKCU and write a ``REG_SZ`` value.

    :param key_path: registry path relative to ``HKEY_CURRENT_USER``.
    :param name: value name; empty string writes the default value.
    :param value: string data to write.
    """
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path) as key:
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        LOG.debug("wrote HKCU\\%s[%r] = %r", key_path, name, value)


def delete_key_tree(path: str) -> None:
    """Recursively delete ``path`` and all its sub-keys under ``HKEY_CURRENT_USER``.

    A no-op (not an error) when ``path`` doesn't exist -- ``unregister`` callers use this to clean
    up state that may already be gone.

    :param path: registry path relative to ``HKEY_CURRENT_USER``.
    """
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, access=winreg.KEY_ALL_ACCESS) as key:
            while True:
                try:
                    child = winreg.EnumKey(key, 0)
                    delete_key_tree(rf"{path}\{child}")
                except OSError:
                    break
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
            LOG.debug("deleted HKCU\\%s", path)
    except OSError:
        pass  # already gone


def notify_shell() -> None:
    """Tell Explorer that an association/shell-verb registration changed, refreshing it without a logoff."""
    ctypes.windll.shell32.SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None)
