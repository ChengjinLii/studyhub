from studyhub_agent.guardrails.privacy import sanitize_output


def test_sanitize_removes_forbidden_keys_and_redacts_emails() -> None:
    value = {
        "title": "联系 a.b@example.com",
        "email": "x@y.com",
        "nested": [{"user_id": 3, "ok": "yes"}],
    }
    assert sanitize_output(value) == {
        "title": "联系 [redacted-email]",
        "nested": [{"ok": "yes"}],
    }


def test_sanitize_returns_new_objects() -> None:
    original = {"a": ["b"]}
    result = sanitize_output(original)
    assert result == original and result is not original and result["a"] is not original["a"]
