"""Tests for `RoleReport`: how a class fares in a role it declares (#683)."""

from typing import Protocol, runtime_checkable

from rehuco_agent.scraping.role_report import RoleReport, RoleState


@runtime_checkable
class Greeter(Protocol):
    """A role of two members, for the tests."""

    @property
    def name(self) -> str:  # pyright: ignore[reportReturnType]
        """Who greets."""

    def greet(self) -> str:  # pyright: ignore[reportReturnType]
        """The greeting.

        :returns: the greeting.
        """


# pylint: disable=missing-function-docstring,too-few-public-methods


class Fit:
    """Has both members."""

    name = "fit"

    def greet(self) -> str:
        return "hello"


class Nameless:
    """Declares the role and lacks its name."""

    def greet(self) -> str:
        return "hello"


class NeedsArgs:
    """Declares the role and cannot be built bare."""

    name = "args"

    def __init__(self, required: str) -> None:
        self.required = required

    def greet(self) -> str:
        return "hello"


class RaisingName:
    """Declares the role, and its name raises when read."""

    @property
    def name(self) -> str:
        raise ValueError("no name today")

    def greet(self) -> str:
        return "hello"


class Bystander:
    """Never meant to greet."""

    name = "bystander"


class DataMarker:
    """Has the marker's name, as data."""

    name = "data"
    greet = "hello"


# pylint: enable=missing-function-docstring,too-few-public-methods


def test_a_class_with_every_member_is_fit_and_built() -> None:
    """A class of the role's whole shape is reported fit, with the instance built (#683).

    **Test steps:**

    * report on a class with both members
    * verify it is fit, carries an instance of the class and no problem, under the class's module and name
    """
    report = RoleReport.of(Fit, Greeter, "greet")

    assert report is not None
    assert report.state is RoleState.OK
    assert isinstance(report.instance, Fit)
    assert report.problem == ""
    assert report.class_key == f"{__name__}.Fit"


def test_a_class_without_the_marker_declares_no_role() -> None:
    """A class lacking the role's telling method, or holding data under its name, is not reported at all (#683).

    **Test steps:**

    * report on a class without the method and on one whose attribute of that name is no method
    * verify neither has a report
    """
    assert RoleReport.of(Bystander, Greeter, "greet") is None
    assert RoleReport.of(DataMarker, Greeter, "greet") is None


def test_a_class_that_declares_the_role_and_cannot_fill_it_says_why() -> None:
    """A missing member, a constructor needing arguments and a member that raises are each a failure naming the
    cause, never an exception (#683).

    **Test steps:**

    * report on a class lacking a member, one needing arguments, one whose property raises
    * verify each is a failure whose problem names the class and the cause
    """
    nameless = RoleReport.of(Nameless, Greeter, "greet")
    needs_args = RoleReport.of(NeedsArgs, Greeter, "greet")
    raising = RoleReport.of(RaisingName, Greeter, "greet")

    assert nameless is not None and needs_args is not None and raising is not None
    assert (nameless.state, nameless.problem) == (RoleState.ERROR, "Nameless lacks name")
    assert isinstance(nameless.instance, Nameless)
    assert needs_args.state is RoleState.ERROR
    assert needs_args.instance is None
    assert needs_args.problem.startswith("NeedsArgs cannot be set up with no arguments: TypeError")
    assert raising.state is RoleState.ERROR
    assert raising.problem == "RaisingName cannot be set up with no arguments: ValueError: no name today"


def test_a_report_turns_into_a_failure_or_a_replaced_one() -> None:
    """A fit class found wanting later fails with the reason; one passed over says what replaced it, a failure kept
    ahead of that (#683).

    **Test steps:**

    * fail a fit report, and override a fit one and a failed one
    * verify the states and the problems
    """
    fit = RoleReport.of(Fit, Greeter, "greet")
    assert fit is not None

    failed = fit.failed("Fit's name is taken")
    replaced = fit.overridden("shop.py")
    replaced_failure = failed.overridden("shop.py")

    assert (failed.state, failed.problem) == (RoleState.ERROR, "Fit's name is taken")
    assert (replaced.state, replaced.problem) == (RoleState.OVERRIDDEN_OK, "Replaced by the one in shop.py")
    assert replaced_failure.state is RoleState.OVERRIDDEN_ERROR
    assert replaced_failure.problem == "Fit's name is taken; Replaced by the one in shop.py"
