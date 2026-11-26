"""One license an asset is held under ([[assets#licenses]], #705): an entry of its block's ``licenses``.

An item can be owned under several licenses at once -- a Fab item under the Standard License and its *UEFN - Reference
only* tier, say -- so the block holds a list, in the user's order, each entry naming one license by its short id and,
where the store states its terms, where they are. The terms themselves are in the record's ``.rehuterms``, one text per
id (:mod:`rehuco_core.license_terms`).
"""

from dataclasses import dataclass
from typing import Any, Final

LICENSE_KEY: Final = "license"
"""An entry's key holding the license's short id, such as ``fab-standard``."""

URL_KEY: Final = "url"
"""An entry's key holding where the store states the terms; absent when it states none."""


@dataclass(frozen=True, slots=True)
class AssetLicense:
    """One entry of an asset's ``licenses``.

    :param license: the license's short id, such as ``fab-standard`` (:data:`~rehuco_core.ASSET_LICENSES`); unique
        within one record's list.
    :param url: where the store states the terms, or ``None`` when it states none (``fab-ue-only``).
    """

    license: str
    url: str | None = None

    def to_data(self) -> dict[str, str]:
        """This entry as the block stores it.

        :returns: ``license``, and ``url`` where there is one.
        """
        return {LICENSE_KEY: self.license} if self.url is None else {LICENSE_KEY: self.license, URL_KEY: self.url}

    @classmethod
    def from_data(cls, data: Any) -> AssetLicense | None:
        """Read one stored entry.

        :param data: what the block holds at one place of its list.
        :returns: the entry; ``None`` for one that is not an object of a non-empty ``license`` string and an optional
            ``url`` string.
        """
        if not isinstance(data, dict):
            return None
        license_id, url = data.get(LICENSE_KEY), data.get(URL_KEY)
        if not isinstance(license_id, str) or not license_id or not (url is None or isinstance(url, str)):
            return None
        return cls(license_id, url)

    @classmethod
    def read_list(cls, value: Any) -> list[AssetLicense]:
        """A stored ``licenses`` list's read value: its readable entries, in order, the first of each id.

        An entry that cannot be read, or repeats an id, is skipped rather than guessed at; the record locks for it
        (:func:`~rehuco_core.rehu_locks.invalid_asset_reasons`), so the original stays recoverable by hand.

        :param value: the stored value.
        :returns: the entries; empty when the key is absent or holds a non-list.
        """
        if not isinstance(value, list):
            return []
        entries: list[AssetLicense] = []
        seen: set[str] = set()
        for item in value:
            entry = cls.from_data(item)
            if entry is not None and entry.license not in seen:
                seen.add(entry.license)
                entries.append(entry)
        return entries

    @staticmethod
    def list_data(entries: list[AssetLicense]) -> list[dict[str, str]]:
        """Entries as the block stores them.

        :param entries: the entries, in order.
        :returns: each one's :meth:`to_data`.
        """
        return [entry.to_data() for entry in entries]
