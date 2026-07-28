"""Linux desktop-integration modules for borco-core.

Unlike the Windows siblings -- which ``import winreg`` at module scope and so cannot even be
collected elsewhere -- nothing here is platform-gated at import time: these modules are
``pathlib``/``subprocess`` only, so they import (and test) on any OS. Only their *effects* are
Linux-specific, which is what lets a Windows or macOS developer run their tests unmocked-away.
"""
