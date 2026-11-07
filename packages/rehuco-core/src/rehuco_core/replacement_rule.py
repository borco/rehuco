"""Text replacements applied to a rendered location name, after the fields are substituted into the
pattern and before :func:`~rehuco_core.sanitized_names.sanitize_name` (#350, #577).

``sanitize_name`` runs ``pathvalidate.sanitize_filename``, which *deletes* characters like ``:`` and ``|``
rather than replacing them -- so a title like ``Foo: The Bar | Vol 2`` loses its separators outright unless
something turns them into something a filesystem name can keep first. A rule is that something.

**Each rule is plain text or a regular expression, per row.** Plain text is the common case -- a literal
``":"`` needs no escaping and cannot misfire -- and a rule flips to `re.sub` only when
:attr:`ReplacementRule.is_regex` is set.

**A rule with no text, or an unparsable regex, is never applied**: replacing an empty string would insert the
replacement between every character (``str.replace("", "-")``), so :func:`apply_location_replacements`
skips such a row rather than acting on it.
"""

import re
from collections.abc import Iterable
from typing import Final, NamedTuple


class ReplacementRule(NamedTuple):
    """One row: text to look for, what to replace it with, and whether ``text`` is a regular expression
    (order-sensitive, applied left to right across the whole table)."""

    text: str
    """The text a rule looks for -- matched literally unless :attr:`is_regex` is set. Empty is a
    validation problem, never applied (:data:`EMPTY_TEXT_PROBLEM`)."""

    replacement: str
    """What a match becomes; empty deletes every match outright, which is a legitimate rule (there is
    nothing here for a group-drop convention to lean on, unlike a location pattern). Under
    :attr:`is_regex` this is `re.sub`'s replacement, so a backreference (``\\1``) is honored."""

    is_regex: bool = False
    """Whether :attr:`text` is a regular expression (`re.sub`) rather than a literal (`str.replace`). An
    unparsable pattern is a validation problem, never applied (:data:`INVALID_REGEX_PROBLEM`)."""


EMPTY_TEXT_PROBLEM: Final = "A rule needs text to look for; an empty one would match everywhere."
INVALID_REGEX_PROBLEM: Final = "This does not parse as a regular expression."


def rule_problem(rule: ReplacementRule) -> str:
    """Why ``rule`` is not something :func:`apply_location_replacements` would act on, if it isn't.

    :param rule: the rule to check.
    :returns: :data:`EMPTY_TEXT_PROBLEM`, :data:`INVALID_REGEX_PROBLEM`, or ``""`` when the rule is fine.
    """
    if not rule.text:
        return EMPTY_TEXT_PROBLEM
    if rule.is_regex:
        try:
            re.compile(rule.text)
        except re.error:
            return INVALID_REGEX_PROBLEM
    return ""


def apply_location_replacements(text: str, rules: Iterable[ReplacementRule]) -> str:
    """Run ``text`` through ``rules`` in order: a plain-text rule as left-to-right string replacement, a
    regex rule as `re.sub`.

    A rule :func:`rule_problem` flags -- empty text, or a regex that fails to compile -- is skipped
    rather than applied.

    :param text: the rendered location name, before :func:`~rehuco_core.sanitized_names.sanitize_name`.
    :param rules: the rules to apply, in order.
    :returns: ``text`` with every usable rule's replacement made.
    """
    for rule in rules:
        if rule_problem(rule):
            continue
        text = re.sub(rule.text, rule.replacement, text) if rule.is_regex else text.replace(rule.text, rule.replacement)
    return text
