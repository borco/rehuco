"""Tests for BalanceBucketsDialogSettings: the balance dialog's geometry and the roots last balanced (#681)."""

from unittest.mock import Mock
from uuid import UUID

from PySide6.QtCore import QByteArray, QSettings
from pytest import mark, param
from rehuco_agent.settings.balance_buckets_dialog_settings import BalanceBucketsDialogSettings

ROOTS = frozenset((UUID(int=1), UUID(int=2)))


def stored(values: dict[str, object]) -> Mock:
    """A stand-in store holding ``values`` and the factory values for every other key.

    :param values: what it holds, by key.
    :returns: the store, whose ``setValue`` writes into ``values``.
    """
    store = Mock(spec=QSettings)
    store.value.side_effect = lambda key, default, **_: values.get(key, default)
    store.setValue.side_effect = values.__setitem__
    return store


def test_what_is_saved_loads_back() -> None:
    """The geometry and the roots round-trip, under the dialog's own group.

    **Test steps:**

    * save settings, and load them into a fresh object
    * verify both values, and the group
    """
    store = stored({})

    BalanceBucketsDialogSettings(geometry=b"blob", roots=ROOTS).save(store)
    restored = BalanceBucketsDialogSettings()
    restored.load(store)

    assert restored == BalanceBucketsDialogSettings(b"blob", ROOTS)
    assert {call.args for call in store.beginGroup.call_args_list} == {("balance_buckets_dialog",)}


@mark.parametrize(
    "values",
    [
        param({}, id="nothing-saved"),
        param({"roots": "not json"}, id="no-json"),
        param({"roots": '["not an id"]'}, id="no-ids"),
        param({"roots": "3"}, id="no-list"),
        param({"roots": "[3]"}, id="numbers"),
    ],
)
def test_stored_roots_that_are_no_ids_read_as_none(values: dict[str, object]) -> None:
    """A damaged value leaves the dialog as on its first run.

    **Test steps:**

    * load a store with a value no save wrote, over settings holding some
    * verify no roots and no geometry
    """
    settings = BalanceBucketsDialogSettings(b"old", ROOTS)

    settings.load(stored(values | {"geometry": QByteArray()}))

    assert settings == BalanceBucketsDialogSettings()
