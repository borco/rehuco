"""A record's license texts, in a sidecar of its own beside it ([[assets#licenses]], #677, #705).

``<stem>.rehuterms`` holds the terms an item was got under, in full: a store can change its terms or take them down,
and a copy fetched on demand would then be the wrong text or none. One per record, never shared between records.

The file is a JSON object keyed by license id -- each one of the record's ``licenses``
(:class:`~rehuco_core.AssetLicense`) -- whose value holds ``title``, ``url`` where the text was read, ``read``, the date
it was read, and ``text``, the terms as Markdown **as a list of their lines**, so the file reads line by line and every
line is kept exactly. Terms with no ``url`` were written for that item alone, and nothing ever refreshes them.

It belongs to the record as its screenshots and its ``.rehuser`` do: a rename and a move carry it by its stem
(:mod:`rehuco_core.rehu_rename`), and it is bookkeeping, never content, so no checksum covers it
(:mod:`rehuco_core.rehu_content_files`). A write happens under the record's own lock
(:func:`~rehuco_core.record_file_lock.locked_record`), which guards its sidecars too; this file has no lock of its own.
"""

import datetime
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from borco_core import atomic_write_text

from .constants import LICENSE_SIDECAR_SUFFIX
from .rehu_parse_limits import oversized_file_reason

TITLE_KEY: Final = "title"
"""The key naming the license, as the store labels it."""

URL_KEY: Final = "url"
"""The key holding where the text was read; absent for terms written for the item alone."""

READ_KEY: Final = "read"
"""The key holding the date the text was read, as an ISO day."""

TEXT_KEY: Final = "text"
"""The key holding the terms' Markdown: one string in :meth:`LicenseTerms.to_data`, a list of its lines in the file."""

LINE_END: Final = "\n"
"""What the file's list of lines is split at and joined by: a text is kept with LF line ends."""


class LicenseTermsError(ValueError):
    """A license sidecar that cannot be read."""


@dataclass(frozen=True, slots=True)
class LicenseTerms:
    """The text of one of a record's licenses, as its sidecar holds it.

    :param title: the license's name, as the store labels it.
    :param url: where the text was read, or ``None`` for terms written for this item alone.
    :param read: the date the text was read: a store's terms change, and a saved text is only as good as its date.
    :param text: the terms, as Markdown.
    """

    title: str
    url: str | None
    read: datetime.date
    text: str

    def to_data(self) -> dict[str, Any]:
        """These terms as the JSON primitives a document holds them as in memory
        (:data:`~rehuco_core.LICENSE_TERMS_KEY`).

        :returns: ``title``, ``url`` where there is one, ``read`` as an ISO date and ``text``.
        """
        data: dict[str, Any] = {TITLE_KEY: self.title}
        if self.url is not None:
            data[URL_KEY] = self.url
        data[READ_KEY] = self.read.isoformat()
        data[TEXT_KEY] = self.text
        return data

    def to_file_data(self) -> dict[str, Any]:
        """These terms as the file holds them: :meth:`to_data`, with the text as a list of its lines.

        :returns: the object.
        """
        return {**self.to_data(), TEXT_KEY: self.text.split(LINE_END)}

    @classmethod
    def from_data(cls, data: object, *, lines: bool = False) -> LicenseTerms:
        """Read the terms :meth:`to_data` or :meth:`to_file_data` wrote.

        :param data: what a document holds for one license id, or what the file does.
        :param lines: whether the text is the file's list of lines rather than one string.
        :returns: the terms.
        :raises LicenseTermsError: it is not an object of those four keys, or its date is not a day.
        """
        if not isinstance(data, dict):
            raise LicenseTermsError("The license terms are not an object.")
        title, url, read, text = data.get(TITLE_KEY), data.get(URL_KEY), data.get(READ_KEY), data.get(TEXT_KEY)
        if lines:
            text = cls.__joined(text)
        if not isinstance(title, str) or not isinstance(text, str) or not (url is None or isinstance(url, str)):
            raise LicenseTermsError("The license terms need a title and a text, and a url that is a string.")
        try:
            day = datetime.date.fromisoformat(read) if isinstance(read, str) else None
        except ValueError:
            day = None
        if day is None:
            raise LicenseTermsError("The license terms' date is not a day.")
        return cls(title, url, day, text)

    @staticmethod
    def __joined(text: object) -> str | None:
        """The file's list of lines as one text.

        :param text: what the file holds for the text.
        :returns: the lines, joined; ``None`` when it is not a list of strings.
        """
        if not isinstance(text, list) or not all(isinstance(line, str) for line in text):
            return None
        return LINE_END.join(text)


