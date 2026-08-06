"""What a checksum run is run with: the algorithm, the two verify choices and the staleness window
([[data-model#checksums]], #242).

Core ships generate and verify as callables taking every one of these as a parameter and reads no
setting of its own, so this is where they come from -- resolved by whoever enqueues a job, and captured
into that job's saved state rather than re-read when it is restored.

A plain ``@dataclass`` rather than the reactive `QObject` shape `LogsSettings` uses: nothing already on
screen renders from these. They are read when a run is enqueued, which is after any Save that changed
them.

:attr:`ChecksumSettings.last_sweep_root` is the one member no page edits -- the folder the last sweep was
pointed at, so the next one opens where the last one did. It lives here because it is a checksum-sweep
fact and there is nowhere else that remembers a chosen directory; it is why the page must write onto the
shared instance rather than a copy of its own, so neither Save drops the other's value.
"""

from dataclasses import dataclass
from datetime import timedelta
from functools import lru_cache
from typing import Final, cast

from PySide6.QtCore import QSettings
from rehuco_core import CHECKSUM_ALGORITHMS, DEFAULT_CHECKSUM_ALGORITHM

from .persistent_settings import persistent_settings

GROUP: Final = "checksums"
ALGORITHM_KEY: Final = "algorithm"
MIGRATE_ON_VERIFY_KEY: Final = "migrate_on_verify"
CREATE_MISSING_ON_VERIFY_KEY: Final = "create_missing_on_verify"
STALE_DAYS_KEY: Final = "stale_days"
LAST_SWEEP_ROOT_KEY: Final = "last_sweep_root"

MIN_STALE_DAYS: Final = 0
MAX_STALE_DAYS: Final = 1000
DEFAULT_STALE_DAYS: Final = 90
"""The staleness window's range and its default, in days.

**Zero is a real setting, not an unset one**: a window of no length leaves nothing fresh, so every sweep
re-reads everything ([[data-model#checksums]]). The page has to say so, since ``0`` reads just as
naturally as *never*."""


def read_algorithm(value: object) -> str:
    """Resolve a stored algorithm name to one this build actually ships.

    An unrecognized name is the ordinary consequence of an ``.ini`` written by a newer version, or of an
    algorithm dropped from a build; it selects :data:`~rehuco_core.DEFAULT_CHECKSUM_ALGORITHM` rather
    than raising, the way `VideosSettings` already treats an unknown ``engine``.

    This only chooses what *new* hashes are written under. Entries already recorded under the missing
    algorithm are not silently re-baselined under this one: core reports such an entry ``malformed`` and
    carries it through untouched (#203), since re-hashing it would replace a claim nothing checked.

    :param value: the raw stored value.
    :returns: the name of an algorithm in :data:`~rehuco_core.CHECKSUM_ALGORITHMS`.
    """
    return value if isinstance(value, str) and value in CHECKSUM_ALGORITHMS else DEFAULT_CHECKSUM_ALGORITHM


def read_stale_days(value: object) -> int:
    """Coerce a stored staleness window into the range the page offers.

    :param value: the raw stored value.
    :returns: whole days, clamped to :data:`MIN_STALE_DAYS`--:data:`MAX_STALE_DAYS`, or the default when
        the stored value is not a number at all.
    """
    try:
        days = int(cast(int, value))
    except TypeError, ValueError:
        return DEFAULT_STALE_DAYS
    return max(MIN_STALE_DAYS, min(MAX_STALE_DAYS, days))


