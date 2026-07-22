"""Generic Windows HKCU file-type association registration.

Binds a file extension to a launch command via a per-user (``HKEY_CURRENT_USER``) ``ProgID`` --
no elevation needed, and no touching ``FileExts\\<ext>\\UserChoice`` (that key is hash-protected
by Explorer and cannot be set reliably by third-party code; registering the plain extension's
default value is the correct, unprivileged approach and works as long as no ``UserChoice`` exists).
"""

import logging
from typing import Final

from . import hkcu_registry

LOG: Final = logging.getLogger(__name__)


class FileAssociation:
    """Namespace for HKCU file-type association registration.

    Grouped as a class, not module-level functions, for symmetry with
    :class:`~borco_core.platforms.windows.directory_context_menu.DirectoryContextMenu` -- there's no
    per-instance state, so every method is a ``classmethod``.
    """

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
        hkcu_registry.set_value(rf"Software\Classes\{progid}", "", friendly_name)
        hkcu_registry.set_value(rf"Software\Classes\{progid}\DefaultIcon", "", icon)
        hkcu_registry.set_value(rf"Software\Classes\{progid}\shell\open\command", "", command)
        if aumid is not None:
            hkcu_registry.set_value(rf"Software\Classes\{progid}\Application", "AppUserModelId", aumid)
        hkcu_registry.set_value(rf"Software\Classes\.{extension}", "", progid)
        # in addition to the plain default-value binding above: a stronger "this is a real
        # recommended handler" signal for Explorer's "how do you want to open this" picker
        hkcu_registry.set_value(rf"Software\Classes\.{extension}\OpenWithProgids", progid, "")

        hkcu_registry.notify_shell()
        LOG.info("registered ProgID %r for .%s", progid, extension)

    @classmethod
    def is_registered(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        cls,
        progid: str,
        extension: str,
        friendly_name: str,
        command: str,
        icon: str,
        aumid: str | None = None,
    ) -> bool:
        """Whether HKCU already holds exactly the registration :meth:`register` with these same
        arguments would write.

        :param progid: same as :meth:`register`.
        :param extension: same as :meth:`register`.
        :param friendly_name: same as :meth:`register`.
        :param command: same as :meth:`register`.
        :param icon: same as :meth:`register`.
        :param aumid: same as :meth:`register` -- when ``None``, the ``Application`` key is not
            checked at all (its presence or absence either way doesn't matter).
        :returns: ``True`` iff every value :meth:`register` would write already matches.
        """
        progid_key = rf"Software\Classes\{progid}"
        if hkcu_registry.get_value(progid_key, "") != friendly_name:
            return False
        if hkcu_registry.get_value(rf"{progid_key}\DefaultIcon", "") != icon:
            return False
        if hkcu_registry.get_value(rf"{progid_key}\shell\open\command", "") != command:
            return False
        if aumid is not None and hkcu_registry.get_value(rf"{progid_key}\Application", "AppUserModelId") != aumid:
            return False
        ext_key = rf"Software\Classes\.{extension}"
        if hkcu_registry.get_value(ext_key, "") != progid:
            return False
        return hkcu_registry.get_value(rf"{ext_key}\OpenWithProgids", progid) == ""

    @classmethod
    def unregister(cls, progid: str, extension: str) -> None:
        """Remove the HKCU ``progid`` key tree and only this progid's own extension bindings.

        The extension key itself survives: deleting the whole ``Software\\Classes\\.<ext>`` tree
        would also wipe *other* applications' ``OpenWithProgids`` entries and unrelated values a
        different registrar may have added (``PerceivedType``, ``ShellNew``, ...), so only the
        ``OpenWithProgids`` value :meth:`register` wrote and -- if it still points at ``progid`` --
        the default-handler value are removed.

        :param progid: the ``ProgID`` to remove.
        :param extension: file extension whose bindings to ``progid`` are cleared.
        """
        hkcu_registry.delete_key_tree(rf"Software\Classes\{progid}")

        ext_key = rf"Software\Classes\.{extension}"
        hkcu_registry.delete_value(rf"{ext_key}\OpenWithProgids", progid)
        if hkcu_registry.get_value(ext_key, "") == progid:
            hkcu_registry.delete_value(ext_key, "")
            LOG.info("removed extension binding for .%s", extension)

        hkcu_registry.notify_shell()
        LOG.info("unregistered ProgID %r", progid)
