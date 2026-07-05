"""Generic Windows HKCU file-type association registration.

Binds a file extension to a launch command via a per-user (``HKEY_CURRENT_USER``) ``ProgID`` --
no elevation needed, and no touching ``FileExts\\<ext>\\UserChoice`` (that key is hash-protected
by Explorer and cannot be set reliably by third-party code; registering the plain extension's
default value is the correct, unprivileged approach and works as long as no ``UserChoice`` exists).
"""

import ctypes
import logging
import winreg
from typing import Final

LOG: Final = logging.getLogger(__name__)


class FileAssociation:
    """Namespace for HKCU file-type association registration.

    Grouped as a class, not module-level functions, so the internal helpers below can be
    genuinely private via Python's name-mangling -- which only applies inside a class body, not
    at module level. There's no per-instance state, so every method is a ``classmethod``/
    ``staticmethod``; nothing is ever instantiated.
    """

    SHCNE_ASSOCCHANGED: Final = 0x08000000
    """``SHChangeNotify`` event id: a file-type association changed."""

    SHCNF_IDLIST: Final = 0x0000
    """``SHChangeNotify`` flag: the two data pointers are ``None`` (not an ``ITEMIDLIST``/path pair)."""

    @classmethod
    def register(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        cls,
        progid: str,
        extension: str,
        friendly_name: str,
        command: str,
        icon: str,
        aumid: str | None = None,
    ) -> None:
        """Write the HKCU ``progid`` and bind ``extension`` to it as the default double-click handler.

        :param progid: ``ProgID`` name to create under ``Software\\Classes``.
        :param extension: file extension (without the leading dot) to bind to ``progid``.
        :param friendly_name: human-readable type name shown in Explorer's Type column.
        :param command: the full ``shell\\open\\command`` value, e.g. ``'"C:\\...\\app.exe" "%1"'``.
        :param icon: ``DefaultIcon`` value, e.g. ``"C:\\...\\app.exe,0"``.
        :param aumid: ``AppUserModelId`` to write under ``progid``'s ``Application`` key; omitted
            entirely when not given.
        """
        cls.__set_value(rf"Software\Classes\{progid}", "", friendly_name)
        cls.__set_value(rf"Software\Classes\{progid}\DefaultIcon", "", icon)
        cls.__set_value(rf"Software\Classes\{progid}\shell\open\command", "", command)
        if aumid is not None:
            cls.__set_value(rf"Software\Classes\{progid}\Application", "AppUserModelId", aumid)
        cls.__set_value(rf"Software\Classes\.{extension}", "", progid)
        # in addition to the plain default-value binding above: a stronger "this is a real
        # recommended handler" signal for Explorer's "how do you want to open this" picker
        cls.__set_value(rf"Software\Classes\.{extension}\OpenWithProgids", progid, "")

        cls.__notify_shell()
        LOG.info("registered ProgID %r for .%s", progid, extension)

    @classmethod
    def unregister(cls, progid: str, extension: str) -> None:
        """Remove the HKCU ``progid`` key tree and, if it still points at it, the extension binding.

        :param progid: the ``ProgID`` to remove.
        :param extension: file extension whose binding is cleared, if it still points at ``progid``.
        """
        cls.__delete_key_tree(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{progid}")

        ext_key = rf"Software\Classes\.{extension}"
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, ext_key) as key:
                value, _ = winreg.QueryValueEx(key, "")
                if value == progid:
                    # recursive delete, not a plain DeleteKey: the extension key now has an
                    # OpenWithProgids subkey, and DeleteKey refuses to remove a key with children
                    cls.__delete_key_tree(winreg.HKEY_CURRENT_USER, ext_key)
                    LOG.info("removed extension binding for .%s", extension)
        except OSError:
            pass  # already gone or never existed

        cls.__notify_shell()
        LOG.info("unregistered ProgID %r", progid)

    @staticmethod
    def __set_value(key_path: str, name: str, value: str) -> None:
        """Create ``key_path`` under HKCU and write a ``REG_SZ`` value.

        :param key_path: registry path relative to ``HKEY_CURRENT_USER``.
        :param name: value name; empty string writes the default value.
        :param value: string data to write.
        """
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
            LOG.debug("wrote HKCU\\%s[%r] = %r", key_path, name, value)

    @classmethod
    def __delete_key_tree(cls, root: int, path: str) -> None:
        """Recursively delete ``path`` and all its sub-keys under ``root``.

        :param root: a ``winreg`` root constant, e.g. ``winreg.HKEY_CURRENT_USER``.
        :param path: registry path relative to ``root``.
        """
        try:
            with winreg.OpenKey(root, path, access=winreg.KEY_ALL_ACCESS) as key:
                while True:
                    try:
                        child = winreg.EnumKey(key, 0)
                        cls.__delete_key_tree(root, rf"{path}\{child}")
                    except OSError:
                        break
                winreg.DeleteKey(root, path)
                LOG.debug("deleted HKCU\\%s", path)
        except OSError:
            pass  # already gone

    @classmethod
    def __notify_shell(cls) -> None:
        """Tell Explorer that file-type associations changed, so it refreshes without a logoff."""
        ctypes.windll.shell32.SHChangeNotify(cls.SHCNE_ASSOCCHANGED, cls.SHCNF_IDLIST, None, None)
