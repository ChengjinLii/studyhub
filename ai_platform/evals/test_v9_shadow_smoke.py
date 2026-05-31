from __future__ import annotations

from pathlib import Path
import sys


AI_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AI_PLATFORM_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_platform.scripts.v9_shadow_smoke import run_v9_shadow_smoke


def test_v9_shadow_smoke_passes_with_mock_providers() -> None:
    report = run_v9_shadow_smoke()

    assert report["suite"] == "studycopilot-v9-admin-shadow-smoke"
    assert report["mode"] == "mock"
    assert report["passed"] is True
    assert report["productionIsolation"] == {
        "productionDatabaseWrites": False,
        "frontendEntryEnabled": False,
        "publicTrafficEnabled": False,
    }
    assert report["rolloutGate"]["allowed"] is True
    assert report["studyCopilot"]["toolUseRecords"]
