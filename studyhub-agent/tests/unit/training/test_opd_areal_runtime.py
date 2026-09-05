import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import torch
import torch.nn.functional as F

from training.opd.areal_runtime import (
    _chunked_selected_log_probs,
    _chunked_top_k_log_probs,
    _decode_sparse_token_field,
    _encode_sparse_token_fields,
    _flatten_sequence_lengths,
    _install_colocated_proxy_start_bridge,
    _prepare_opd_microbatches,
    _split_sparse_outputs,
    aggregate_opd_diagnostics,
    assistant_prediction_mask,
    compute_opd_diagnostics,
    install_areal_opd_bridge,
    prediction_turn_ids,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("actor_offload,rollout_saver", [(True, False), (False, True), (False, False)])
def test_colocated_opd_rejects_inactive_memory_release(actor_offload: bool, rollout_saver: bool) -> None:
    from scripts.train.preflight_qwen35_4b_opd import validate_rollout_memory_config

    config = SimpleNamespace(
        rollout=SimpleNamespace(scheduling_strategy=SimpleNamespace(type="colocation", target="actor")),
        enable_offload=actor_offload,
        sglang=SimpleNamespace(enable_memory_saver=rollout_saver),
    )
    with pytest.raises(RuntimeError, match="Colocated OPD requires"):
        validate_rollout_memory_config(config)


def test_opd_launcher_separates_code_and_artifact_roots() -> None:
    launcher = (PROJECT_ROOT / "scripts/train/run_qwen35_4b_opd.sh").read_text()
    config = (PROJECT_ROOT / "configs/train/qwen35-4b-strict-opd.yaml").read_text()

    assert 'ARTIFACT_ROOT="${STUDYHUB_OPD_ARTIFACT_ROOT:-${PROJECT_ROOT}}"' in launcher
    assert 'VENV_DIR="${STUDYHUB_TRAIN_VENV:-${ARTIFACT_ROOT}/.venv-train}"' in launcher
    assert 'DATA_MANIFEST="${ARTIFACT_ROOT}/datasets/processed/' in launcher
    assert 'CHECKPOINT_ROOT="${RUN_ROOT}/checkpoints/' in launcher
    assert 'RUN_ROOT="${ARTIFACT_ROOT}/artifacts/areal/opd-attempts/${ATTEMPT_ID}"' in launcher
    assert '"cluster.fileroot=${RUN_ROOT}"' in launcher
    assert 'STAGE_MARKER="${STAGE_ROOT}/QWEN35_4B_OPD_LR1E6_PASS.json"' in launcher
    assert '--reward-root "${REWARD_ROOT}/reward-v3.jsonl"' in launcher
    assert "--expected-group-size 2" in launcher
    assert "BATCH_SIZE=2; CHECKPOINT_EVERY=1" in launcher
    assert "${PROJECT_ROOT}/artifacts/areal" not in launcher
    assert "libcudart.so.12" in launcher
    assert "STUDYHUB_CUDA_RUNTIME_LIBRARY_PATH" in launcher
    assert "prepare_sglang_model_overlay.py" in launcher
    assert "SGLANG_OVERLAY_AUDIT" in launcher
    assert "qwen35-4b-opd-sglang-lora" in config
    assert "model_path: ${actor.path}" not in config
    assert "mem_fraction_static: 0.65" in config
    assert config.count("LD_LIBRARY_PATH: ${oc.env:STUDYHUB_CUDA_RUNTIME_LIBRARY_PATH}") >= 5
    assert 'REWARD_ROOT="${ARTIFACT_ROOT}/artifacts/areal/strict-opd/rewards/${TRIAL}/${ATTEMPT_ID}"' in launcher

    probe = (PROJECT_ROOT / "scripts/train/run_opd_policy_probe.py").read_text()
    assert 'parser.add_argument("--artifact-root"' in probe
    assert 'artifact_root / ".vendor/hermes-agent"' in probe
    assert "model_overlay = artifact_root /" in probe


def test_lora_only_opd_rejects_base_weights_without_cpu_backup() -> None:
    from scripts.train.preflight_qwen35_4b_opd import validate_rollout_memory_config

    config = SimpleNamespace(
        rollout=SimpleNamespace(scheduling_strategy=SimpleNamespace(type="colocation", target="actor"), use_lora=True),
        enable_offload=True,
        sglang=SimpleNamespace(enable_memory_saver=True, enable_weights_cpu_backup=False),
    )
    with pytest.raises(RuntimeError, match="weight CPU backup"):
        validate_rollout_memory_config(config)
    config.sglang.enable_weights_cpu_backup = True
    validate_rollout_memory_config(config)


def test_opd_disables_thinking_without_changing_other_workflows() -> None:
    from training.rl.hermes_workflow_v3 import StudyHubHermesWorkflowV3

    workflow = object.__new__(StudyHubHermesWorkflowV3)
    workflow.temperature, workflow.top_p = 0.7, 1.0
    workflow.enable_thinking = None
    assert workflow._request_overrides() == {"temperature": 0.7, "top_p": 1.0}
    workflow.enable_thinking = False
    overrides = workflow._request_overrides()
    assert overrides["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False
    assert overrides["metadata"] == {"studyhub_chat_template": "disable_thinking_v1"}
    assert '"enable_thinking": False' in (PROJECT_ROOT / "training/opd/driver.py").read_text()


def test_prediction_mask_does_not_cross_trajectory_boundaries() -> None:
    mask = torch.tensor([[0, 0, 1, 1], [0, 1, 0, 1]], dtype=torch.float32)

    shifted = assistant_prediction_mask(mask)

    assert torch.equal(
        shifted,
        torch.tensor([[0, 1, 1, 0], [1, 0, 1, 0]], dtype=torch.float32),
    )


def test_opd_signal_does_not_require_positive_mean_logprob_gap() -> None:
    from scripts.train.record_qwen35_4b_opd_stage import distillation_signal_failures

    student = torch.log(torch.tensor([[[0.8, 0.2]]]))
    teacher = torch.log(torch.tensor([[[0.2, 0.8]]]))
    ids = torch.tensor([[[0, 1]]])
    stats = compute_opd_diagnostics(
        student_ids=ids,
        student_log_probs=student,
        teacher_on_student=teacher,
        teacher_ids=ids,
        teacher_log_probs=teacher,
        response_mask=torch.ones(1, 1),
    )
    assert stats["opd_teacher_logprob_advantage"].abs() < 1e-6
    assert stats["opd_teacher_logprob_gap_abs"] > 1
    assert not distillation_signal_failures([1], [1.3], [10], [0.1])
    assert distillation_signal_failures([1], [0], [10], [0.1]) == ["teacher_signal_indistinguishable_from_zero"]


def test_prediction_turn_ids_follow_next_token_alignment() -> None:
    turn_ids = torch.tensor([[-1, 0, 0, 1, 1]])

    assert torch.equal(prediction_turn_ids(turn_ids), torch.tensor([[0, 0, 1, 1, -1]]))


def test_opd_sequence_lengths_flatten_all_interactions_without_padding() -> None:
    trajectories = [
        {"attention_mask": torch.tensor([[1, 1, 1, 1, 1], [1, 1, 1, 1, 0], [1, 1, 1, 0, 0]])},
        {"attention_mask": torch.tensor([[1, 1, 1, 1, 1, 1, 1], [1, 1, 1, 1, 1, 1, 0]])},
    ]

    assert _flatten_sequence_lengths(trajectories) == [5, 4, 3, 7, 6]


def test_opd_sparse_outputs_split_interactions_and_trim_sequence_axis() -> None:
    padded = torch.arange(5 * 7 * 2).reshape(5, 7, 2)
    meta = SimpleNamespace(traj_group_sizes=[3, 2], traj_seqlens=[5, 7])

    split = _split_sparse_outputs(padded, meta)

    assert [tuple(value.shape) for value in split] == [(3, 5, 2), (2, 7, 2)]
    assert torch.equal(split[0], padded[:3, :5])
    assert torch.equal(split[1], padded[3:, :7])


def test_opd_sparse_outputs_reject_interaction_count_mismatch() -> None:
    meta = SimpleNamespace(traj_group_sizes=[2, 2], traj_seqlens=[4, 4])

    with pytest.raises(RuntimeError, match="interaction count"):
        _split_sparse_outputs(torch.zeros((3, 4, 2)), meta)


def test_opd_sparse_wings_follow_areal_token_packing() -> None:
    pytest.importorskip("areal")
    from areal.utils.data import pack_tensor_dict

    attention_mask = torch.tensor([[1, 1, 0], [1, 1, 1]])
    sparse = torch.arange(2 * 3 * 3).reshape(2, 3, 3)
    encoded = _encode_sparse_token_fields(
        {
            "attention_mask": attention_mask,
            "input_ids": torch.arange(6).reshape(2, 3),
            "opd_top_k_ids": sparse,
        }
    )

    assert "opd_top_k_ids" not in encoded
    assert all(tuple(encoded[f"opd_top_k_ids__wing_{wing:03d}"].shape) == (2, 3) for wing in range(3))
    packed = pack_tensor_dict(encoded)
    restored = _decode_sparse_token_field(
        packed,
        "opd_top_k_ids",
        expected_wings=3,
    )
    expected = torch.cat([sparse[0, :2], sparse[1, :3]], dim=0)

    assert tuple(restored.shape) == (5, 3)
    assert torch.equal(restored, expected)


def test_opd_sparse_wing_decode_fails_closed_on_missing_wing() -> None:
    packed = {
        "opd_top_k_ids__wing_000": torch.tensor([1, 2]),
        "opd_top_k_ids__wing_002": torch.tensor([3, 4]),
    }

    with pytest.raises(RuntimeError, match="sparse wings are incomplete"):
        _decode_sparse_token_field(
            packed,
            "opd_top_k_ids",
            expected_wings=3,
        )


def test_chunked_sparse_scores_match_full_log_softmax() -> None:
    logits = torch.tensor(
        [[2.0, 1.0, 0.0, -1.0], [0.0, 2.0, 1.0, -1.0], [1.0, 0.0, 2.0, -1.0]],
        dtype=torch.float64,
    )
    token_ids = torch.tensor([[0, 2], [1, 0], [2, 1]])
    expected = F.log_softmax(logits / 0.7, dim=-1).gather(-1, token_ids)

    actual = _chunked_selected_log_probs(logits, token_ids, temperature=0.7, chunk_size=1)
    top_ids, top_log_probs = _chunked_top_k_log_probs(
        logits,
        top_k=2,
        temperature=0.7,
        chunk_size=1,
    )

    assert torch.allclose(actual, expected.float(), atol=1e-6, rtol=0)
    expected_top = F.log_softmax(logits / 0.7, dim=-1).gather(-1, top_ids)
    assert torch.allclose(top_log_probs, expected_top.float(), atol=1e-6, rtol=0)


def test_opd_diagnostics_report_overlap_mass_and_advantage() -> None:
    student_ids = torch.tensor([[0, 1], [1, 2]])
    teacher_ids = torch.tensor([[1, 2], [1, 0]])
    student_log_probs = torch.log(torch.tensor([[0.6, 0.3], [0.5, 0.2]]))
    teacher_on_student = torch.log(torch.tensor([[0.4, 0.5], [0.6, 0.1]]))
    teacher_log_probs = torch.log(torch.tensor([[0.7, 0.2], [0.6, 0.25]]))
    mask = torch.tensor([1.0, 0.0])
    turn_ids = torch.tensor([0, -1])

    result = compute_opd_diagnostics(
        student_ids,
        student_log_probs,
        teacher_on_student,
        teacher_ids,
        teacher_log_probs,
        mask,
        turn_ids,
    )

    assert result["opd_scored_tokens"].item() == 1
    assert result["opd_overlap_ratio"].item() == pytest.approx(0.5)
    assert result["opd_student_top_k_mass"].item() == pytest.approx(0.9)
    assert result["opd_teacher_on_student_mass"].item() == pytest.approx(0.9)
    assert result["opd_teacher_logprob_advantage"].item() > 0
    assert result["opd_teacher_student_kl"].item() >= 0
    assert result["opd_student_top_k_entropy"].item() > 0
    assert result["opd_teacher_on_student_entropy"].item() > 0
    assert result["opd_turn_0_scored_tokens"].item() == 1
    assert result["opd_turn_1_scored_tokens"].item() == 0


def test_opd_diagnostic_aggregation_is_token_weighted() -> None:
    def row(mask: torch.Tensor, turn_ids: torch.Tensor) -> dict[str, torch.Tensor]:
        ids = torch.tensor([[0, 1], [1, 2]])
        student = torch.log(torch.tensor([[0.6, 0.3], [0.5, 0.2]]))
        teacher = torch.log(torch.tensor([[0.4, 0.5], [0.6, 0.1]]))
        teacher_ids = torch.tensor([[1, 2], [1, 0]])
        teacher_top = torch.log(torch.tensor([[0.7, 0.2], [0.6, 0.25]]))
        return compute_opd_diagnostics(
            ids,
            student,
            teacher,
            teacher_ids,
            teacher_top,
            mask,
            turn_ids,
        )

    first = row(torch.tensor([1.0, 0.0]), torch.tensor([0, -1]))
    second = row(torch.tensor([1.0, 1.0]), torch.tensor([0, 1]))
    merged = aggregate_opd_diagnostics([first, second])

    assert merged["opd_scored_tokens"] == 3
    assert merged["opd_reward_wings"] == 6
    assert merged["opd_turn_0_scored_tokens"] == 2
    assert merged["opd_turn_1_scored_tokens"] == 1
    assert merged["opd_active_turns"] == 2
    assert merged["opd_teacher_student_kl"] >= 0
    assert merged["opd_student_top_k_entropy"] > 0
    assert merged["opd_teacher_on_student_entropy"] > 0


def test_opd_diagnostics_reject_empty_assistant_mask() -> None:
    values = torch.zeros((2, 2))
    with pytest.raises(RuntimeError, match="no trainable assistant tokens"):
        compute_opd_diagnostics(
            torch.zeros((2, 2), dtype=torch.long),
            values,
            values,
            torch.zeros((2, 2), dtype=torch.long),
            values,
            torch.zeros(2),
        )


def test_opd_config_is_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("areal")
    from areal.api.cli_args import load_expr_config

    from training.opd.config import StudyHubOPDConfig

    monkeypatch.setenv("STUDYHUB_AREAL_ADMIN_API_KEY", "unit-test-only")
    monkeypatch.setenv("STUDYHUB_CUDA_RUNTIME_LIBRARY_PATH", "/unit-test/cuda-runtime/lib")
    for name in (
        "ALL_PROXY",
        "all_proxy",
        "HTTP_PROXY",
        "http_proxy",
        "HTTPS_PROXY",
        "https_proxy",
    ):
        monkeypatch.delenv(name, raising=False)
    config, _ = load_expr_config(
        ["--config", str(PROJECT_ROOT / "configs/train/qwen35-4b-strict-opd.yaml")],
        StudyHubOPDConfig,
    )

    assert config.opd_top_k == 16
    assert config.opd_top_k_strategy == "only_stu"
    assert config.actor.mb_spec.max_tokens_per_mb == config.gconfig.max_tokens
    assert config.teacher.train.mb_spec.max_tokens_per_mb == config.gconfig.max_tokens
    assert config.actor.mb_spec.n_mbs == 128
    from areal.utils.data import allocate_balanced_mbs

    engine = SimpleNamespace(config=config.actor)
    engine._prepare_mb_list = lambda inputs: allocate_balanced_mbs(engine.config.mb_spec, [1000, 2000, 16000])
    groups = _prepare_opd_microbatches(engine, {"attention_mask": torch.ones(3, 1)})
    assert sorted(groups) == [[0], [1], [2]]
    assert config.actor.mb_spec.n_mbs == 128
    assert config.actor.kl_ctl == 0
    assert config.ref is None
    assert config.teacher.engine_type == "train"
    from scripts.train.preflight_qwen35_4b_opd import validate_rollout_memory_config

    validate_rollout_memory_config(config)
    assert config.sglang.enable_memory_saver is True
    assert config.sglang.enable_weights_cpu_backup is True
    from areal.api.cli_args import SGLangConfig

    args = SGLangConfig.build_args(config.sglang, tp_size=1, base_gpu_id=0)
    assert args["enable_weights_cpu_backup"] is True


def test_areal_bridge_install_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("areal")
    monkeypatch.delenv("STUDYHUB_OPD_STUDENT_ADAPTER", raising=False)

    install_areal_opd_bridge()
    install_areal_opd_bridge()

    from areal.engine.fsdp_engine import FSDPPPOActor

    assert callable(FSDPPPOActor.opd_compute_anchor)
    assert callable(FSDPPPOActor.opd_score_selected)
    assert callable(FSDPPPOActor.opd_update)
    assert os.environ.get("STUDYHUB_OPD_STUDENT_ADAPTER") is None
    from areal.engine.sglang_remote import SGLangBackend

    actor_env = {"TMS_INIT_ENABLE": "1", "TMS_INIT_ENABLE_CPU_BACKUP": "1", "CUDA_VISIBLE_DEVICES": "0"}
    child_env = SGLangBackend.build_server_env(actor_env)
    assert child_env["TMS_INIT_ENABLE"] == "0"
    assert child_env["TMS_INIT_ENABLE_CPU_BACKUP"] == "0"
    assert child_env["CUDA_VISIBLE_DEVICES"] == "0"
    assert actor_env["TMS_INIT_ENABLE"] == "1"
    assert actor_env["TMS_INIT_ENABLE_CPU_BACKUP"] == "1"


def test_opd_bridge_skips_only_single_rank_rpc_broadcast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("areal")
    from areal.infra.rpc.guard import engine_blueprint

    install_areal_opd_bridge()
    engine = SimpleNamespace(
        initialized=True,
        context_and_model_parallel_group=object(),
    )
    monkeypatch.setattr(torch.distributed, "is_available", lambda: True)
    monkeypatch.setattr(torch.distributed, "is_initialized", lambda: True)
    monkeypatch.setattr(torch.distributed, "get_world_size", lambda group=None: 1)

    assert engine_blueprint._should_broadcast_payload(engine, {"broadcast": True}) is False

    monkeypatch.setattr(torch.distributed, "get_world_size", lambda group=None: 2)
    assert engine_blueprint._should_broadcast_payload(engine, {"broadcast": True}) is True

    engine.initialized = False
    monkeypatch.setattr(torch.distributed, "get_world_size", lambda group=None: 1)
    assert engine_blueprint._should_broadcast_payload(engine, {"broadcast": True}) is True


def test_opd_bridge_makes_only_redundant_fsdp_offload_a_noop() -> None:
    pytest.importorskip("areal")
    from areal.engine.fsdp_engine import FSDPEngine

    install_areal_opd_bridge()
    messages: list[str] = []
    engine = SimpleNamespace(
        is_offload=True,
        logger=SimpleNamespace(info=lambda message: messages.append(message)),
    )

    assert FSDPEngine.offload(engine) is None
    assert messages == ["StudyHub skipped redundant FSDP offload"]
    assert callable(FSDPEngine.offload._studyhub_upstream)


def test_opd_proxy_bridge_temporarily_onloads_colocated_rollout() -> None:
    events: list[str] = []
    trainer = SimpleNamespace(
        _proxy_started=False,
        _should_offload_rollout=True,
        _onload_rollout=lambda: events.append("onload"),
        _offload_rollout=lambda: events.append("offload"),
    )

    def start_proxy() -> None:
        events.append("start_proxy")
        trainer._proxy_started = True

    trainer._ensure_proxy_started = start_proxy
    _install_colocated_proxy_start_bridge(trainer)

    trainer._ensure_proxy_started()
    trainer._ensure_proxy_started()

    assert events == ["onload", "start_proxy", "offload", "start_proxy"]
    assert trainer._ensure_proxy_started._studyhub_opd_colocated_proxy_start_v1


def test_opd_proxy_bridge_leaves_separated_rollout_unchanged() -> None:
    events: list[str] = []
    trainer = SimpleNamespace(
        _proxy_started=False,
        _should_offload_rollout=False,
        _onload_rollout=lambda: events.append("onload"),
        _offload_rollout=lambda: events.append("offload"),
    )

    def start_proxy() -> None:
        events.append("start_proxy")

    trainer._ensure_proxy_started = start_proxy
    _install_colocated_proxy_start_bridge(trainer)
    trainer._ensure_proxy_started()

    assert events == ["start_proxy"]
