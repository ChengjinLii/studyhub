from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.engine import Engine
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.schema import Column, MetaData, Table

from app.core.db import LEGACY_TABLE_COMPATIBILITY, get_engine, has_compatible_legacy_table


DESTRUCTIVE_SQL_PATTERN = re.compile(
    r"\b(DELETE|DROP|TRUNCATE|RENAME|CHANGE|MODIFY|INSERT|UPDATE|CREATE\s+TABLE|DROP\s+COLUMN)\b",
    re.IGNORECASE,
)


def build_schema_audit_payload(
    *,
    engine: Engine | None = None,
    metadata: MetaData | None = None,
) -> dict[str, Any]:
    engine = engine or get_engine()
    if metadata is None:
        from app.models import Base

        metadata = Base.metadata

    inspector = inspect(engine)
    actual_tables = set(inspector.get_table_names())
    actual_column_details_by_table = {}
    actual_columns_by_table = {}
    for table_name in actual_tables:
        columns = inspector.get_columns(table_name)
        details = {str(column["name"]): column for column in columns}
        actual_column_details_by_table[table_name] = details
        actual_columns_by_table[table_name] = set(details)
    actual_indexes_by_table = {
        table_name: _index_column_sets(inspector.get_indexes(table_name))
        for table_name in actual_tables
    }
    return compare_metadata_schema(
        metadata=metadata,
        actual_tables=actual_tables,
        actual_columns_by_table=actual_columns_by_table,
        actual_column_details_by_table=actual_column_details_by_table,
        actual_indexes_by_table=actual_indexes_by_table,
        dialect=engine.dialect,
    )


