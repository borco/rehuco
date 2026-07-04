"""Application-lifecycle primitives built on PySide6."""

from borco_pyside.core.application_singleton import ApplicationSingleton
from borco_pyside.core.properties import SimpleProperty, TypedProperty, notify_signal_name

__all__ = ["ApplicationSingleton", "SimpleProperty", "TypedProperty", "notify_signal_name"]
