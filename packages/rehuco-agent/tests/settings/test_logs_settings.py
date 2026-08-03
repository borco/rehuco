"""Tests for LogsSettings: how much of the log each surface keeps.

Uses a hand-rolled in-memory stand-in for ``QSettings`` (see ``test_main_window_settings.py`` for
the same rationale) rather than a real one or ``tmp_path``.
"""

from typing import Any

from borco_pyside.logging import DEFAULT_LOG_LIMIT
from pytest import fixture
from rehuco_agent.settings.logs_settings import (
    APP_LIMIT_KEY,
    GROUP,
    MINIMUM_APP_LIMIT,
    MINIMUM_RESOURCE_LIMIT,
    RESOURCE_LIMIT_KEY,
    LogsSettings,
)


# region fixtures
# Mirrors test_theme_settings.py's FakeSettings exactly -- kept as a separate copy rather than a
# shared import, matching this codebase's settings-test convention.
# pylint: disable=duplicate-code
class FakeSettings:  # pylint: disable=invalid-name,missing-function-docstring,redefined-builtin
    """A minimal in-memory stand-in for the ``QSettings`` group/value API.

    Method names and the ``type=`` parameter deliberately mirror ``QSettings``'s own C++-derived
    API, since :meth:`LogsSettings.load`/:meth:`~LogsSettings.save` call them by name.
    """

    def __init__(self) -> None:
        self.__data: dict[str, Any] = {}
        self.__group = ""

    def beginGroup(self, name: str) -> None:  # noqa: N802
        self.__group = f"{name}/"

    def endGroup(self) -> None:  # noqa: N802
        self.__group = ""

    def setValue(self, key: str, value: Any) -> None:  # noqa: N802
        self.__data[self.__group + key] = value

    def value(self, key: str, default: Any = None, type: Any = None) -> Any:  # noqa: A002, N802
        del type
        return self.__data.get(self.__group + key, default)


# pylint: enable=duplicate-code


@fixture
def settings() -> FakeSettings:
    """A fresh in-memory settings stand-in.

    :returns: the stand-in.
    """
    return FakeSettings()


# endregion


# region defaults


def test_both_limits_default_to_the_librarys_own(settings: FakeSettings) -> None:
    """A fresh install keeps what borco-pyside considers a readable scroll-back, not a number invented here.

    **Test steps:**

    * Load from empty storage.
    * Assert both limits are the library's default.
    """
    logs = LogsSettings()
    logs.load(settings)  # type: ignore[arg-type]  # the stand-in mirrors the QSettings API used
    assert logs.app_limit == DEFAULT_LOG_LIMIT
    assert logs.resource_limit == DEFAULT_LOG_LIMIT


# endregion


# region load and save


def test_saves_and_reloads_both_limits(settings: FakeSettings) -> None:
    """What was saved is what comes back.

    **Test steps:**

    * Set both limits and save.
    * Load into a fresh object.
    * Assert both came back.
    """
    logs = LogsSettings()
    logs.app_limit = 1200
    logs.resource_limit = 80
    logs.save(settings)  # type: ignore[arg-type]  # the stand-in mirrors the QSettings API used

    reloaded = LogsSettings()
    reloaded.load(settings)  # type: ignore[arg-type]  # the stand-in mirrors the QSettings API used

    assert reloaded.app_limit == 1200
    assert reloaded.resource_limit == 80


def test_writes_both_limits_under_the_logs_group(settings: FakeSettings) -> None:
    """The values are stored under this section's own group and keys.

    **Test steps:**

    * Save.
    * Assert both keys are readable under the group.
    """
    logs = LogsSettings()
    logs.app_limit = 7
    logs.save(settings)  # type: ignore[arg-type]  # the stand-in mirrors the QSettings API used

    settings.beginGroup(GROUP)
    assert settings.value(APP_LIMIT_KEY) == 7
    assert settings.value(RESOURCE_LIMIT_KEY) == DEFAULT_LOG_LIMIT


def test_a_stored_limit_below_its_minimum_is_raised_to_it(settings: FakeSettings) -> None:
    """A hand-edited ``.ini`` asking for less than a surface can be given gets the least it can be.

    An app log holding nothing would look exactly like a log nothing had been written to, and turning one
    off is what closing its dock is for -- so zero is a mistake there, and its floor is one record.

    **Test steps:**

    * Store a negative number under each key.
    * Load.
    * Assert each came back as its own minimum.
    """
    settings.beginGroup(GROUP)
    settings.setValue(APP_LIMIT_KEY, -5)
    settings.setValue(RESOURCE_LIMIT_KEY, -5)
    settings.endGroup()

    logs = LogsSettings()
    logs.load(settings)  # type: ignore[arg-type]  # the stand-in mirrors the QSettings API used

    assert logs.app_limit == MINIMUM_APP_LIMIT
    assert logs.resource_limit == MINIMUM_RESOURCE_LIMIT


