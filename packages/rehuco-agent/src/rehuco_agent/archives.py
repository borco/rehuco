"""Archive-file constants, deliberately free of any Qt import.

Split out of :mod:`rehuco_agent.main_window` so the CLI's ``--register``/``--unregister`` path can
reach :data:`ARCHIVE_EXTENSIONS` without dragging in the GUI stack. The Windows installer runs
``Rehuco.exe --register`` from a post-install script ([[appendices.briefcase-packaging#windows]]),
and importing PySide6, QtAds and the compiled resources to write a handful of registry values cost
about a second -- a second the installer spent showing a console window. Registration needs the
extension list and nothing else Qt-shaped, so the list lives here instead.
"""

from typing import Final

ARCHIVE_EXTENSIONS: Final = (".zip",)
"""Archive file extensions (each including the leading dot) that get a file-scoped ``.rehu``
companion ([[data-model#resource-scoping]]) via :meth:`~rehuco_agent.main_window.MainWindow.open_archive`,
instead of being opened directly like a bare ``.rehu`` file. Also the set given the "Create or Open
Rehuco Info" shell verb (#43) by :func:`rehuco_agent.windows_registration.register`."""
