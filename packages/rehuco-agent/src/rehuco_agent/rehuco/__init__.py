"""The Root Catalog: one opened ``.rehuco`` and the cache its roots are scanned into, shown by two docks -- its
roots in the Root Catalog dock, the resources the cache lists in the Browsers dock (#377, #378, #461,
[[plugins#rehuco-dock]]).
"""

from .browsers_dock import BrowsersDock
from .catalog_table_model import CatalogTableModel
from .root_catalog import RootCatalog
from .roots_folder_model import RootsFolderModel
from .roots_panel import RootsPanel
from .table_browser import TableBrowser

__all__ = ["BrowsersDock", "CatalogTableModel", "RootCatalog", "RootsFolderModel", "RootsPanel", "TableBrowser"]