@dataclass
class ChecksumSettings:
    """The checksum defaults, in one place ([[data-model#checksums]]).

    :attr:`algorithm`, :attr:`migrate_on_verify` and :attr:`create_missing_on_verify` are stored as the
    page left them; what a run consumes is :attr:`migrate_target` and :attr:`stale_after`, the values
    they resolve to.
    """

    algorithm: str = DEFAULT_CHECKSUM_ALGORITHM
    """What new hashes are recorded under. Per-entry in the record, so changing it invalidates nothing
    already written (#203)."""

    migrate_on_verify: bool = False
    """Whether a verify re-keys an entry recorded under another algorithm to :attr:`algorithm`.

    **Off by default.** Migration rewrites records nobody asked to change: with a catalog seeded from
    legacy ``.sfv``/``.md5`` manifests (#243), the first sweep with this on would re-key the whole thing
    -- turning a pass that should skip almost everything into a full re-read and rewrite."""

    create_missing_on_verify: bool = False
    """Whether a verify may create the record it is checking against, adopting every content file.

    **Off by default**, because [[data-model#checksums]] makes adoption deliberate: a verify that creates
    its own record is a generate under another name, and this setting reaches the per-document Verify as
    well as the sweep. A resource with no record costs a sweep one failed open and is counted as such,
    which is where turning it on becomes discoverable."""

    stale_days: int = DEFAULT_STALE_DAYS
    """How long a recorded verification stays fresh, in days. A *default for unattended runs* only:
    verifying a file, a selection or a resource on demand ignores it entirely (#203's ``stale_after=None``)."""

    last_sweep_root: str = ""
    """The folder the last sweep was pointed at, so the next one's chooser opens there. Not on any page."""

    @property
    def stale_after(self) -> timedelta:
        """The window a run is handed. ``timedelta(0)`` at zero days, which leaves nothing fresh --
        core's freshness test is a strict ``<``, so no special case is needed anywhere."""
        return timedelta(days=self.stale_days)

    @property
    def migrate_target(self) -> str | None:
        """What a verify migrates entries to, or ``None`` when it migrates nothing -- the shape
        :func:`~rehuco_core.verify_checksums` takes."""
        return self.algorithm if self.migrate_on_verify else None

    def load(self, settings: QSettings) -> None:
        """Replace the current values with what's in persistent storage.

        :param settings: the ``QSettings`` to read from.
        """
        settings.beginGroup(GROUP)
        self.algorithm = read_algorithm(settings.value(ALGORITHM_KEY))
        self.migrate_on_verify = cast(bool, settings.value(MIGRATE_ON_VERIFY_KEY, False, type=bool))
        self.create_missing_on_verify = cast(bool, settings.value(CREATE_MISSING_ON_VERIFY_KEY, False, type=bool))
        self.stale_days = read_stale_days(settings.value(STALE_DAYS_KEY, DEFAULT_STALE_DAYS))
        self.last_sweep_root = cast(str, settings.value(LAST_SWEEP_ROOT_KEY, "", type=str))
        settings.endGroup()

    def save(self, settings: QSettings) -> None:
        """Save the current values to persistent storage.

        :param settings: the ``QSettings`` to write to.
        """
        settings.beginGroup(GROUP)
        settings.setValue(ALGORITHM_KEY, self.algorithm)
        settings.setValue(MIGRATE_ON_VERIFY_KEY, self.migrate_on_verify)
        settings.setValue(CREATE_MISSING_ON_VERIFY_KEY, self.create_missing_on_verify)
        settings.setValue(STALE_DAYS_KEY, self.stale_days)
        settings.setValue(LAST_SWEEP_ROOT_KEY, self.last_sweep_root)
        settings.endGroup()


@lru_cache(maxsize=1)
def shared_checksum_settings() -> ChecksumSettings:
    """The single, process-wide `ChecksumSettings` instance, loaded from persistent storage on first
    call -- the same shape, and for the same reason, as
    :func:`~rehuco_agent.settings.excluded_files_settings.shared_excluded_files_settings`: the settings
    page's Save must be what the next enqueued run reads.

    One instance also carries :attr:`ChecksumSettings.last_sweep_root` between the page and the sweep,
    which is why both write onto this object rather than onto copies of their own.

    :returns: the shared instance.
    """
    settings = ChecksumSettings()
    settings.load(persistent_settings())
    return settings
