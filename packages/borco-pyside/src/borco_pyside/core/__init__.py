"""Application-lifecycle primitives built on PySide6."""

from .application_singleton import ApplicationSingleton
from .properties import SimpleProperty, TypedProperty

__all__ = ["ApplicationSingleton", "SimpleProperty", "TypedProperty"]
