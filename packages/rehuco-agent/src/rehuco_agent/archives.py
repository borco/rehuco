"""Archive-file constants, deliberately free of any Qt import.

Split out of :mod:`rehuco_agent.main_window` so the CLI's ``--register``/``--unregister`` path can
reach :data:`ARCHIVE_EXTENSIONS` without dragging in the GUI stack. The Windows installer runs
``Rehuco.exe --register`` from a post-install script ([[appendices.briefcase-packaging#windows]]),
and importing PySide6, QtAds and the compiled resources to write a handful of registry values cost
about a second -- a second the installer spent showing a console window. Registration needs the
extension list and nothing else Qt-shaped, so it is reachable here instead.

The value itself lives in `rehuco_core.constants.ARCHIVE_EXTENSIONS` -- shared with content-image
enumeration (`rehuco_core.rehu_content_images`, #197), which needs the same set to know what a
reference-images resource's content is. Re-exported here so the existing agent-side import path keeps
working.
"""

from rehuco_core import ARCHIVE_EXTENSIONS

__all__ = ["ARCHIVE_EXTENSIONS"]
