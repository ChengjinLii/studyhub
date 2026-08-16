from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.ops.backup_automation import BackupArtifact, _retained_names, require_isolated_restore_target


def _artifact(value: str) -> BackupArtifact:
    created_at = datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    return BackupArtifact(name=f"studyhub-production-{value}.sql.gz.age", created_at=created_at)


def test_retention_is_union_of_daily_weekly_and_monthly_generations() -> None:
    artifacts = [
        _artifact("20260816T010000Z"),
        _artifact("20260815T010000Z"),
        _artifact("20260814T010000Z"),
        _artifact("20260801T010000Z"),
        _artifact("20260701T010000Z"),
        _artifact("20260601T010000Z"),
    ]

    retained = _retained_names(artifacts, daily=2, weekly=2, monthly=3)

    assert artifacts[0].name in retained
    assert artifacts[1].name in retained
    assert artifacts[3].name in retained
    assert artifacts[4].name in retained
    assert artifacts[5].name in retained


def test_restore_drill_rejects_production_database() -> None:
    production = "mysql+pymysql://user:secret@prod.example:3306/study_hub"
    with pytest.raises(RuntimeError, match="生产数据库相同"):
        require_isolated_restore_target(production, production)


def test_restore_drill_requires_explicit_drill_database_name() -> None:
    production = "mysql+pymysql://user:secret@prod.example:3306/study_hub"
    with pytest.raises(RuntimeError, match="必须包含 drill"):
        require_isolated_restore_target(production, "mysql+pymysql://user:secret@127.0.0.1:3306/study_hub_preview")


def test_restore_drill_accepts_isolated_mysql_database() -> None:
    production = "mysql+pymysql://user:secret@prod.example:3306/study_hub"
    target = require_isolated_restore_target(production, "mysql+pymysql://user:secret@127.0.0.1:3306/studyhub_restore_drill")
    assert target.database == "studyhub_restore_drill"
