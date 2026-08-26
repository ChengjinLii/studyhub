from __future__ import annotations

from scripts.train.redact_trial_secret import REDACTION, candidate_files, redact


def test_redactor_only_changes_text_artifacts_for_the_selected_trial(tmp_path) -> None:
    secret = b"a-secure-ephemeral-key-that-is-long-enough"
    selected = tmp_path / "logs" / "trial-a" / "config.yaml"
    selected.parent.mkdir(parents=True)
    selected.write_bytes(b"admin_api_key: " + secret + b"\n")
    unrelated = tmp_path / "logs" / "trial-b" / "config.yaml"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_bytes(secret)
    binary = tmp_path / "logs" / "trial-a" / "weights.bin"
    binary.write_bytes(secret)

    assert candidate_files(tmp_path, "trial-a") == [selected]
    files_changed, replacements, paths = redact(tmp_path, "trial-a", secret)

    assert files_changed == 1
    assert replacements == 1
    assert paths == ["logs/trial-a/config.yaml"]
    assert REDACTION in selected.read_bytes()
    assert secret not in selected.read_bytes()
    assert unrelated.read_bytes() == secret
    assert binary.read_bytes() == secret
