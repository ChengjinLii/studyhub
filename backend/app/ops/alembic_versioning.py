"""Bootstrap the Alembic version table safely across supported databases."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.engine import Connection


ALEMBIC_VERSION_TABLE = "alembic_version"
ALEMBIC_VERSION_COLUMN = "version_num"
ALEMBIC_VERSION_LENGTH = 128


def prepare_alembic_version_table(connection: Connection) -> None:
    """Ensure Alembic can store every committed StudyHub revision identifier.

    Alembic creates ``version_num`` as ``VARCHAR(32)`` by default.  This project
    has historical revision identifiers longer than that, which SQLite silently
    accepts but MySQL and PostgreSQL reject.  The bootstrap runs before Alembic
    reads or writes its own version table, so a fresh database and an existing
    strict-dialect database both converge without renaming revision history.
    """

    inspector = sa.inspect(connection)
    if not inspector.has_table(ALEMBIC_VERSION_TABLE):
        _version_table().create(connection)
        return

    columns = {column["name"]: column for column in inspector.get_columns(ALEMBIC_VERSION_TABLE)}
    version_column = columns.get(ALEMBIC_VERSION_COLUMN)
    if version_column is None:
        raise RuntimeError(f"{ALEMBIC_VERSION_TABLE} is missing {ALEMBIC_VERSION_COLUMN}")

    length = getattr(version_column["type"], "length", None)
    if length is None or length >= ALEMBIC_VERSION_LENGTH:
        return

    dialect_name = connection.dialect.name
    if dialect_name == "sqlite":
        # SQLite does not enforce VARCHAR lengths, so changing it would require
        # a table rewrite for no correctness benefit.
        return

    preparer = connection.dialect.identifier_preparer
    table_name = preparer.quote(ALEMBIC_VERSION_TABLE)
    column_name = preparer.quote(ALEMBIC_VERSION_COLUMN)
    if dialect_name == "mysql":
        statement = f"ALTER TABLE {table_name} MODIFY COLUMN {column_name} VARCHAR({ALEMBIC_VERSION_LENGTH}) NOT NULL"
    elif dialect_name == "postgresql":
        statement = f"ALTER TABLE {table_name} ALTER COLUMN {column_name} TYPE VARCHAR({ALEMBIC_VERSION_LENGTH})"
    else:
        raise RuntimeError(
            f"{ALEMBIC_VERSION_TABLE}.{ALEMBIC_VERSION_COLUMN} is too short for StudyHub revisions on unsupported "
            f"dialect {dialect_name!r}; widen it to VARCHAR({ALEMBIC_VERSION_LENGTH}) before retrying"
        )
    connection.execute(sa.text(statement))


def _version_table() -> sa.Table:
    metadata = sa.MetaData()
    return sa.Table(
        ALEMBIC_VERSION_TABLE,
        metadata,
        sa.Column(ALEMBIC_VERSION_COLUMN, sa.String(ALEMBIC_VERSION_LENGTH), primary_key=True, nullable=False),
    )
