from pathlib import Path


PROJECT = Path(__file__).resolve().parents[3]


def test_sft_launcher_installs_required_areal_runtime_shim() -> None:
    script = (PROJECT / "scripts/train/run_controlled_sft.sh").read_text(encoding="utf-8")

    assert 'RUNTIME_SHIM="${PROJECT_ROOT}/training/runtime_shims"' in script
    assert "export STUDYHUB_AREAL_CHAT_TEMPLATE_METADATA_BRIDGE=1" in script
    assert script.count('PYTHONPATH="${RUNTIME_SHIM}:${PROJECT_ROOT}') == 2