@dataclass(frozen=True, slots=True)
class LicenseTermsSet:
    """Every license text a record keeps, by license id ([[assets#licenses]], #705).

    Compared as a mapping, so two sets of the same texts are equal in any order: reordering a record's licenses never
    rewrites its sidecar.

    :param terms: the texts, by license id, in the order the file lists them.
    """

    terms: Mapping[str, LicenseTerms] = field(default_factory=dict)

    def get(self, license_id: str) -> LicenseTerms | None:
        """One license's text.

        :param license_id: the license's short id.
        :returns: its terms, or ``None`` when none are kept for it.
        """
        return self.terms.get(license_id)

    def with_terms(self, license_id: str, terms: LicenseTerms | None) -> LicenseTermsSet:
        """This set with one license's text set or removed.

        :param license_id: the license's short id.
        :param terms: its terms; ``None`` removes them.
        :returns: the new set; a new id goes last.
        """
        if terms is None:
            return LicenseTermsSet({key: value for key, value in self.terms.items() if key != license_id})
        return LicenseTermsSet({**self.terms, license_id: terms})

    def renamed(self, old: str, new: str) -> LicenseTermsSet:
        """This set with one license's text kept under another id, in its place.

        :param old: the id the text is kept under.
        :param new: the id to keep it under; a text already kept under it is dropped.
        :returns: the new set; this one when ``old`` has no text or is ``new``.
        """
        if old not in self.terms or old == new:
            return self
        return LicenseTermsSet({new if key == old else key: value for key, value in self.terms.items() if key != new})

    @classmethod
    def parse(cls, text: str, name: str) -> LicenseTermsSet:
        """Read a sidecar's text.

        :param text: the file's text.
        :param name: its file name, which every reason starts with.
        :returns: the texts.
        :raises LicenseTermsError: it is not JSON, not an object, or holds an entry that cannot be read.
        """
        try:
            data: object = json.loads(text)
        except (ValueError, RecursionError) as error:
            raise LicenseTermsError(f"{name}: invalid JSON — {error}.") from error
        if not isinstance(data, dict):
            raise LicenseTermsError(f"{name}: expected a JSON object of license texts by license id.")
        terms: dict[str, LicenseTerms] = {}
        for license_id, entry in data.items():
            try:
                terms[license_id] = LicenseTerms.from_data(entry, lines=True)
            except LicenseTermsError as error:
                raise LicenseTermsError(f"{name}: {license_id}: {error}") from error
        return cls(terms)

    def to_text(self) -> str:
        """The sidecar's text, written as a ``.rehu`` is: two-space indents, characters as they are, a final newline.

        :returns: the text.
        """
        data = {license_id: terms.to_file_data() for license_id, terms in self.terms.items()}
        return json.dumps(data, indent=2, ensure_ascii=False) + LINE_END

    def to_data(self) -> dict[str, Any]:
        """These texts as the JSON primitives a document holds them as in memory
        (:data:`~rehuco_core.LICENSE_TERMS_KEY`).

        :returns: each license's :meth:`LicenseTerms.to_data`, by id.
        """
        return {license_id: terms.to_data() for license_id, terms in self.terms.items()}

    @classmethod
    def from_data(cls, data: object) -> LicenseTermsSet:
        """Read the texts :meth:`to_data` wrote.

        :param data: what a document holds under :data:`~rehuco_core.LICENSE_TERMS_KEY`.
        :returns: the texts.
        :raises LicenseTermsError: it is not an object, or holds an entry that cannot be read.
        """
        if not isinstance(data, dict):
            raise LicenseTermsError("The license texts are not an object.")
        return cls({str(license_id): LicenseTerms.from_data(entry) for license_id, entry in data.items()})


def license_terms_path(record: Path) -> Path:
    """Where a record's license sidecar sits.

    :param record: the ``.rehu``.
    :returns: ``<stem>.rehuterms`` beside it.
    """
    return record.with_name(f"{record.stem}{LICENSE_SIDECAR_SUFFIX}")


def license_terms_owner(filename: str) -> str | None:
    """Whose license sidecar a file is, by its name alone.

    :param filename: a file name.
    :returns: the record stem it belongs to, or ``None`` when it is no license sidecar.
    """
    if not filename.lower().endswith(LICENSE_SIDECAR_SUFFIX):
        return None
    stem = filename[: -len(LICENSE_SIDECAR_SUFFIX)]
    return stem or None


def is_license_terms_name(filename: str) -> bool:
    """Whether a file is a license sidecar -- what scans, checksums and listings never take for content.

    :param filename: a file name.
    :returns: whether it is named as one.
    """
    return license_terms_owner(filename) is not None


def read_license_terms(record: Path) -> LicenseTermsSet | None:
    """Read a record's license sidecar, held to the same size cap as a record ([[data-model#write-integrity]]).

    :param record: the ``.rehu``.
    :returns: the texts, or ``None`` when the record has no sidecar.
    :raises LicenseTermsError: it is not UTF-8 text, could not be parsed, or trips the size cap.
    :raises OSError: it could not be read.
    """
    path = license_terms_path(record)
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return None
    oversized = oversized_file_reason(size)
    if oversized is not None:
        raise LicenseTermsError(f"{path.name}: refusing to parse — {oversized}")
    try:
        # an editor may save a byte-order mark in front of the object; it is no part of the text
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as error:
        raise LicenseTermsError(f"{path.name}: not UTF-8 text — {error}.") from error
    return LicenseTermsSet.parse(text, path.name)


def write_license_terms(record: Path, terms: LicenseTermsSet) -> None:
    """Write a record's license sidecar atomically, replacing whatever it held.

    The caller holds the record's lock (:func:`~rehuco_core.record_file_lock.locked_record`).

    :param record: the ``.rehu``.
    :param terms: the texts to keep.
    :raises OSError: it could not be written.
    """
    atomic_write_text(license_terms_path(record), terms.to_text())