def test_a_stored_zero_app_limit_is_still_raised(settings: FakeSettings) -> None:
    """Zero means *keep everything* for a resource log only -- the app-wide one does not take it.

    **Test steps:**

    * Store zero under the app key.
    * Load.
    * Assert it came back as one record.
    """
    settings.beginGroup(GROUP)
    settings.setValue(APP_LIMIT_KEY, 0)
    settings.endGroup()

    logs = LogsSettings()
    logs.load(settings)  # type: ignore[arg-type]  # the stand-in mirrors the QSettings API used

    assert logs.app_limit == MINIMUM_APP_LIMIT


def test_a_stored_zero_resource_limit_is_kept(settings: FakeSettings) -> None:
    """Zero is a resource limit a reader can actually have chosen, so loading must not raise it (#236).

    **Test steps:**

    * Store zero under the resource key.
    * Load.
    * Assert it came back as zero.
    """
    settings.beginGroup(GROUP)
    settings.setValue(RESOURCE_LIMIT_KEY, 0)
    settings.endGroup()

    logs = LogsSettings()
    logs.load(settings)  # type: ignore[arg-type]  # the stand-in mirrors the QSettings API used

    assert logs.resource_limit == MINIMUM_RESOURCE_LIMIT


# endregion


# region the effective resource limit


def test_a_resource_limit_within_the_app_limit_is_used_as_it_is() -> None:
    """Below the app-wide limit there is nothing to clamp.

    **Test steps:**

    * Set a resource limit under the app one.
    * Assert the effective limit is the resource one.
    """
    logs = LogsSettings()
    logs.app_limit = 500
    logs.resource_limit = 100
    assert logs.effective_resource_limit == 100


def test_a_resource_limit_above_the_app_limit_is_clamped_to_it() -> None:
    """A resource surface cannot hold more than the bridge does, so it is not promised more.

    The bridge's cache is also its queue, so entries beyond the app-wide limit were dropped before they
    could reach any resource surface -- a larger number there would be a promise the plumbing cannot keep.

    **Test steps:**

    * Set a resource limit above the app one.
    * Assert the effective limit is the app one.
    """
    logs = LogsSettings()
    logs.app_limit = 200
    logs.resource_limit = 5000
    assert logs.effective_resource_limit == 200
    assert logs.resource_limit == 5000


def test_a_resource_limit_of_zero_is_no_cap_rather_than_the_app_limit() -> None:
    """*Keep everything* is not a number, so the clamp has nothing to hold it down to (#236).

    Unbounded is not *above* the app limit in the sense the clamp exists for: it promises to keep what
    reaches the surface, which the plumbing does honour, from attach onward.

    **Test steps:**

    * Set the resource limit to zero, under an app limit that would otherwise clamp it.
    * Assert the effective limit is no cap at all.
    """
    logs = LogsSettings()
    logs.app_limit = 200
    logs.resource_limit = 0
    assert logs.effective_resource_limit is None


# endregion


# region reporting changes


def test_reports_a_changed_app_limit() -> None:
    """The limit is watchable, which is what lets an open surface re-cap itself.

    A value read only at construction could not reach a dock already open, scrolled back, mid-job.

    **Test steps:**

    * Watch the notify signal and change the limit.
    * Assert it fired with the new value.
    """
    logs = LogsSettings()
    seen: list[int] = []
    logs.app_limit_changed.connect(seen.append)  # type: ignore[attr-defined]  # synthesized by SimpleProperty

    logs.app_limit = 42

    assert seen == [42]


def test_reports_a_changed_resource_limit() -> None:
    """Same for the per-resource limit, which every open resource surface follows.

    **Test steps:**

    * Watch the notify signal and change the limit.
    * Assert it fired with the new value.
    """
    logs = LogsSettings()
    seen: list[int] = []
    logs.resource_limit_changed.connect(seen.append)  # type: ignore[attr-defined]  # synthesized by SimpleProperty

    logs.resource_limit = 9

    assert seen == [9]


# endregion
