"""A record's license text, in a sidecar of its own beside it ([[assets#licenses]], #677).

``<stem>.rehuterms`` holds the terms an item was got under, in full: a store can change its terms or take them down,
and a copy fetched on demand would then be the wrong text or none. One per record, never shared between records.

The file is a YAML header between ``---`` lines -- ``title``, ``url`` where the text was read, and ``read``, the date
it was read -- then the terms as Markdown. A file with no ``url`` holds terms written for that item alone, which
nothing ever refreshes.

It belongs to the record as its screenshots and its ``.rehuser`` do: a rename and a move carry it by its stem
(:mod:`rehuco_core.rehu_rename`), and it is bookkeeping, never content, so no checksum covers it
(:mod:`rehuco_core.rehu_content_files`). A write happens under the record's own lock
(:func:`~rehuco_core.record_file_lock.locked_record`), which guards its sidecars too; this file has no lock of its own.
"""

import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import yaml
from borco_core import atomic_write_text

from .constants import LICENSE_SIDECAR_SUFFIX
from .rehu_parse_limits import oversized_file_reason

HEADER_FENCE: Final = "---"
"""The line that opens and closes the YAML header."""

TITLE_KEY: Final = "title"
"""The header key naming the license, as the store labels it."""

URL_KEY: Final = "url"
"""The header key holding where the text was read; absent for terms written for the item alone."""

READ_KEY: Final = "read"
"""The header key holding the date the text was read."""


class LicenseTermsError(ValueError):
    """A license sidecar that cannot be read."""


@dataclass(frozen=True, slots=True)
class LicenseTerms:
    """One record's license text, as its sidecar holds it.

    :param title: the license's name, as the store labels it.
    :param url: where the text was read, or ``None`` for terms written for this item alone.
    :param read: the date the text was read: a store's terms change, and a saved text is only as good as its date.
    :param text: the terms, as Markdown.
    """

    title: str
    url: str | None
    read: datetime.date
    text: str

    @classmethod
    def parse(cls, text: str, name: str) -> LicenseTerms:
        """Read a sidecar's text.

        ``yaml.safe_load`` raises more than ``YAMLError`` (:meth:`~rehuco_core.tc_document.TcDocument.load` says
        why), so all three are caught.

        :param text: the file's text.
        :param name: its file name, which every reason starts with.
        :returns: the terms.
        :raises LicenseTermsError: no header, a header that is not a mapping, or a key of the wrong type.
        """
        lines = text.splitlines(keepends=True)
        if not lines or lines[0].rstrip("\r\n") != HEADER_FENCE:
            raise LicenseTermsError(f"{name}: expected a YAML header opened by {HEADER_FENCE!r}.")
        closing = next((index for index in range(1, len(lines)) if lines[index].rstrip("\r\n") == HEADER_FENCE), None)
        if closing is None:
            raise LicenseTermsError(f"{name}: the YAML header is never closed by {HEADER_FENCE!r}.")
        try:
            header: object = yaml.safe_load("".join(lines[1:closing]))
        except (yaml.YAMLError, ValueError, RecursionError) as error:
            raise LicenseTermsError(f"{name}: invalid YAML header — {error}.") from error
        if not isinstance(header, dict):
            raise LicenseTermsError(f"{name}: expected a YAML mapping in the header.")
        return cls(
            title=cls.__title(header, name),
            url=cls.__url(header, name),
            read=cls.__read(header, name),
            text="".join(lines[closing + 1 :]).removeprefix("\n").removeprefix("\r\n"),
        )

    def to_text(self) -> str:
        """The sidecar's text: the header, a blank line, then the terms.

        :returns: the text; a header with no ``url`` key when there is none.
        """
        header: dict[str, Any] = {TITLE_KEY: self.title}
        if self.url is not None:
            header[URL_KEY] = self.url
        header[READ_KEY] = self.read
        dumped = yaml.safe_dump(header, sort_keys=False, allow_unicode=True)
        return f"{HEADER_FENCE}\n{dumped}{HEADER_FENCE}\n\n{self.text}"

    @staticmethod
    def __title(header: dict[Any, Any], name: str) -> str:
        """The header's ``title``.

        :param header: the parsed header.
        :param name: the file name, for the reason.
        :returns: the title.
        :raises LicenseTermsError: it is missing or not a string.
        """
        title = header.get(TITLE_KEY)
        if not isinstance(title, str):
            raise LicenseTermsError(f"{name}: {TITLE_KEY} is missing or not a string.")
        return title

    @staticmethod
    def __url(header: dict[Any, Any], name: str) -> str | None:
        """The header's ``url``, if it has one.

        :param header: the parsed header.
        :param name: the file name, for the reason.
        :returns: the url, or ``None`` when the header names none.
        :raises LicenseTermsError: it is present and not a string.
        """
        url = header.get(URL_KEY)
        if url is not None and not isinstance(url, str):
            raise LicenseTermsError(f"{name}: {URL_KEY} is not a string.")
        return url

    @staticmethod
    def __read(header: dict[Any, Any], name: str) -> datetime.date:
        """The header's ``read``.

        A datetime is a date to :func:`isinstance`, and the header holds a day, so one is refused rather than kept.

        :param header: the parsed header.
        :param name: the file name, for the reason.
        :returns: the date.
        :raises LicenseTermsError: it is missing or not a date.
        """
        read = header.get(READ_KEY)
        if not isinstance(read, datetime.date) or isinstance(read, datetime.datetime):
            raise LicenseTermsError(f"{name}: {READ_KEY} is missing or not a date.")
        return read


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


def read_license_terms(record: Path) -> LicenseTerms | None:
    """Read a record's license sidecar, held to the same size cap as a record ([[data-model#write-integrity]]).

    :param record: the ``.rehu``.
    :returns: the terms, or ``None`` when the record has no sidecar.
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
        # an editor may save a byte-order mark in front of the header; it is no part of the text
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as error:
        raise LicenseTermsError(f"{path.name}: not UTF-8 text — {error}.") from error
    return LicenseTerms.parse(text, path.name)


def write_license_terms(record: Path, terms: LicenseTerms) -> None:
    """Write a record's license sidecar atomically, replacing whatever it held.

    The caller holds the record's lock (:func:`~rehuco_core.record_file_lock.locked_record`).

    :param record: the ``.rehu``.
    :param terms: the terms to keep.
    :raises OSError: it could not be written.
    """
    atomic_write_text(license_terms_path(record), terms.to_text())
