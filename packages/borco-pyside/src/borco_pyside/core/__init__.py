"""Application-lifecycle primitives built on PySide6."""

from .application_singleton import ApplicationSingleton
from .connection_list import ConnectionList
from .properties import SimpleProperty, TypedProperty

__all__ = ["ApplicationSingleton", "ConnectionList", "SimpleProperty", "TypedProperty"]
