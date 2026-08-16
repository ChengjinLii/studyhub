from __future__ import annotations

import argparse
from collections import Counter
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, MetaData, Table, inspect, select

from app.core.config import get_settings
from app.core.db import get_engine


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _group(rows: list[Any], *fields: str) -> dict[str, int]:
    counts = Counter("/".join(str(row.get(field) or "UNKNOWN") for field in fields) for row in rows)
    return dict(sorted(counts.items()))


def _rows(engine: Engine, table_name: str, columns: tuple[str, ...]) -> list[Any]:
    table = Table(table_name, MetaData(), autoload_with=engine)
    selected = [table.c[name] for name in columns]
    with engine.connect() as connection:
        return list(connection.execute(select(*selected)).mappings())


def build_finance_reconciliation(engine: Engine, *, now: datetime | None = None) -> dict[str, Any]:
    checked_at = now or datetime.now(UTC)
    stale_before = checked_at - timedelta(hours=1)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    issues: list[dict[str, Any]] = []
    report: dict[str, Any] = {
        "checkedAt": checked_at.isoformat(),
        "outbox": {"statusByType": {}, "stale": 0},
        "payouts": {"status": {}, "stale": 0, "inconsistentSettlements": 0},
        "refunds": {"status": {}, "stale": 0},
        "issues": issues,
    }

    if "finance_instructions" in tables:
        instructions = _rows(
            engine,
            "finance_instructions",
            ("instruction_type", "status", "created_at", "updated_at"),
        )
        stale = [
            item
            for item in instructions
            if item["status"] in {"PENDING", "PROCESSING"}
            and (_as_utc(item["updated_at"]) or _as_utc(item["created_at"]) or checked_at) <= stale_before
        ]
        report["outbox"] = {
            "statusByType": _group(instructions, "instruction_type", "status"),
            "stale": len(stale),
        }
        failed = sum(item["status"] == "FAILED" for item in instructions)
        if stale:
            issues.append({"severity": "warning", "code": "STALE_FINANCE_INSTRUCTIONS", "count": len(stale)})
        if failed:
            issues.append({"severity": "error", "code": "FAILED_FINANCE_INSTRUCTIONS", "count": failed})

    if "payout_transfers" in tables:
        transfers = _rows(engine, "payout_transfers", ("id", "status", "created_at", "updated_at"))
        stale = [
            item
            for item in transfers
            if item["status"] in {"PENDING", "SUBMITTED"}
            and (_as_utc(item["updated_at"]) or _as_utc(item["created_at"]) or checked_at) <= stale_before
        ]
        report["payouts"]["status"] = _group(transfers, "status")
        report["payouts"]["stale"] = len(stale)
        if stale:
            issues.append({"severity": "warning", "code": "STALE_PAYOUT_TRANSFERS", "count": len(stale)})

    if {"payout_transfers", "settlements"}.issubset(tables):
        settlement_columns = {str(item["name"]) for item in inspector.get_columns("settlements")}
        if {"payout_transfer_id", "status"}.issubset(settlement_columns):
            transfers_by_id = {
                int(item["id"]): item for item in _rows(engine, "payout_transfers", ("id", "status")) if item["id"] is not None
            }
            settlements = _rows(engine, "settlements", ("payout_transfer_id", "status"))
            inconsistent = 0
            for settlement in settlements:
                if settlement["payout_transfer_id"] is None:
                    continue
                transfer = transfers_by_id.get(int(settlement["payout_transfer_id"]))
                if transfer is None:
                    inconsistent += 1
                elif transfer["status"] == "SUCCESS" and settlement["status"] != "PAID":
                    inconsistent += 1
                elif transfer["status"] == "FAILED" and settlement["status"] == "PENDING":
                    inconsistent += 1
            report["payouts"]["inconsistentSettlements"] = inconsistent
            if inconsistent:
                issues.append({"severity": "error", "code": "PAYOUT_SETTLEMENT_MISMATCH", "count": inconsistent})

    contribution_columns = (
        {str(item["name"]) for item in inspector.get_columns("material_request_contributions")}
        if "material_request_contributions" in tables
        else set()
    )
    required = {"status", "refund_status", "created_at", "updated_at"}
    if required.issubset(contribution_columns):
        contributions = _rows(
            engine,
            "material_request_contributions",
            ("status", "refund_status", "created_at", "updated_at"),
        )
        refund_rows = [
            item
            for item in contributions
            if item["status"] == "REFUNDING" or item["refund_status"] in {"PENDING", "FAILED"}
        ]
        stale = [
            item
            for item in refund_rows
            if (_as_utc(item["updated_at"]) or _as_utc(item["created_at"]) or checked_at) <= stale_before
        ]
        report["refunds"] = {"status": _group(refund_rows, "status", "refund_status"), "stale": len(stale)}
        if stale:
            issues.append({"severity": "warning", "code": "STALE_REQUEST_REFUNDS", "count": len(stale)})

    report["ok"] = not any(item["severity"] == "error" for item in issues)
    return report


def write_report(report: dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = str(report["checkedAt"]).replace(":", "").replace("+", "-")
    destination = output_dir / f"finance-reconciliation-{stamp}.json"
    temporary = output_dir / f".{destination.name}.{os.getpid()}.tmp"
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    temporary.write_text(payload, encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, destination)
    latest = output_dir / "latest.json"
    latest_tmp = output_dir / f".latest.{os.getpid()}.tmp"
    latest_tmp.write_text(payload, encoding="utf-8")
    os.chmod(latest_tmp, 0o600)
    os.replace(latest_tmp, latest)
    cutoff = datetime.now(UTC) - timedelta(days=90)
    for candidate in output_dir.glob("finance-reconciliation-*.json"):
        if datetime.fromtimestamp(candidate.stat().st_mtime, UTC) < cutoff:
            candidate.unlink()
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a privacy-safe StudyHub finance reconciliation report")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    settings = get_settings()
    output_dir = args.output_dir or settings.private_dir / "reports" / "finance"
    report = build_finance_reconciliation(get_engine())
    destination = write_report(report, output_dir)
    print(json.dumps({"ok": report["ok"], "issues": report["issues"], "report": str(destination)}, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
