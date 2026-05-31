from __future__ import annotations

from pathlib import Path
import sys


AI_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AI_PLATFORM_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_platform.scripts.api_smoke_demo import run_api_smoke


def test_api_smoke_demo_does_not_call_api_by_default(monkeypatch) -> None:
    monkeypatch.setenv("STUDYHUB_LLM_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("STUDYHUB_LLM_API_KEY", "test-key")
    monkeypatch.setenv("STUDYHUB_LLM_MODEL", "test-model")
    monkeypatch.setenv("STUDYHUB_EMBEDDING_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("STUDYHUB_EMBEDDING_API_KEY", "test-key")
    monkeypatch.setenv("STUDYHUB_EMBEDDING_MODEL", "embedding-model")

    result = run_api_smoke(run_api=False)

    assert result["chatProviderConfigured"] is True
    assert result["embeddingProviderConfigured"] is True
    assert result["executed"] is False
