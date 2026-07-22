"""Shared per-user (``HKEY_CURRENT_USER``) registry write/delete/notify helpers.

Every HKCU-based registration reduces to the same handful of low-level operations -- writing a
string value, recursively deleting a key tree, telling Explorer to refresh without a logoff. Some
helpers below compose others for a shape common across callers; that doesn't make them primitives.
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


# region primitives


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
    up state that may already be gone. Any other failure (e.g. permission denied partway through
    the tree) is logged rather than swallowed silently, so a partial deletion leaves a trace instead
    of being reported as success -- but it is not re-raised: unregistration is best-effort cleanup
    and must not crash the caller.

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
    except FileNotFoundError:
        pass  # already gone
    except OSError:
        LOG.warning("failed to delete HKCU\\%s", path, exc_info=True)


def notify_shell() -> None:
    """Tell Explorer that an association/shell-verb registration changed, refreshing it without a logoff."""
    ctypes.windll.shell32.SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None)


def get_value(key_path: str, name: str) -> str | None:
    """Read a ``REG_SZ`` value under HKCU, or ``None`` if ``key_path`` or ``name`` doesn't exist.

    The read-back counterpart to :func:`set_value`, for verifying a registration is (still)
    exactly what it should be -- e.g. a "Check registration" settings-page button.

    :param key_path: registry path relative to ``HKEY_CURRENT_USER``.
    :param name: value name; empty string reads the default value.
    :returns: the string value, or ``None`` if either the key or the value is missing.
    """
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            value, _ = winreg.QueryValueEx(key, name)
            return str(value)
    except OSError:
        return None


# endregion

# region composites


def write_verb(key_path: str, text: str, icon: str, command: str) -> None:
    """Write one shell-verb key: its label, icon, and launch command.

    :param key_path: registry path relative to ``HKEY_CURRENT_USER`` for the verb's own key --
        its ``command`` sub-key is derived from this path.
    :param text: menu label Explorer shows for this entry.
    :param icon: ``Icon`` value for this entry.
    :param command: the full command value, already carrying its trailing path argument.
    """
    set_value(key_path, "", text)
    set_value(key_path, "Icon", icon)
    set_value(rf"{key_path}\command", "", command)


def matches_verb(key_path: str, text: str, icon: str, command: str) -> bool:
    """Whether the shell-verb key :func:`write_verb` would write at ``key_path`` already holds
    exactly ``text``/``icon``/``command``.

    :param key_path: registry path relative to ``HKEY_CURRENT_USER``, as passed to
        :func:`write_verb`.
    :param text: expected menu label.
    :param icon: expected ``Icon`` value.
    :param command: expected full command value.
    :returns: whether every value :func:`write_verb` would write already matches what's currently
        in HKCU.
    """
    return (
        get_value(key_path, "") == text
        and get_value(key_path, "Icon") == icon
        and get_value(rf"{key_path}\command", "") == command
    )


# endregion