def compare_metadata_schema(
    *,
    metadata: MetaData,
    actual_tables: set[str],
    actual_columns_by_table: Mapping[str, set[str]],
    actual_indexes_by_table: Mapping[str, set[tuple[str, ...]]] | None,
    dialect: Dialect,
    actual_column_details_by_table: Mapping[str, Mapping[str, Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    expected_tables = metadata.tables
    missing_tables: list[str] = []
    legacy_compatible_tables: list[dict[str, Any]] = []
    missing_columns: list[dict[str, Any]] = []
    manual_review_columns: list[dict[str, Any]] = []
    missing_indexes: list[dict[str, Any]] = []
    column_warnings: list[dict[str, Any]] = []

    for table_name in sorted(expected_tables):
        table = expected_tables[table_name]
        if table_name not in actual_tables:
            if has_compatible_legacy_table(table_name, actual_tables):
                covered_by = [
                    legacy_table
                    for legacy_table in LEGACY_TABLE_COMPATIBILITY.get(table_name, ())
                    if legacy_table in actual_tables
                ]
                legacy_compatible_tables.append({"table": table_name, "coveredBy": covered_by})
                continue
            missing_tables.append(table_name)
            continue

        actual_columns = actual_columns_by_table.get(table_name, set())
        actual_column_details = (actual_column_details_by_table or {}).get(table_name, {})
        for column in table.columns:
            if column.name in actual_columns:
                actual_column = actual_column_details.get(column.name)
                if actual_column is not None:
                    column_warnings.extend(_column_warning_payloads(table, column, actual_column, dialect))
            else:
                item = _missing_column_payload(table, column, dialect)
                missing_columns.append(item)
                if not item["autoMigratable"]:
                    manual_review_columns.append(item)

        missing_indexes.extend(
            _missing_single_column_indexes(
                table,
                actual_columns=actual_columns,
                actual_index_columns=actual_indexes_by_table.get(table_name, set()) if actual_indexes_by_table else set(),
                dialect=dialect,
            )
        )

    ready = not missing_tables and not missing_columns
    statements = [item["sql"] for item in missing_columns if item["autoMigratable"]]
    return {
        "expectedTableCount": len(expected_tables),
        "actualTableCount": len(actual_tables),
        "missingTableCount": len(missing_tables),
        "missingTables": missing_tables,
        "legacyCompatibleTableCount": len(legacy_compatible_tables),
        "legacyCompatibleTables": legacy_compatible_tables,
        "missingColumnCount": len(missing_columns),
        "missingColumns": missing_columns,
        "manualReviewColumnCount": len(manual_review_columns),
        "manualReviewColumns": manual_review_columns,
        "columnWarningCount": len(column_warnings),
        "columnWarnings": column_warnings,
        "missingIndexCount": len(missing_indexes),
        "missingIndexes": missing_indexes,
        "destructiveChangeCount": 0,
        "destructiveChanges": [],
        "additiveStatementCount": len(statements),
        "additiveStatements": statements,
        "executable": not missing_tables and not manual_review_columns,
        "ready": ready,
    }


def build_additive_migration_payload(*, engine: Engine | None = None, metadata: MetaData | None = None) -> dict[str, Any]:
    return build_scoped_additive_migration_payload(engine=engine, metadata=metadata, only_columns=None)


def build_scoped_schema_audit_payload(
    *,
    engine: Engine | None = None,
    metadata: MetaData | None = None,
    only_columns: set[tuple[str, str]] | None,
) -> dict[str, Any]:
    payload = build_schema_audit_payload(engine=engine, metadata=metadata)
    if metadata is None:
        from app.models import Base

        metadata = Base.metadata
    payload = select_additive_migration_scope(payload, metadata=metadata, only_columns=only_columns)
    if only_columns:
        payload["ready"] = (
            not payload["missingTables"]
            and not payload["missingColumns"]
            and not payload["manualReviewColumns"]
            and not payload.get("unknownRequestedColumns")
        )
    return payload


def build_scoped_additive_migration_payload(
    *,
    engine: Engine | None = None,
    metadata: MetaData | None = None,
    only_columns: set[tuple[str, str]] | None,
) -> dict[str, Any]:
    payload = build_scoped_schema_audit_payload(engine=engine, metadata=metadata, only_columns=only_columns)
    payload["statementCount"] = len(payload["additiveStatements"])
    payload["readyAfterMigration"] = payload["executable"]
    return payload


def select_additive_migration_scope(
    payload: dict[str, Any],
    *,
    metadata: MetaData,
    only_columns: set[tuple[str, str]] | None,
) -> dict[str, Any]:
    if not only_columns:
        payload["scope"] = "all"
        payload["onlyColumns"] = []
        return payload

    expected_columns = {
        (table_name, column.name)
        for table_name, table in metadata.tables.items()
        for column in table.columns
    }
    missing_by_key = {
        (item["table"], item["column"]): item
        for item in payload["missingColumns"]
    }
    manual_by_key = {
        (item["table"], item["column"]): item
        for item in payload["manualReviewColumns"]
    }
    missing_table_names = set(payload["missingTables"])
    selected_missing_tables = [
        table_name
        for table_name in sorted({table for table, _column in only_columns})
        if table_name in missing_table_names
    ]
    selected_missing = [
        missing_by_key[key]
        for key in sorted(only_columns)
        if key in missing_by_key
    ]
    selected_manual = [
        manual_by_key[key]
        for key in sorted(only_columns)
        if key in manual_by_key
    ]
    unknown_requested = [
        {"table": table, "column": column, "reason": "column is not part of current SQLAlchemy metadata"}
        for table, column in sorted(only_columns)
        if (table, column) not in expected_columns
    ]
    already_present = [
        {"table": table, "column": column}
        for table, column in sorted(only_columns)
        if table not in missing_table_names
        and (table, column) in expected_columns
        and (table, column) not in missing_by_key
    ]

    payload["scope"] = "selected"
    payload["onlyColumns"] = [f"{table}.{column}" for table, column in sorted(only_columns)]
    payload["allMissingTableCount"] = len(payload["missingTables"])
    payload["missingTables"] = selected_missing_tables
    payload["missingTableCount"] = len(selected_missing_tables)
    payload["allMissingColumnCount"] = len(payload["missingColumns"])
    payload["missingColumns"] = selected_missing
    payload["missingColumnCount"] = len(selected_missing)
    payload["manualReviewColumns"] = selected_manual
    payload["manualReviewColumnCount"] = len(selected_manual)
    payload["allColumnWarningCount"] = len(payload.get("columnWarnings", []))
    payload["columnWarnings"] = [
        item
        for item in payload.get("columnWarnings", [])
        if (item["table"], item["column"]) in only_columns
    ]
    payload["columnWarningCount"] = len(payload["columnWarnings"])
    payload["allMissingIndexCount"] = len(payload["missingIndexes"])
    payload["unknownRequestedColumns"] = unknown_requested
    payload["unknownRequestedColumnCount"] = len(unknown_requested)
    payload["alreadyPresentColumns"] = already_present
    payload["alreadyPresentColumnCount"] = len(already_present)
    payload["missingIndexes"] = [
        item
        for item in payload["missingIndexes"]
        if any((item["table"], column) in only_columns for column in item["columns"])
    ]
    payload["missingIndexCount"] = len(payload["missingIndexes"])
    payload["additiveStatements"] = [item["sql"] for item in selected_missing if item["autoMigratable"]]
    payload["additiveStatementCount"] = len(payload["additiveStatements"])
    payload["executable"] = not selected_missing_tables and not selected_manual and not unknown_requested
    return payload


def assert_additive_sql(sql: str) -> None:
    normalized = " ".join(sql.strip().rstrip(";").split())
    upper = normalized.upper()
    if not upper.startswith("ALTER TABLE ") or " ADD COLUMN " not in upper:
        raise RuntimeError(f"拒绝执行非 ADD COLUMN 语句：{sql}")
    if DESTRUCTIVE_SQL_PATTERN.search(normalized):
        raise RuntimeError(f"拒绝执行包含破坏性关键字的 SQL：{sql}")


def find_latest_nonempty_backup(private_dir: Path, environment: str) -> Path | None:
    backup_root = private_dir / "backups" / environment
    if not backup_root.exists():
        return None
    candidates = [
        path
        for path in backup_root.iterdir()
        if path.is_file() and path.stat().st_size > 0 and (path.name.endswith(".sql") or path.name.endswith(".sql.gz"))
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def require_recent_nonempty_backup(
    private_dir: Path,
    environment: str,
    *,
    max_age_seconds: int,
    now: datetime | None = None,
) -> Path:
    backup = find_latest_nonempty_backup(private_dir, environment)
    if backup is None:
        raise RuntimeError("production migrate-additive --yes 需要先完成非空数据库备份。")
    current_ts = (now or datetime.now(UTC)).timestamp()
    age_seconds = max(0, int(current_ts - backup.stat().st_mtime))
    if age_seconds > max_age_seconds:
        max_age_minutes = max(1, max_age_seconds // 60)
        age_minutes = max(1, age_seconds // 60)
        raise RuntimeError(
            f"production migrate-additive --yes 需要最近 {max_age_minutes} 分钟内的非空数据库备份；"
            f"最新备份已约 {age_minutes} 分钟。"
        )
    return backup


def _index_column_sets(indexes: list[dict[str, Any]]) -> set[tuple[str, ...]]:
    result: set[tuple[str, ...]] = set()
    for index in indexes:
        columns = index.get("column_names") or []
        if columns:
            result.add(tuple(str(column) for column in columns))
    return result


def _missing_column_payload(table: Table, column: Column[Any], dialect: Dialect) -> dict[str, Any]:
    default_sql = _default_sql(column, dialect)
    auto_migratable, reason = _can_auto_add_column(column, default_sql)
    return {
        "table": table.name,
        "column": column.name,
        "expectedType": _column_type_sql(column, dialect),
        "nullable": bool(column.nullable),
        "default": _default_payload(column),
        "autoMigratable": auto_migratable,
        "reason": reason,
        "sql": _add_column_sql(table, column, dialect, default_sql) if auto_migratable else None,
    }


def _can_auto_add_column(column: Column[Any], default_sql: str | None) -> tuple[bool, str]:
    if column.primary_key:
        return False, "primary key columns require manual migration"
    if column.unique:
        return False, "unique columns require manual migration"
    if column.nullable:
        return True, "nullable column can be added without touching existing rows"
    if default_sql is not None:
        return True, "non-null column has a safe default"
    return False, "non-null column has no safe default"


def _column_warning_payloads(
    table: Table,
    column: Column[Any],
    actual_column: Mapping[str, Any],
    dialect: Dialect,
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    expected_type = _column_type_sql(column, dialect)
    actual_type = _actual_column_type_sql(actual_column, dialect)
    if actual_type and _normalize_column_type_sql(actual_type) != _normalize_column_type_sql(expected_type):
        warnings.append(
            {
                "table": table.name,
                "column": column.name,
                "kind": "type",
                "expectedType": expected_type,
                "actualType": actual_type,
                "reason": "existing column type differs from SQLAlchemy metadata",
            }
        )

    actual_nullable = actual_column.get("nullable")
    if actual_nullable is not None and bool(actual_nullable) != bool(column.nullable):
        warnings.append(
            {
                "table": table.name,
                "column": column.name,
                "kind": "nullable",
                "expectedNullable": bool(column.nullable),
                "actualNullable": bool(actual_nullable),
                "reason": "existing column nullable flag differs from SQLAlchemy metadata",
            }
        )

    expected_default = _default_sql(column, dialect)
    if expected_default is not None:
        actual_default = _actual_default_sql(actual_column)
        if _normalize_default_sql(actual_default) != _normalize_default_sql(expected_default):
            warnings.append(
                {
                    "table": table.name,
                    "column": column.name,
                    "kind": "default",
                    "expectedDefault": expected_default,
                    "actualDefault": actual_default,
                    "reason": "existing column default differs from SQLAlchemy metadata",
                }
            )
    return warnings


def _missing_single_column_indexes(
    table: Table,
    *,
    actual_columns: set[str],
    actual_index_columns: set[tuple[str, ...]],
    dialect: Dialect,
) -> list[dict[str, Any]]:
    missing: list[dict[str, Any]] = []
    for column in table.columns:
        if not column.index or column.name not in actual_columns:
            continue
        columns = (column.name,)
        if columns in actual_index_columns:
            continue
        index_name = f"ix_{table.name}_{column.name}"
        missing.append(
            {
                "table": table.name,
                "index": index_name,
                "columns": [column.name],
                "sql": f"CREATE INDEX {_quote_identifier(index_name, dialect)} ON "
                f"{_quote_identifier(table.name, dialect)} ({_quote_identifier(column.name, dialect)});",
            }
        )
    return missing


def _add_column_sql(table: Table, column: Column[Any], dialect: Dialect, default_sql: str | None) -> str:
    parts = [
        "ALTER TABLE",
        _quote_identifier(table.name, dialect),
        "ADD COLUMN",
        _quote_identifier(column.name, dialect),
        _column_type_sql(column, dialect),
    ]
    parts.append("NULL" if column.nullable else "NOT NULL")
    if default_sql is not None:
        parts.extend(["DEFAULT", default_sql])
    return " ".join(parts) + ";"


def _column_type_sql(column: Column[Any], dialect: Dialect) -> str:
    return column.type.compile(dialect=dialect).upper()


def _actual_column_type_sql(actual_column: Mapping[str, Any], dialect: Dialect) -> str | None:
    column_type = actual_column.get("type")
    if column_type is None:
        return None
    if hasattr(column_type, "compile"):
        return str(column_type.compile(dialect=dialect)).upper()
    return str(column_type).upper()


def _normalize_column_type_sql(value: str) -> str:
    normalized = " ".join(value.strip().upper().split())
    normalized = re.sub(r"\bINT\(\d+\)", "INTEGER", normalized)
    normalized = re.sub(r"\bINTEGER\(\d+\)", "INTEGER", normalized)
    normalized = re.sub(r"\bTINYINT\(1\)", "BOOLEAN", normalized)
    if normalized == "INT":
        return "INTEGER"
    if normalized in {"BOOL", "BOOLEAN"}:
        return "BOOLEAN"
    return normalized


def _actual_default_sql(actual_column: Mapping[str, Any]) -> str | None:
    value = actual_column.get("default")
    if value is None:
        return None
    return str(value)


def _normalize_default_sql(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(str(value).strip().split())
    if normalized.upper().startswith("DEFAULT "):
        normalized = normalized[8:].strip()
    while normalized.startswith("(") and normalized.endswith(")") and len(normalized) >= 2:
        normalized = normalized[1:-1].strip()
    if (
        len(normalized) >= 2
        and normalized[0] == normalized[-1]
        and normalized[0] in {"'", '"'}
    ):
        normalized = normalized[1:-1]
    upper = normalized.upper()
    if upper in {"NOW()", "CURRENT_TIMESTAMP()"}:
        return "CURRENT_TIMESTAMP"
    if upper in {"TRUE", "FALSE"}:
        return "1" if upper == "TRUE" else "0"
    return normalized


def _quote_identifier(value: str, dialect: Dialect) -> str:
    return dialect.identifier_preparer.quote_identifier(value)


def _default_payload(column: Column[Any]) -> Any:
    if column.default is not None and column.default.is_scalar:
        return column.default.arg
    if column.server_default is not None:
        return str(column.server_default.arg)
    return None


def _default_sql(column: Column[Any], dialect: Dialect) -> str | None:
    if column.default is not None and column.default.is_scalar:
        return _literal_value(column.default.arg, column, dialect)
    if column.server_default is not None:
        arg = column.server_default.arg
        if isinstance(arg, str):
            return arg
        if hasattr(arg, "compile"):
            compiled = str(arg.compile(dialect=dialect, compile_kwargs={"literal_binds": True}))
            if compiled.lower() in {"now()", "current_timestamp()"}:
                return "CURRENT_TIMESTAMP"
            return compiled
        return str(arg)
    return None


def _literal_value(value: Any, column: Column[Any], dialect: Dialect) -> str:
    processor = column.type.literal_processor(dialect)
    if processor is not None:
        return processor(value)
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    if value is True:
        return "1"
    if value is False:
        return "0"
    return str(value)
