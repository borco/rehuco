"""How much of the log each surface keeps ([[appendices.logging#configured-limits]], #200)."""

from functools import lru_cache
from typing import Final, cast

from borco_pyside.core import SimpleProperty
from borco_pyside.logging import DEFAULT_LOG_LIMIT
from PySide6.QtCore import QObject, QSettings

from .persistent_settings import persistent_settings

GROUP: Final = "logs"
APP_LIMIT_KEY: Final = "app_limit"
RESOURCE_LIMIT_KEY: Final = "resource_limit"

MINIMUM_LIMIT: Final = 1
"""The smallest either limit can be set to -- one record, which is what the models themselves clamp to.

Not zero: a surface holding nothing would look exactly like a surface nothing had been logged to, and
turning a log off is what closing its dock is for."""


class LogsSettings(QObject):
    """How many records the app-wide log surface and each resource's own keep
    ([[appendices.logging#configured-limits]]).

    A reactive ``QObject``, following `ImageViewerSettings` rather than the plain dataclass most of this
    app's settings use: a limit lowered in the settings dialog has to reach the surfaces **already
    open**, scrolled back, mid-job -- that is the whole point of [[appendices.logging#buffers]]'s
    "settable while running", and a value read only at construction could not do it.

    **Two values, and only two.** :attr:`app_limit` is also what the bridge's cache is capped at rather
    than being a third setting: that cache exists to fill the app-wide surface on attach, so a larger one
    could never be shown and a smaller one would truncate the replay.

    **The value is shared; the buffers are not.** :attr:`resource_limit` is one number applied to every
    resource surface. Changing it re-caps all of them, and changes nothing about what each holds relative
    to the others, or about clearing them.

    :param parent: optional Qt parent.
    """

    app_limit = SimpleProperty(DEFAULT_LOG_LIMIT)
    """How many records the app-wide log surface keeps -- and the cap on the bridge's replay cache."""

    resource_limit = SimpleProperty(DEFAULT_LOG_LIMIT)
    """How many records each resource's own log surface keeps, as stored.

    What a surface is actually given is :attr:`effective_resource_limit`."""

    @property
    def effective_resource_limit(self) -> int:
        """What a resource surface is really capped at: :attr:`resource_limit`, but never above
        :attr:`app_limit`.

        The bridge's cache is also its queue ([[appendices.logging#buffers]]), so a resource surface
        asked to hold more than the bridge does can never fill past it -- the entries were dropped before
        they could arrive. Clamping keeps the number a surface reports honest rather than leaving a
        promise the plumbing cannot keep.
        """
        return min(self.resource_limit, self.app_limit)

    def load(self, settings: QSettings) -> None:
        """Replace the current limits with what's in persistent storage.

        A stored value below :data:`MINIMUM_LIMIT` -- an ``.ini`` edited by hand, or written by a version
        that allowed zero -- is raised to it rather than refused: an unreadable preference must not stop
        a log surface from opening.

        :param settings: the ``QSettings`` to read from.
        """
        settings.beginGroup(GROUP)
        self.app_limit = max(MINIMUM_LIMIT, cast(int, settings.value(APP_LIMIT_KEY, DEFAULT_LOG_LIMIT, type=int)))
        self.resource_limit = max(
            MINIMUM_LIMIT, cast(int, settings.value(RESOURCE_LIMIT_KEY, DEFAULT_LOG_LIMIT, type=int))
        )
        settings.endGroup()

    def save(self, settings: QSettings) -> None:
        """Save the current limits to persistent storage.

        :param settings: the ``QSettings`` to write to.
        """
        settings.beginGroup(GROUP)
        settings.setValue(APP_LIMIT_KEY, self.app_limit)
        settings.setValue(RESOURCE_LIMIT_KEY, self.resource_limit)
        settings.endGroup()


@lru_cache(maxsize=1)
def shared_logs_settings() -> LogsSettings:
    """The single, process-wide `LogsSettings` instance, loaded from persistent storage on first call.

    The same shape, and for the same reason, as
    :func:`~rehuco_agent.settings.image_viewer_settings.shared_image_viewer_settings`: every log surface
    and the bridge itself subscribe to *this* object, so a per-reader copy would leave the settings
    page's Save reaching nothing.

    :returns: the shared instance.
    """
    settings = LogsSettings()
    settings.load(persistent_settings())
    return settings
