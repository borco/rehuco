"""Tests for chain families: a name claimed once, and the only way to build the chain keys it owns (#563)."""

import pytest
from rehuco_core import DEFAULT_CHAIN_REGISTRY, DISK_CHAIN, ChainFamily, ChainRegistry


def test_a_family_builds_its_single_chain_and_one_per_resource() -> None:
    """A family's keys are its name alone, or its name and a resource.

    **Test steps:**

    * register a family
    * verify its single chain is its name, and a resource's chain is ``name:resource``
    """
    family = ChainRegistry().register("save")

    assert family.chain() == "save"
    assert family.chain(r"\\Nas\data") == r"save:\\Nas\data"


def test_a_name_is_claimed_once() -> None:
    """Two kinds of job claiming one name would share its chains; the second claim is refused.

    **Test steps:**

    * register a family
    * verify registering the same name again raises, naming it
    """
    registry = ChainRegistry()
    registry.register("save")

    with pytest.raises(ValueError, match="'save'"):
        registry.register("save")


@pytest.mark.parametrize("name", ["", "save:nas"])
def test_a_name_that_is_empty_or_holds_the_separator_is_refused(name: str) -> None:
    """The part of a key before its first separator must name exactly one family.

    **Test steps:**

    * verify registering an empty name, or one holding the separator, raises
    """
    with pytest.raises(ValueError, match="non-empty name"):
        ChainRegistry().register(name)


def test_a_key_belongs_to_the_family_whose_name_it_starts_with() -> None:
    """Keys of two families never meet, even when one's resource spells the other's name.

    **Test steps:**

    * register two families, ``a`` and ``save``
    * verify ``save:a`` and ``save:x:y`` belong to ``save``, ``a`` to ``a``, and an unclaimed name to nothing
    """
    registry = ChainRegistry()
    a, save = registry.register("a"), registry.register("save")

    assert registry.family_of(save.chain(a.chain())) == save
    assert registry.family_of(save.chain("x:y")) == save
    assert registry.family_of(a.chain()) == a
    assert registry.family_of("other:a") is None


def test_the_app_registry_owns_the_disk_chain() -> None:
    """Every job that names no chain runs in one the app's registry owns.

    **Test steps:**

    * verify the default registry's family of the disk chain is the disk family
    """
    assert DEFAULT_CHAIN_REGISTRY.family_of(DISK_CHAIN) == ChainFamily(DISK_CHAIN)
