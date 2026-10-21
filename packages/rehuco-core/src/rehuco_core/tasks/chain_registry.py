"""Who owns which chain names, so two kinds of job never share a chain by accident (#563,
[[appendices.task-queue#serial]]).

A chain is a string key, and a string can be spelled alike by two authors who never met: a checksum job and a save
both calling theirs ``"nas"`` would take turns that nobody asked for, and a typo would silently put a job in a chain of
its own and run it beside the work it was meant to wait for. So a chain name is something a **family** claims: it
registers its name once, a second claim of that name is refused, and every key it hands out is built from the name --
``name`` alone, or ``name:resource`` for a family with one chain per resource (a save's per server). The queue refuses
a job whose chain no family owns. Keys of two families can then never be equal, because a family's name never holds the
separator and every key starts with its family's name.
"""

from dataclasses import dataclass
from typing import Final

CHAIN_SEPARATOR: Final = ":"
"""What divides a family's name from the resource in a chain key, e.g. ``save:C:``. A family's name never holds it,
which is what makes the part before the first one name exactly one family."""


@dataclass(frozen=True, slots=True)
class ChainFamily:
    """A name claimed in a :class:`ChainRegistry`, and the only way to build the chain keys it owns.

    :param name: the claimed name.
    """

    name: str

    def chain(self, resource: str = "") -> str:
        """A chain key of this family.

        :param resource: the one resource the chain's jobs would hammer -- a server, a drive -- or ``""`` for the
            family's single chain.
        :returns: ``name``, or ``name:resource``.
        """
        return f"{self.name}{CHAIN_SEPARATOR}{resource}" if resource else self.name


class ChainRegistry:
    """The chain families this build knows, each name claimed once.

    Registration is done by whoever owns the jobs -- a module registering its family at import, as job classes
    register their kinds (:class:`~rehuco_core.tasks.TaskJobRegistry`) -- rather than by a central list.
    """

    def __init__(self) -> None:
        self.__families: dict[str, ChainFamily] = {}

    def register(self, name: str) -> ChainFamily:
        """Claim ``name`` for a family of chains.

        :param name: the family's name: non-empty, without :data:`CHAIN_SEPARATOR`.
        :returns: the family, which builds its chain keys.
        :raises ValueError: if ``name`` is empty, holds the separator, or is already claimed -- two kinds of job
            claiming one name is a programming error, and silently sharing it is the very collision this prevents.
        """
        if not name or CHAIN_SEPARATOR in name:
            raise ValueError(f"A chain family needs a non-empty name without {CHAIN_SEPARATOR!r}, not {name!r}.")
        if name in self.__families:
            raise ValueError(f"Two kinds of job claim the chain family {name!r}.")
        family = ChainFamily(name)
        self.__families[name] = family
        return family

    def family_of(self, chain: str) -> ChainFamily | None:
        """The family a chain key belongs to.

        :param chain: the key.
        :returns: its family, or ``None`` when no family claimed the name it starts with.
        """
        return self.__families.get(chain.partition(CHAIN_SEPARATOR)[0])


DEFAULT_CHAIN_REGISTRY: Final = ChainRegistry()
"""The registry the app's queue checks chains against, and the one a job module registers its family into at import.

A module-level default for the reason :data:`~rehuco_core.tasks.DEFAULT_TASK_JOB_REGISTRY` is one: which chains exist is
a property of the build. Tests build their own instead of registering into this."""

DISK_FAMILY: Final = DEFAULT_CHAIN_REGISTRY.register("disk")
"""The family of this machine's disks, which every job that has not thought about its chain runs in."""
