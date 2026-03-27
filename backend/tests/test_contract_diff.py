from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import clear_dependency_caches, get_auth_service
from app.contracts.executor import SyncRequestExecutor
from app.contracts.loader import load_contract_samples
from app.contracts.runner import ContractSuiteRunner
from app.core.config import get_settings
from app.core.db import reset_database_runtime
from app.main import create_app
from tests.support import prepare_contract_diff_state


def test_contract_diff_snapshot_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "contract-diff.sqlite3"
    monkeypatch.setenv("STUDYHUB_ENVIRONMENT", "local")
    monkeypatch.setenv("STUDYHUB_DATABASE_URL", f"sqlite+pysqlite:///{db_path}")
    monkeypatch.setenv("STUDYHUB_JWT_SECRET", "studyhub-fastapi-test-secret-1234567890abcdefghijkl")
    monkeypatch.setenv("STUDYHUB_CONTRACT_REPORT_DIR", str(tmp_path))
    monkeypatch.setenv("STUDYHUB_MATERIAL_ASSET_DIR", str(tmp_path / "materials"))
    monkeypatch.setenv("STUDYHUB_PAYOUT_QR_ASSET_DIR", str(tmp_path / "payout-qr"))
    monkeypatch.setenv("STUDYHUB_MAIL_OUTBOX_DIR", str(tmp_path / "outbox" / "mail"))
    monkeypatch.setenv("STUDYHUB_BUILD_GIT_SHA", "local-dev")
    monkeypatch.setenv("STUDYHUB_LOCAL_DEV_BOOTSTRAP_USER", "false")

    get_settings.cache_clear()
    clear_dependency_caches()
    reset_database_runtime()

    app = create_app()
    sample_dir = get_settings().resolved_contract_sample_dir
    samples = load_contract_samples(sample_dir)

    with TestClient(app) as client:
        prepare_contract_diff_state(get_auth_service())
        executor = SyncRequestExecutor(client)
        summary = ContractSuiteRunner().run(
            samples=samples,
            candidate_executor=executor,
            output_dir=tmp_path,
        )

    assert summary["failed"] == 0
    assert summary["dimension_summary"]["cookie"]["total"] >= 1
    assert summary["dimension_summary"]["text/plain"]["total"] >= 2
    assert summary["dimension_summary"]["multipart"]["total"] >= 1
    assert summary["dimension_summary"]["binary/download"]["total"] >= 2
    assert (tmp_path / "report.json").exists()
    assert (tmp_path / "report.md").exists()

    clear_dependency_caches()
    reset_database_runtime()
    get_settings.cache_clear()
