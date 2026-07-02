"""Windows HKCU file-association and app-identity registration (§16.8, §5.4).

Ported from the file-association spike (issue #1): a HKCU ProgID for ``.rehu`` plus its
``AppUserModelId``, so double-click opens route through the single-instance agent and the
taskbar shows the right icon/pin/running state. HKCU only -- no elevation needed. Registering
is a one-off, user-triggered step (``rehuco-agent --register``), not something the app does on
every launch.
"""

import ctypes
import logging
import winreg
from pathlib import Path
from typing import Final

LOG: Final = logging.getLogger(__name__)

PROGID: Final = "Rehuco.Document"
"""HKCU ProgID under ``Software\\Classes`` that owns the ``.rehu`` association."""

EXTENSION: Final = "rehu"
"""File extension (without the leading dot) registered to :data:`PROGID`."""

AUMID: Final = "borco.rehuco.agent"
"""Application User Model ID the running process declares via ``SetCurrentProcessExplicitAppUserModelID``."""

FRIENDLY_NAME: Final = "Rehuco Resource"
"""Human-readable type name shown in Explorer's Type column."""

__SHCNE_ASSOCCHANGED: Final = 0x08000000
__SHCNF_IDLIST: Final = 0x0000


def register(exe_path: Path | str, ico_path: Path | str | None = None) -> None:
    """Write the HKCU ProgID and bind ``.rehu`` to it as the default double-click handler.

    Does not touch ``FileExts\\.rehu\\UserChoice`` -- that key is hash-protected by Explorer
    and cannot be set reliably by third-party code; registering the plain ``.rehu`` default
    value is the correct, unprivileged approach and works as long as no ``UserChoice`` exists.

    :param exe_path: absolute path to the ``rehuco-agent`` launcher executable.
    :param ico_path: absolute path to a ``.ico`` file for ``DefaultIcon``; falls back to the
        launcher exe's own embedded icon when not given (no dedicated ``.ico`` asset yet).
    """
    exe_path = str(exe_path)
    icon = f"{ico_path},0" if ico_path is not None else f"{exe_path},0"
    command = f'"{exe_path}" "%1"'

    __set_value(rf"Software\Classes\{PROGID}", "", FRIENDLY_NAME)
    __set_value(rf"Software\Classes\{PROGID}\DefaultIcon", "", icon)
    __set_value(rf"Software\Classes\{PROGID}\shell\open\command", "", command)
    __set_value(rf"Software\Classes\{PROGID}\Application", "AppUserModelId", AUMID)
    __set_value(rf"Software\Classes\.{EXTENSION}", "", PROGID)
    # in addition to the plain default-value binding above: a stronger "this is a real
    # recommended handler" signal for Explorer's "how do you want to open this" picker
    __set_value(rf"Software\Classes\.{EXTENSION}\OpenWithProgids", PROGID, "")

    __notify_shell()
    LOG.info("registered ProgID %r for .%s", PROGID, EXTENSION)


def unregister() -> None:
    """Remove the HKCU ProgID and, if it still points at it, the extension binding."""
    __delete_key_tree(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{PROGID}")

    ext_key = rf"Software\Classes\.{EXTENSION}"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, ext_key) as key:
            value, _ = winreg.QueryValueEx(key, "")
            if value == PROGID:
                # recursive delete, not a plain DeleteKey: .rehu now has an OpenWithProgids
                # subkey, and DeleteKey refuses to remove a key that still has children
                __delete_key_tree(winreg.HKEY_CURRENT_USER, ext_key)
                LOG.info("removed extension binding for .%s", EXTENSION)
    except OSError:
        pass  # already gone or never existed

    __notify_shell()
    LOG.info("unregistered ProgID %r", PROGID)


def __set_value(key_path: str, name: str, value: str) -> None:
    """Create ``key_path`` under HKCU and write a ``REG_SZ`` value.

    :param key_path: registry path relative to ``HKEY_CURRENT_USER``.
    :param name: value name; empty string writes the default value.
    :param value: string data to write.
    """
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path) as key:
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        LOG.debug("wrote HKCU\\%s[%r] = %r", key_path, name, value)


def __delete_key_tree(root: int, path: str) -> None:
    """Recursively delete ``path`` and all its sub-keys under ``root``.

    :param root: a ``winreg`` root constant, e.g. ``winreg.HKEY_CURRENT_USER``.
    :param path: registry path relative to ``root``.
    """
    try:
        with winreg.OpenKey(root, path, access=winreg.KEY_ALL_ACCESS) as key:
            while True:
                try:
                    child = winreg.EnumKey(key, 0)
                    __delete_key_tree(root, rf"{path}\{child}")
                except OSError:
                    break
            winreg.DeleteKey(root, path)
            LOG.debug("deleted HKCU\\%s", path)
    except OSError:
        pass  # already gone


def __notify_shell() -> None:
    """Tell Explorer that file-type associations changed, so it refreshes without a logoff."""
    ctypes.windll.shell32.SHChangeNotify(__SHCNE_ASSOCCHANGED, __SHCNF_IDLIST, None, None)
