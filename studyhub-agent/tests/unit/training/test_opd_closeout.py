import pytest

from scripts.train.recover_opd_closeout import exported_rewards


def fixture():
    files = [{"task_id": f"task-{i}-{j}", "policy_version_directory": str(i)} for i in range(300) for j in range(8)]
    rewards = [{"task_id": r["task_id"], "reward": {"status": "SCORED"}} for r in files for _ in range(2)]
    return rewards, files


def test_reconcile_only_runtime_excluded_group():
    rows, files = fixture()
    rows += [{"task_id": "infra", "reward": {"status": status}} for status in ("SCORED", "INFRA_EXCLUDED")]
    accepted, excluded = exported_rewards(rows, files)
    assert len(accepted) == 4800 and len(excluded) == 2


def test_cannot_hide_infra_in_consumed_task():
    rows, files = fixture()
    rows[0]["reward"]["status"] = "INFRA_EXCLUDED"
    with pytest.raises(RuntimeError, match="appears in training"):
        exported_rewards(rows, files)


def test_cannot_drop_unexplained_successful_groups():
    rows, files = fixture()
    rows += [{"task_id": "unexplained", "reward": {"status": "SCORED"}}] * 2
    with pytest.raises(RuntimeError, match="unexplained"):
        exported_rewards(rows, files)


def test_missing_step_or_reward_fails_closed():
    rows, files = fixture()
    with pytest.raises(RuntimeError, match="eight prompt groups"):
        exported_rewards(rows, files[:-1])
    with pytest.raises(RuntimeError, match="multiplicity"):
        exported_rewards(rows[:-1], files)
