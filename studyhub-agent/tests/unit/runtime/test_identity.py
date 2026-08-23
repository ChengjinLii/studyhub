import pytest

from studyhub_agent.runtime.identity import AgentIdentity

SECRET = "fixture-identity-secret-at-least-16"


def test_raw_user_id_is_pseudonymized_stably() -> None:
    first = AgentIdentity.from_raw_user_id(294, session_id="session-0001", environment="prod", identity_secret=SECRET)
    second = AgentIdentity.from_raw_user_id(
        "294",
        session_id="session-0002",
        environment="prod",
        identity_secret=SECRET,
    )

    assert first.principal_id == second.principal_id
    assert "294" not in first.principal_id
    assert first.principal_id.startswith("studyhub:user:")


def test_user_and_environment_namespaces_are_isolated() -> None:
    user_a = AgentIdentity.from_raw_user_id("a", session_id="session-a1", environment="prod", identity_secret=SECRET)
    user_b = AgentIdentity.from_raw_user_id("b", session_id="session-b1", environment="prod", identity_secret=SECRET)
    train = AgentIdentity.from_raw_user_id("a", session_id="session-a2", environment="train", identity_secret=SECRET)
    evaluate = AgentIdentity.from_raw_user_id("a", session_id="session-a3", environment="eval", identity_secret=SECRET)

    assert user_a.personal_memory_namespace() != user_b.personal_memory_namespace()
    assert train.personal_memory_namespace(task_id="task-a", seed=7) == "train:task-a:7"
    assert evaluate.personal_memory_namespace(case_id="case-a", seed=7) == "eval:case-a:7"
    assert train.personal_memory_namespace(task_id="task-a", seed=7) != user_a.personal_memory_namespace()


def test_identity_rejects_raw_or_weak_inputs() -> None:
    with pytest.raises(ValueError):
        AgentIdentity(principal_id="294", session_id="session-0001", environment="prod")
    with pytest.raises(ValueError):
        AgentIdentity.from_raw_user_id(294, session_id="short", environment="prod", identity_secret=SECRET)
    with pytest.raises(ValueError):
        AgentIdentity.from_raw_user_id(294, session_id="session-0001", environment="prod", identity_secret="short")
