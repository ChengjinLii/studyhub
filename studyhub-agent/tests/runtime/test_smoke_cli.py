import importlib.util
from pathlib import Path

import pytest

from studyhub_agent.contracts.episode import Episode
from tests.architectures.test_hooks import _spec
from tests.runtime.fakes import CharTokenizer, ScriptedPolicy, final_turn, parse_error_turn

SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "smoke_episodes.py"
module_spec = importlib.util.spec_from_file_location("smoke_episodes", SCRIPT_PATH)
smoke = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(smoke)


@pytest.fixture
def args(tmp_path):
    model = tmp_path / "4B"
    model.mkdir()
    (model / "tokenizer.json").write_text("{}", encoding="utf-8")
    tasks = tmp_path / "tasks.jsonl"
    tasks.write_text(_spec().model_dump_json() + "\n\n", encoding="utf-8")
    return [
        "--model-dir",
        str(model),
        "--sglang-url",
        "http://small.invalid",
        "--snapshot",
        str(Path(__file__).parents[1] / "fixtures" / "replay_snapshot.json"),
        "--tasks",
        str(tasks),
        "--out",
        str(tmp_path / "results" / "episodes.jsonl"),
    ]


def _large_args(tmp_path):
    model = tmp_path / "9B"
    model.mkdir()
    (model / "tokenizer.json").write_text("{}", encoding="utf-8")
    return ["--large-model-dir", str(model), "--large-sglang-url", "http://large.invalid"]


@pytest.mark.parametrize("architecture", ["react", "react_verify", "plan_execute", "react_context", "cascade"])
def test_cli_writes_episodes_with_each_architecture(args, tmp_path, monkeypatch, architecture) -> None:
    class Tokenizer(CharTokenizer):
        def __init__(self, path):
            self.revision = path.name + "@test-rev"

    monkeypatch.setattr(smoke.HFTokenizer, "from_model_dir", Tokenizer)
    small_turns = [parse_error_turn()] if architecture == "cascade" else [final_turn("答案")]
    if architecture == "plan_execute":
        small_turns.insert(0, final_turn("1. 检索\n2. 阅读\n3. 回答"))
    policies = {"4B": ScriptedPolicy(small_turns), "9B": ScriptedPolicy([final_turn("答案")])}
    monkeypatch.setattr(smoke, "SGLangGenerateBackend", lambda url: url)
    monkeypatch.setattr(
        smoke, "TokenPolicyClient", lambda tokenizer, backend: policies[tokenizer.revision.split("@")[0]]
    )
    command = [*args, "--architecture", architecture, "--model-id", "Qwen/Qwen3.5-4B"]
    if architecture == "cascade":
        command += [*_large_args(tmp_path), "--large-model-id", "Qwen/Qwen3.5-9B"]
    smoke.main(command)
    output = Path(args[-1]).read_text(encoding="utf-8").splitlines()
    assert len(output) == 1
    episode = Episode.model_validate_json(output[0])
    assert episode.final_answer == "答案" and episode.architecture == architecture + "@1.0"
    assert episode.model_revisions["small"] == "4B@test-rev"
    if architecture == "cascade":
        assert episode.model_revisions["large"] == "9B@test-rev"
        assert episode.turns[-1].model_id == "Qwen/Qwen3.5-9B"
        assert policies["9B"].seen[0] == episode.messages[:-1]


@pytest.mark.parametrize(
    "options,error",
    [
        (["--architecture", "cascade"], "requires --large-model-dir"),
        (["--large-model-id", "9B"], "only used"),
        (["--architecture", "react_verify", "--max-citation-rejections", "-1"], "--max-citation-rejections"),
        (["--max-citation-rejections", "-1"], "--max-citation-rejections"),
        (["--architecture", "plan_execute", "--max-plan-chars", "0"], "max_plan_chars"),
        (["--architecture", "react_context", "--context-threshold", "nan"], "context_threshold"),
        (["--architecture", "react_context", "--keep-recent-tools", "-1"], "keep_recent_tools"),
    ],
)
def test_bad_cli_configuration_fails_before_creating_output(args, options, error, capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        smoke.main([*args, *options])
    assert exc.value.code == 2 and error in capsys.readouterr().err
    assert not Path(args[-1]).exists()


@pytest.mark.parametrize("missing", ["small_tokenizer", "large_tokenizer", "snapshot", "tasks"])
def test_missing_cli_inputs_fail_before_execution(args, tmp_path, missing, capsys) -> None:
    command = list(args)
    if missing == "small_tokenizer":
        Path(args[1], "tokenizer.json").unlink()
    elif missing == "large_tokenizer":
        command += ["--architecture", "cascade", *_large_args(tmp_path)]
        Path(command[-3], "tokenizer.json").unlink()
    else:
        flag_index = command.index("--" + missing)
        command[flag_index + 1] = str(tmp_path / "missing.json")
    with pytest.raises(SystemExit) as exc:
        smoke.main(command)
    assert exc.value.code == 2
    error = capsys.readouterr().err
    assert ("no tokenizer.json" if "tokenizer" in missing else "does not exist") in error
    assert not Path(args[-1]).exists()
