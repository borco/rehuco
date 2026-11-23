"""How a class in a scraper script fares in a role it declares -- a scraper's or a scraper wizard's -- as the Scrapers
settings page shows it ([[acquisition-tooling#scraper-registry]], #683).

The protocols are structural, so a class missing one member is otherwise indistinguishable from a helper that was
never meant to be a scraper. A class that has a role's one telling method has *declared* the role, and is then either
fit for it or reported with what it lacks.
"""

from dataclasses import dataclass, replace
from enum import Enum
from typing import get_protocol_members


class RoleState(Enum):
    """How a class fares in a role it declares."""

    OK = "ok"
    """Fit for the role, and the one used."""

    ERROR = "error"
    """Declares the role and cannot fill it."""

    OVERRIDDEN_OK = "overridden_ok"
    """Fit for the role, and passed over for another that claims the same key."""

    OVERRIDDEN_ERROR = "overridden_error"
    """Cannot fill the role, and another claims its key anyway."""


@dataclass(frozen=True)
class RoleReport:
    """One class in one role.

    :param owner: the class.
    :param state: how it fares.
    :param instance: the class built with no arguments; ``None`` when it cannot be.
    :param problem: what is wrong, or what replaced it, as the page's Error column says it; empty for none.
    """

    owner: type
    state: RoleState
    instance: object | None = None
    problem: str = ""

    @property
    def class_key(self) -> str:
        """The class's identity, the same for one class read by two registries, and the key its **Use browser** tick
        is saved under (`~rehuco_agent.settings.scrapers_settings.scraper_key`).

        :returns: ``"<module>.<qualname>"``.
        """
        return f"{self.owner.__module__}.{self.owner.__qualname__}"

    @staticmethod
    def of(candidate: type, protocol: type, marker: str) -> RoleReport | None:
        """Report how ``candidate`` fares as a ``protocol``.

        :param candidate: the class.
        :param protocol: the role's structural protocol.
        :param marker: the protocol's method that declares the role: a class without it never meant to fill it.
        :returns: the report; ``None`` for a class that does not declare the role.
        """
        if not callable(getattr(candidate, marker, None)):
            return None
        try:
            # a member may be a property of the user's own, which raises what it likes when read
            instance = candidate()
            missing = sorted(name for name in get_protocol_members(protocol) if not hasattr(instance, name))
        except Exception as error:  # pylint: disable=broad-exception-caught
            problem = f"{candidate.__name__} cannot be set up with no arguments: {type(error).__name__}: {error}"
            return RoleReport(candidate, RoleState.ERROR, None, problem)
        if missing:
            return RoleReport(candidate, RoleState.ERROR, instance, f"{candidate.__name__} lacks {', '.join(missing)}")
        return RoleReport(candidate, RoleState.OK, instance)

    def failed(self, problem: str) -> RoleReport:
        """This report, turned into a failure.

        :param problem: what is wrong.
        :returns: the report.
        """
        return replace(self, state=RoleState.ERROR, problem=problem)

    def overridden(self, by: str) -> RoleReport:
        """This report, passed over for another class claiming the same key.

        :param by: where the class that is used comes from, as the page names it.
        :returns: the report, its own problem kept ahead of what replaced it.
        """
        state = RoleState.OVERRIDDEN_OK if self.state is RoleState.OK else RoleState.OVERRIDDEN_ERROR
        replaced = f"Replaced by the one in {by}"
        return replace(self, state=state, problem=f"{self.problem}; {replaced}" if self.problem else replaced)
