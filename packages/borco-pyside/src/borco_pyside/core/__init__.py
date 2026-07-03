"""Application-lifecycle primitives built on PySide6."""

from borco_pyside.core.application_singleton import ApplicationSingleton
from borco_pyside.core.properties import SimpleProperty, TypedProperty

__all__ = ["ApplicationSingleton", "SimpleProperty", "TypedProperty"]
