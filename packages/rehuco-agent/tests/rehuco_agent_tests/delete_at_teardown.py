"""The type of the repository conftest's ``delete_at_teardown`` fixture, for the tests that take it (#529)."""

from typing import Protocol

from PySide6.QtCore import QObject


# one method is the design: a callable's type
# pylint: disable-next=too-few-public-methods
class DeleteAtTeardown(Protocol):
    """Registers a `QObject` a test builds bare, to be deleted when the test ends, and hands it back."""

    def __call__[Q: QObject](self, qobject: Q, /) -> Q:
        """Delete ``qobject`` when the test ends.

        :param qobject: the object.
        :returns: ``qobject``.
        """
        ...  # pylint: disable=unnecessary-ellipsis
