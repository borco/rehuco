"""``.rehudb`` cache schema migrations ([[data-model#cache-schema]], #372).

The one target whose steps reshape a **database** rather than a parsed payload, so a step takes a
:class:`sqlite3.Connection` instead of a dict and the version lives in ``PRAGMA user_version`` instead of a
key. Otherwise the shape every target has: a ``BASE_VERSION``, a ``CHAIN`` of ``(version, step)`` pairs, a head
derived from it. :class:`~rehuco_core.rehudb.CatalogCache` walks the chain, one transaction per step, stamping
``user_version`` inside the same transaction so a step that fails leaves the version it started from.

Forward only. A cache stamped **newer** than :data:`CURRENT_VERSION` is never written: being derived and
disposable, it is discarded and rebuilt from the records, which is always cheaper than understanding it. A step
is free to be *drop and rebuild* for the same reason.

Like every other step, these inline the literals they operate on: a migration is a frozen historical record,
and a column renamed later must not rewrite what version 1 created.
"""

import sqlite3
from collections.abc import Callable
from typing import Final

from ..runner import chain_head

SchemaStep = Callable[[sqlite3.Connection], None]
"""A cache migration step: reshapes the schema in place, inside the transaction its caller opened."""

SchemaChain = tuple[tuple[int, SchemaStep], ...]
"""An ordered ``(target, step)`` chain of cache steps -- the cache's counterpart of
:data:`~rehuco_core.migrations.runner.Chain`."""

BASE_VERSION: Final = 0
"""What an empty file's ``user_version`` reads -- SQLite's own default, so a fresh cache is simply one every
step is still ahead of."""

V1_STATEMENTS: Final = (
    """
    CREATE TABLE roots (
        id TEXT PRIMARY KEY,
        label TEXT NOT NULL,
        path TEXT NOT NULL,
        position INTEGER NOT NULL,
        removable INTEGER NOT NULL DEFAULT 0,
        reachable INTEGER,
        scanned_at REAL
    )
    """,
    """
    CREATE TABLE resources (
        id INTEGER PRIMARY KEY,
        root_id TEXT NOT NULL REFERENCES roots (id) ON DELETE CASCADE,
        path TEXT NOT NULL,
        path_key TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('rehu', 'tc')),
        uuid TEXT NOT NULL DEFAULT '',
        type TEXT NOT NULL DEFAULT '',
        title TEXT NOT NULL DEFAULT '',
        publisher TEXT NOT NULL DEFAULT '',
        url TEXT NOT NULL DEFAULT '',
        released TEXT,
        current_size INTEGER,
        updated TEXT NOT NULL DEFAULT '',
        mtime_ns INTEGER NOT NULL,
        size INTEGER NOT NULL,
        content_hash TEXT NOT NULL,
        error TEXT,
        scanned_at REAL NOT NULL,
        UNIQUE (root_id, path_key)
    )
    """,
    "CREATE INDEX resources_uuid ON resources (uuid)",
    "CREATE TABLE authors (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE)",
    "CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE)",
    "CREATE TABLE publishers (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE)",
    """
    CREATE TABLE resource_authors (
        resource_id INTEGER NOT NULL REFERENCES resources (id) ON DELETE CASCADE,
        value_id INTEGER NOT NULL REFERENCES authors (id) ON DELETE CASCADE,
        position INTEGER NOT NULL,
        PRIMARY KEY (resource_id, value_id)
    )
    """,
    """
    CREATE TABLE resource_tags (
        resource_id INTEGER NOT NULL REFERENCES resources (id) ON DELETE CASCADE,
        value_id INTEGER NOT NULL REFERENCES tags (id) ON DELETE CASCADE,
        position INTEGER NOT NULL,
        PRIMARY KEY (resource_id, value_id)
    )
    """,
    """
    CREATE TABLE resource_publishers (
        resource_id INTEGER NOT NULL REFERENCES resources (id) ON DELETE CASCADE,
        value_id INTEGER NOT NULL REFERENCES publishers (id) ON DELETE CASCADE,
        position INTEGER NOT NULL,
        PRIMARY KEY (resource_id, value_id)
    )
    """,
    "CREATE INDEX resource_authors_value ON resource_authors (value_id)",
    "CREATE INDEX resource_tags_value ON resource_tags (value_id)",
    "CREATE INDEX resource_publishers_value ON resource_publishers (value_id)",
)
"""Version 1's schema, statement by statement -- frozen here rather than built from the live column names."""

V2_JOIN_TABLES: Final = ("resource_authors", "resource_tags", "resource_publishers")
"""The join tables version 2 gives a spelling of their own -- frozen, like :data:`V1_STATEMENTS`."""

V3_COLUMNS: Final = (
    ("advertised_duration", "INTEGER"),
    ("original_duration", "INTEGER"),
    ("current_duration", "INTEGER"),
    ("level", "TEXT"),
    ("advertised_count", "TEXT"),
    ("current_count", "INTEGER"),
)
"""The type-specific columns version 3 adds to ``resources``, with their SQL types -- frozen, like
:data:`V1_STATEMENTS`."""


def create_schema_v1(connection: sqlite3.Connection) -> None:
    """0 -> 1: the first schema -- roots, the resources under them, and the three value tables with their joins.

    :param connection: the cache, inside the transaction the caller opened.
    """
    for statement in V1_STATEMENTS:
        connection.execute(statement)


def add_join_spellings_v2(connection: sqlite3.Connection) -> None:
    """1 -> 2: each join row keeps the name **as its resource spells it** (#377).

    The value tables hold one row per name, unique case-insensitively, so they can only ever keep one spelling: the
    first one stored. A resource whose file changed ``foo bar`` to ``Foo Bar`` matched the old row and went on
    showing the old case. The value tables stay what matching and filtering go through; the spelling shown moves to
    the join, per resource. A row written before this step has no spelling of its own (``NULL``) and reads as the
    shared one until its resource is scanned again.

    :param connection: the cache, inside the transaction the caller opened.
    """
    for table in V2_JOIN_TABLES:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN name TEXT")


def add_type_fields_v3(connection: sqlite3.Connection) -> None:
    """2 -> 3: the type-specific fields a browser shows as columns -- a tutorial's durations and level, a reference
    pack's image counts (#399).

    Typed columns rather than one generic value column, so a duration or a count sorts and compares as a number;
    ``advertised_count`` is text because the claim it holds may be open-ended (``500+``), and ``level`` a JSON
    array because the field is multi-choice.

    A row written before this step keeps its place but has no values for them, and nothing on disk says it is
    stale: so its stat signature is cleared too, which no real file matches, and the next scan of any kind reads
    the record again rather than trusting the row as current.

    :param connection: the cache, inside the transaction the caller opened.
    """
    for column, sql_type in V3_COLUMNS:
        connection.execute(f"ALTER TABLE resources ADD COLUMN {column} {sql_type}")
    connection.execute("UPDATE resources SET mtime_ns = 0, content_hash = ''")


CHAIN: Final[SchemaChain] = ((1, create_schema_v1), (2, add_join_spellings_v2), (3, add_type_fields_v3))
"""This target's ordered ``(target, step)`` chain."""

CURRENT_VERSION: Final = chain_head(CHAIN, BASE_VERSION)
"""The newest cache schema this build understands -- the chain's head, derived so it cannot drift."""
