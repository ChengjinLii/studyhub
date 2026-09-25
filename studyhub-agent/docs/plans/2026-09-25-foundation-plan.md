# StudyHub Agent v3 Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the legacy studyhub-agent code with a small, tested foundation: one versioned runtime contract, one `EpisodeRunner` shared by data generation / RL rollout / evaluation, token-level and OpenAI-compatible policy clients, a gated replay environment with 7 MCP-aligned tools, and a grader protocol.

**Architecture:** Pure-data `contracts` (tool specs, prompts, episode models, the single Qwen3.5 chat renderer/parser, contract hash) sit at the bottom. `guardrails` → `tools` (specs + MCP names) → `environments` (replay implementation) → `runtime` (runner + clients) build on it; `graders` depends only on `contracts`. The direction is enforced by import-linter in CI.

**Tech Stack:** Python 3.12, pydantic v2, jinja2 (sandboxed, to render the vendored Qwen3.5 chat template), httpx (SGLang `/generate`, OpenAI-compatible `/v1/chat/completions`), `tokenizers` (optional, real tokenizer), pytest + pytest-cov, ruff, import-linter.

**Spec:** `studyhub-agent/docs/specs/2026-09-25-foundation-design.md`

## Global Constraints

- Package: directory `studyhub-agent/`, import package `studyhub_agent` in `studyhub-agent/src/studyhub_agent/`, project name `studyhub-agent`, version `3.0.0`, `requires-python = ">=3.12,<3.13"`.
- Main-line model: official post-trained `Qwen3.5-4B` (instruct). Chat template vendored verbatim from `/data/chengjin/studyhub/models/P1/Qwen3.5-4B/chat_template.jinja`; its SHA-256 is part of the contract.
- Every config/data model: pydantic `ConfigDict(frozen=True, extra="forbid")` — unknown fields are errors.
- `thinking` is an `EpisodeSpec` field, default `False`, constant for the whole episode.
- Turn rule `turn-rule@1`: a turn containing any tool call is a TOOL_CALLS turn (its text is an internal preamble, never an answer); a turn without tool calls is FINAL; text after a tool call, unclosed tags or schema-invalid arguments make the whole turn PARSE_ERROR and none of its calls execute.
- Tool names (8; the spec's "7 tools" counts `memory_get`/`memory_update` as one memory pair): `materials_search`, `materials_get`, `materials_recommend`, `platform_policy`, `materials_read`, `web_extract`, `memory_get`, `memory_update`.
- All 8 tools carry `capability="snapshot"` in v3 (replay data); the four materials/policy tools also set `mcp_name`.
- JSON serialization of tool payloads and tool arguments: `json.dumps(..., ensure_ascii=False, sort_keys=True, separators=(",", ":"))`.
- Data sources: open data and self-hosted open models only; no Codex/gpt outputs; no uploader personal data.
- Coverage of `studyhub_agent` ≥ 80%; `ruff check` clean; import-linter contracts pass.
- Commit messages: conventional (`feat:`, `test:`, `refactor:`, `chore:`, `ci:`, `docs:`), English, no Co-Authored-By line, author `ChengjinLii <2731938007@qq.com>`.
- Do not delete gitignored large artifacts (`artifacts/`, `training_artifacts/`, `evaluation_artifacts/`, `datasets/`) or non-agent remote branches.

## Execution Environment

- Repo root on the server: a worktree of `/data/chengjin/studyhub` at `origin/main` (the orchestrator creates it, e.g. `/data/chengjin/studyhub-agent-v3`). All paths below are relative to the repo root.
- Python env (Task 1 creates it): `PY=/data/chengjin/.venvs/studyhub-agent/bin/python`. Commands below write `$PY`; expand it literally.
- Run tests from `studyhub-agent/`: `cd studyhub-agent && $PY -m pytest ...`.

## Review Focus

1. Tool argument strings with newlines, Chinese text, or a literal `</parameter>` inside a value — the parser must round-trip multi-line and non-ASCII values, and reject (PARSE_ERROR, not crash) values it cannot represent. Pinned in Task 5 (`test_parse_multiline_chinese_value_round_trips`, `test_value_containing_parameter_close_tag_is_rejected_by_renderer`).
2. Models emitting integers as strings (`"101"`) or garbage (`"abc"`) for integer parameters — coerce valid numerals, PARSE_ERROR on garbage, never an exception. Pinned in Task 5 (`test_integer_parameter_coercion`).
3. A turn with two tool calls where the second is invalid — nothing executes (no partial side effects such as a `memory_update`). Pinned in Task 10 (`test_turn_with_one_invalid_call_executes_nothing`).
4. A tool implementation raising an unexpected exception — the episode ends with `ENV_ERROR` / `FailureOwner.ENV`, the batch keeps going. Pinned in Task 10 (`test_environment_exception_ends_episode_as_env_error`).
5. Rendering determinism across the two policy clients — the canonical completion text for the same logical turn is byte-identical whether it came from SGLang tokens or an OpenAI-style message, including Chinese content and argument key order. Pinned in Task 11 (`test_token_and_openai_clients_produce_identical_canonical_completion`).

---

### Task 1: Tag legacy, remove old code, scaffold the v3 package

**Files:**
- Delete (git rm): everything under `studyhub-agent/` except `docs/` and `design-defects/`
- Move: `studyhub-agent/docs/*` (except `specs/`, `plans/`) → `studyhub-agent/docs/history/`; `studyhub-agent/design-defects/` → `studyhub-agent/docs/history/design-defects/`; `studyhub-agent/README.md` → `studyhub-agent/docs/history/README-v2.md`
- Delete: `.github/workflows/agent-v2.yml`
- Create: `studyhub-agent/pyproject.toml`, `studyhub-agent/README.md`, `studyhub-agent/src/studyhub_agent/__init__.py`, `studyhub-agent/src/studyhub_agent/{contracts,guardrails,tools,environments,runtime,graders}/__init__.py`, `studyhub-agent/tests/__init__.py`, `studyhub-agent/tests/test_package.py`, `studyhub-agent/.importlinter`

**Interfaces:**
- Produces: importable package `studyhub_agent` with `__version__ = "3.0.0"`; venv at `/data/chengjin/.venvs/studyhub-agent`.

- [ ] **Step 1: Create tags for history (run in `/data/chengjin/studyhub`)**

```bash
cd /data/chengjin/studyhub
git fetch origin
git tag legacy-agent-v2 origin/main
git tag archive/opd-evaluation codex/qwen35-4b-opd-evaluation
git tag archive/opd-execution codex/qwen35-4b-opd-execution
git tag archive/opd-preflight codex/qwen35-4b-opd-preflight
git push origin legacy-agent-v2 archive/opd-evaluation archive/opd-execution archive/opd-preflight
```
Expected: 4 new tags on the remote (`git ls-remote --tags origin | grep -E "legacy-agent-v2|archive/opd"` shows 4 lines).

- [ ] **Step 2: Move docs to history and remove legacy code (in the worktree)**

```bash
cd studyhub-agent
mkdir -p docs/history
for entry in docs/*; do
  case "$entry" in docs/specs|docs/plans|docs/history) continue ;; esac
  git mv "$entry" docs/history/
done
git mv design-defects docs/history/design-defects
git mv README.md docs/history/README-v2.md
for entry in $(git ls-files | cut -d/ -f1 | sort -u); do
  case "$entry" in docs) continue ;; esac
  git rm -r -q "$entry"
done
cd ..
git rm -q .github/workflows/agent-v2.yml
git ls-files studyhub-agent | cut -d/ -f2 | sort -u
```
Expected last output: only `docs`.

- [ ] **Step 3: Write `studyhub-agent/pyproject.toml`**

```toml
[build-system]
requires = ["hatchling>=1.27"]
build-backend = "hatchling.build"

[project]
name = "studyhub-agent"
version = "3.0.0"
description = "StudyHub agent: runtime contract, episode runner, replay environment and graders"
readme = "README.md"
requires-python = ">=3.12,<3.13"
dependencies = [
  "pydantic>=2.7,<3.0",
  "jinja2>=3.1,<4.0",
  "httpx>=0.27,<1.0",
]

[project.optional-dependencies]
tokenizers = ["tokenizers>=0.20,<1.0"]
acceptance = ["transformers>=4.51,<5.0"]
dev = [
  "pytest>=8.3,<9.0",
  "pytest-cov>=5.0,<7.0",
  "ruff>=0.9,<0.14",
  "import-linter>=2.1,<3.0",
]

[tool.hatch.build.targets.wheel]
packages = ["src/studyhub_agent"]

[tool.pytest.ini_options]
addopts = "-q"
testpaths = ["tests"]
markers = ["requires_model: needs the Qwen3.5-4B tokenizer/model files (set STUDYHUB_AGENT_MODEL_DIR)"]

[tool.coverage.run]
source = ["studyhub_agent"]

[tool.coverage.report]
fail_under = 80
show_missing = true

[tool.ruff]
line-length = 120
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
```

- [ ] **Step 4: Write `studyhub-agent/.importlinter`**

```ini
[importlinter]
root_package = studyhub_agent

[importlinter:contract:layers]
name = Foundation layers
type = layers
layers =
    studyhub_agent.runtime
    studyhub_agent.environments
    studyhub_agent.tools
    studyhub_agent.guardrails
    studyhub_agent.contracts

[importlinter:contract:graders]
name = Graders depend only on contracts
type = forbidden
source_modules =
    studyhub_agent.graders
forbidden_modules =
    studyhub_agent.runtime
    studyhub_agent.environments
    studyhub_agent.tools
    studyhub_agent.guardrails
```

- [ ] **Step 5: Package skeleton and first test**

`studyhub-agent/src/studyhub_agent/__init__.py`:
```python
"""StudyHub agent v3 foundation."""

__version__ = "3.0.0"
```
Each of `contracts/__init__.py`, `guardrails/__init__.py`, `tools/__init__.py`, `environments/__init__.py`, `runtime/__init__.py`, `graders/__init__.py`, `tests/__init__.py`: empty file.

`studyhub-agent/tests/test_package.py`:
```python
import studyhub_agent


def test_version_is_v3() -> None:
    assert studyhub_agent.__version__ == "3.0.0"
```

`studyhub-agent/README.md` (short; rewritten fully in Task 13):
```markdown
# StudyHub Agent v3

Foundation for the StudyHub agent research project. Design: `docs/specs/2026-09-25-foundation-design.md`.
Legacy v2 code is preserved at git tag `legacy-agent-v2`; its reports live in `docs/history/`.
```

- [ ] **Step 6: Create the venv and run the test**

```bash
/home/chengjin/.local/share/uv/python/cpython-3.12.13-linux-x86_64-gnu/bin/python3.12 -m venv /data/chengjin/.venvs/studyhub-agent
/data/chengjin/.venvs/studyhub-agent/bin/pip install -q -e "studyhub-agent[dev,tokenizers]"
cd studyhub-agent && $PY -m pytest tests/test_package.py && $PY -m ruff check src tests && lint-imports --config .importlinter
```
(`lint-imports` is `/data/chengjin/.venvs/studyhub-agent/bin/lint-imports`.)
Expected: `1 passed`; ruff clean; import-linter "Contracts: 2 kept, 0 broken".

- [ ] **Step 7: Commit**

```bash
git add -A studyhub-agent .github/workflows
git commit -m "refactor: replace legacy studyhub-agent with v3 package skeleton

Legacy code is preserved at tag legacy-agent-v2; reports and design-defects move to docs/history."
```

---

### Task 2: ToolSpec contract and schema lint

**Files:**
- Create: `studyhub-agent/src/studyhub_agent/contracts/tools.py`
- Test: `studyhub-agent/tests/contracts/test_tools.py` (+ empty `tests/contracts/__init__.py`)

**Interfaces:**
- Produces: `ToolSpec(name, version, description, parameters, capability="snapshot", mcp_name=None)` frozen dataclass with `.to_openai() -> dict`, `.canonical() -> dict`; `ToolSpecError(ValueError)`; `lint_tool_spec(spec) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
import pytest

from studyhub_agent.contracts.tools import ToolSpec, ToolSpecError


def _params(**properties):
    return {"type": "object", "properties": properties, "required": [], "additionalProperties": False}


def test_valid_spec_renders_openai_shape() -> None:
    spec = ToolSpec(
        name="materials_get",
        version="1.0",
        description="读取资料详情",
        parameters=_params(material_id={"type": "integer", "description": "资料 ID"}),
        mcp_name="materials.get",
    )
    assert spec.to_openai() == {
        "type": "function",
        "function": {"name": "materials_get", "description": "读取资料详情", "parameters": spec.parameters},
    }


@pytest.mark.parametrize(
    ("name", "parameters", "message"),
    [
        ("Bad-Name", _params(), "name"),
        ("ok_name", {"type": "array"}, "object"),
        ("ok_name", _params(x={"type": "int", "description": "d"}), "type"),
        ("ok_name", _params(x={"type": "string"}), "description"),
        ("ok_name", _params(x={"type": "string", "description": "d", "enum": [str(i) for i in range(40)]}), "enum"),
        ("ok_name", {**_params(x={"type": "string", "description": "d"}), "required": ["y"]}, "required"),
        ("ok_name", {**_params(), "additionalProperties": True}, "additionalProperties"),
        ("ok_name", _params(x={"type": "array", "description": "d"}), "items"),
    ],
)
def test_lint_rejects_invalid_specs(name, parameters, message) -> None:
    with pytest.raises(ToolSpecError, match=message):
        ToolSpec(name=name, version="1.0", description="desc", parameters=parameters)


def test_lint_rejects_bad_version_and_empty_description() -> None:
    with pytest.raises(ToolSpecError, match="version"):
        ToolSpec(name="ok", version="v1", description="desc", parameters=_params())
    with pytest.raises(ToolSpecError, match="description"):
        ToolSpec(name="ok", version="1.0", description=" ", parameters=_params())


def test_canonical_form_is_order_independent() -> None:
    a = ToolSpec(name="t", version="1.0", description="d", parameters={"type": "object", "properties": {}, "required": [], "additionalProperties": False})
    b = ToolSpec(name="t", version="1.0", description="d", parameters={"additionalProperties": False, "required": [], "properties": {}, "type": "object"})
    assert a.canonical() == b.canonical()
```

- [ ] **Step 2: Run to verify failure**

Run: `cd studyhub-agent && $PY -m pytest tests/contracts/test_tools.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'studyhub_agent.contracts.tools'`.

- [ ] **Step 3: Implement `contracts/tools.py`**

```python
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

ALLOWED_JSON_TYPES = frozenset({"string", "integer", "number", "boolean", "array", "object", "null"})
TOOL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
VERSION_PATTERN = re.compile(r"^\d+\.\d+$")
MAX_ENUM_VALUES = 32

Capability = Literal["live", "snapshot"]


class ToolSpecError(ValueError):
    """Raised when a tool specification violates the runtime contract."""


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    version: str
    description: str
    parameters: dict[str, Any]
    capability: Capability = "snapshot"
    mcp_name: str | None = None

    def __post_init__(self) -> None:
        lint_tool_spec(self)

    def to_openai(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": self.parameters},
        }

    def canonical(self) -> dict[str, Any]:
        return json.loads(
            json.dumps(
                {
                    "name": self.name,
                    "version": self.version,
                    "description": self.description,
                    "parameters": self.parameters,
                    "capability": self.capability,
                    "mcp_name": self.mcp_name,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )


def lint_tool_spec(spec: ToolSpec) -> None:
    if not TOOL_NAME_PATTERN.match(spec.name):
        raise ToolSpecError(f"tool name {spec.name!r} must match {TOOL_NAME_PATTERN.pattern}")
    if not VERSION_PATTERN.match(spec.version):
        raise ToolSpecError(f"tool {spec.name}: version {spec.version!r} must look like 1.0")
    if not spec.description.strip():
        raise ToolSpecError(f"tool {spec.name}: description must not be empty")
    params = spec.parameters
    if params.get("type") != "object":
        raise ToolSpecError(f"tool {spec.name}: parameters must be a JSON Schema object")
    if params.get("additionalProperties") is not False:
        raise ToolSpecError(f"tool {spec.name}: parameters must set additionalProperties to false")
    properties = params.get("properties", {})
    missing = set(params.get("required", [])) - set(properties)
    if missing:
        raise ToolSpecError(f"tool {spec.name}: required names unknown properties {sorted(missing)}")
    for prop_name, schema in properties.items():
        _lint_property(spec.name, prop_name, schema)


def _lint_property(tool: str, prop_name: str, schema: dict[str, Any]) -> None:
    prop_type = schema.get("type")
    if prop_type not in ALLOWED_JSON_TYPES:
        raise ToolSpecError(f"tool {tool}: property {prop_name} has invalid type {prop_type!r}")
    if not str(schema.get("description", "")).strip():
        raise ToolSpecError(f"tool {tool}: property {prop_name} needs a description")
    if len(schema.get("enum", [])) > MAX_ENUM_VALUES:
        raise ToolSpecError(f"tool {tool}: property {prop_name} enum exceeds {MAX_ENUM_VALUES} values")
    if prop_type == "array":
        items = schema.get("items")
        if not isinstance(items, dict) or items.get("type") not in ALLOWED_JSON_TYPES:
            raise ToolSpecError(f"tool {tool}: array property {prop_name} needs typed items")
```

- [ ] **Step 4: Run to verify pass**

Run: `cd studyhub-agent && $PY -m pytest tests/contracts/test_tools.py -q`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add studyhub-agent/src/studyhub_agent/contracts/tools.py studyhub-agent/tests/contracts
git commit -m "feat: add ToolSpec contract with schema lint"
```

---

### Task 3: Versioned prompt registry

**Files:**
- Create: `studyhub-agent/src/studyhub_agent/contracts/prompts.py`
- Test: `studyhub-agent/tests/contracts/test_prompts.py`

**Interfaces:**
- Produces: `PromptTemplate(prompt_id, version, text)` with `.key -> "id@version"`; `PromptRegistry(prompts)` with `.get(key) -> PromptTemplate`, `.with_prompt(prompt) -> PromptRegistry`, `.keys() -> tuple[str, ...]`; constants `SYSTEM_PROMPT_KEY = "studyhub.agent.system@1.0"`, `FINALIZE_PROMPT_KEY = "studyhub.agent.finalize@1.0"`, `DEFAULT_PROMPTS: PromptRegistry`.

- [ ] **Step 1: Write the failing tests**

```python
import pytest

from studyhub_agent.contracts.prompts import (
    DEFAULT_PROMPTS,
    FINALIZE_PROMPT_KEY,
    SYSTEM_PROMPT_KEY,
    PromptRegistry,
    PromptTemplate,
)


def test_default_registry_has_system_and_finalize_prompts() -> None:
    assert DEFAULT_PROMPTS.get(SYSTEM_PROMPT_KEY).text.strip()
    assert DEFAULT_PROMPTS.get(FINALIZE_PROMPT_KEY).text.strip()


def test_duplicate_keys_are_rejected() -> None:
    prompt = PromptTemplate("p", "1.0", "text")
    with pytest.raises(ValueError, match="duplicate"):
        PromptRegistry([prompt, prompt])


def test_unknown_key_raises_with_known_keys_listed() -> None:
    with pytest.raises(KeyError, match="studyhub.agent.system@1.0"):
        DEFAULT_PROMPTS.get("missing@9.9")


def test_with_prompt_returns_new_registry_without_mutating() -> None:
    extended = DEFAULT_PROMPTS.with_prompt(PromptTemplate("extra", "1.0", "hi"))
    assert "extra@1.0" in extended.keys()
    assert "extra@1.0" not in DEFAULT_PROMPTS.keys()


def test_prompt_version_must_be_numeric() -> None:
    with pytest.raises(ValueError, match="version"):
        PromptTemplate("p", "latest", "text")
```

- [ ] **Step 2: Run to verify failure**

Run: `cd studyhub-agent && $PY -m pytest tests/contracts/test_prompts.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `contracts/prompts.py`**

```python
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from types import MappingProxyType

_VERSION = re.compile(r"^\d+\.\d+$")

SYSTEM_PROMPT_KEY = "studyhub.agent.system@1.0"
FINALIZE_PROMPT_KEY = "studyhub.agent.finalize@1.0"

_SYSTEM_TEXT = """你是 StudyHub 学习助手，服务高校学生查找学习资料、了解平台规则。
工作方式：
- 需要事实时先调用工具检索，不要凭记忆编造资料名称、页码或政策条款。
- 读取资料内容前必须先通过 materials_search 或 materials_recommend 找到它。
- 回答时引用你实际读到的资料，格式为 [资料ID:页码]；没有读到的内容不要引用。
- 工具返回错误时根据错误调整参数，不要重复同样的调用。
- 信息足够后直接给出简洁的中文回答；不要在同一条回复里既调用工具又给出最终回答。"""

_FINALIZE_TEXT = "这是最后一轮。请不要再调用工具，根据已经获得的信息直接给出最终回答；信息不足时说明缺少什么。"


@dataclass(frozen=True, slots=True)
class PromptTemplate:
    prompt_id: str
    version: str
    text: str

    def __post_init__(self) -> None:
        if not self.prompt_id.strip():
            raise ValueError("prompt_id must not be empty")
        if not _VERSION.match(self.version):
            raise ValueError(f"prompt {self.prompt_id}: version {self.version!r} must look like 1.0")

    @property
    def key(self) -> str:
        return f"{self.prompt_id}@{self.version}"


class PromptRegistry:
    def __init__(self, prompts: Iterable[PromptTemplate] = ()) -> None:
        mapping: dict[str, PromptTemplate] = {}
        for prompt in prompts:
            if prompt.key in mapping:
                raise ValueError(f"duplicate prompt {prompt.key}")
            mapping[prompt.key] = prompt
        self._prompts = MappingProxyType(mapping)

    def get(self, key: str) -> PromptTemplate:
        try:
            return self._prompts[key]
        except KeyError:
            raise KeyError(f"unknown prompt {key!r}; known: {', '.join(sorted(self._prompts))}") from None

    def with_prompt(self, prompt: PromptTemplate) -> PromptRegistry:
        return PromptRegistry([*self._prompts.values(), prompt])

    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._prompts))


DEFAULT_PROMPTS = PromptRegistry(
    [
        PromptTemplate("studyhub.agent.system", "1.0", _SYSTEM_TEXT),
        PromptTemplate("studyhub.agent.finalize", "1.0", _FINALIZE_TEXT),
    ]
)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd studyhub-agent && $PY -m pytest tests/contracts/test_prompts.py -q`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add studyhub-agent/src/studyhub_agent/contracts/prompts.py studyhub-agent/tests/contracts/test_prompts.py
git commit -m "feat: add versioned prompt registry"
```

---

### Task 4: Episode data models

**Files:**
- Create: `studyhub-agent/src/studyhub_agent/contracts/episode.py`
- Test: `studyhub-agent/tests/contracts/test_episode.py`

**Interfaces:**
- Produces (all pydantic, frozen, `extra="forbid"`):
  - `ToolCall(call_id: str, name: str, arguments: dict[str, Any])`
  - `Message(role: Literal["system","user","assistant","tool"], content: str = "", tool_calls: tuple[ToolCall, ...] = (), tool_call_id: str | None = None, name: str | None = None)`
  - `Sampling(temperature: float = 0.0, top_p: float = 1.0, seed: int | None = None)`
  - `Budget(max_turns=12, max_tool_calls=16, max_parse_errors=2, max_context_tokens=16384, max_new_tokens=2048)` (all `ge=1`; validator: `max_new_tokens < max_context_tokens`)
  - `Principal(principal_id: str, purchased_material_ids: frozenset[int] = frozenset(), owned_material_ids: frozenset[int] = frozenset(), is_admin: bool = False)`
  - `EpisodeSpec(episode_id, task_id, user_message, principal: Principal, system_prompt: str = SYSTEM_PROMPT_KEY, finalize_prompt: str = FINALIZE_PROMPT_KEY, tool_names: tuple[str, ...], thinking: bool = False, budget: Budget = Budget(), sampling: Sampling = Sampling(), metadata: dict[str, str] = {})`
  - `TurnKind(StrEnum)`: `TOOL_CALLS`, `FINAL`, `PARSE_ERROR`
  - `AssistantTurn(kind, content: str = "", tool_calls: tuple[ToolCall, ...] = (), raw_text: str, canonical_text: str, parse_error: str | None = None, prompt_token_ids: tuple[int, ...] = (), completion_token_ids: tuple[int, ...] = (), completion_logprobs: tuple[float, ...] = (), non_canonical: bool = False, server_parse_mismatch: bool = False, finish_reason: str | None = None, latency_ms: float = 0.0)`
  - `Observation(call_id: str, name: str, ok: bool, payload: dict[str, Any], error_code: str | None = None)`
  - `Termination(StrEnum)`: `FINAL_ANSWER`, `MAX_TURNS`, `TOOL_BUDGET`, `PARSE_ERROR_BUDGET`, `CONTEXT_BUDGET`, `ENV_ERROR`, `INFRA_ERROR`
  - `FailureOwner(StrEnum)`: `NONE`, `MODEL`, `ENV`, `INFRA`
  - `Episode(spec, contract_hash: str, messages: tuple[Message, ...], turns: tuple[AssistantTurn, ...], observations: tuple[Observation, ...], termination: Termination, failure_owner: FailureOwner, final_answer: str | None = None, error_detail: str | None = None, environment_trace: dict[str, Any] = {})`

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from pydantic import ValidationError

from studyhub_agent.contracts.episode import (
    Budget,
    Episode,
    EpisodeSpec,
    FailureOwner,
    Message,
    Principal,
    Termination,
)


def _spec(**overrides):
    base = {
        "episode_id": "ep-1",
        "task_id": "task-1",
        "user_message": "帮我找高数期末复习资料",
        "principal": Principal(principal_id="u-1001"),
        "tool_names": ("materials_search",),
    }
    return EpisodeSpec(**{**base, **overrides})


def test_spec_defaults_are_contract_defaults() -> None:
    spec = _spec()
    assert spec.thinking is False
    assert spec.system_prompt == "studyhub.agent.system@1.0"
    assert spec.budget.max_turns == 12


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        _spec(temperature=0.7)


def test_models_are_immutable() -> None:
    spec = _spec()
    with pytest.raises(ValidationError):
        spec.thinking = True


def test_budget_requires_room_for_prompt() -> None:
    with pytest.raises(ValidationError, match="max_new_tokens"):
        Budget(max_context_tokens=1024, max_new_tokens=1024)


def test_episode_round_trips_through_json() -> None:
    episode = Episode(
        spec=_spec(),
        contract_hash="sha256:abc",
        messages=(Message(role="user", content="你好"),),
        turns=(),
        observations=(),
        termination=Termination.MAX_TURNS,
        failure_owner=FailureOwner.MODEL,
    )
    assert Episode.model_validate_json(episode.model_dump_json()) == episode
```

- [ ] **Step 2: Run to verify failure**

Run: `cd studyhub-agent && $PY -m pytest tests/contracts/test_episode.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `contracts/episode.py`**

```python
from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from studyhub_agent.contracts.prompts import FINALIZE_PROMPT_KEY, SYSTEM_PROMPT_KEY


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ToolCall(_Frozen):
    call_id: str
    name: str
    arguments: dict[str, Any]


class Message(_Frozen):
    role: Literal["system", "user", "assistant", "tool"]
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    name: str | None = None


class Sampling(_Frozen):
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    top_p: float = Field(default=1.0, gt=0.0, le=1.0)
    seed: int | None = None


class Budget(_Frozen):
    max_turns: int = Field(default=12, ge=1)
    max_tool_calls: int = Field(default=16, ge=1)
    max_parse_errors: int = Field(default=2, ge=0)
    max_context_tokens: int = Field(default=16384, ge=1)
    max_new_tokens: int = Field(default=2048, ge=1)

    @model_validator(mode="after")
    def _prompt_room(self) -> Budget:
        if self.max_new_tokens >= self.max_context_tokens:
            raise ValueError("max_new_tokens must be smaller than max_context_tokens")
        return self


class Principal(_Frozen):
    principal_id: str
    purchased_material_ids: frozenset[int] = frozenset()
    owned_material_ids: frozenset[int] = frozenset()
    is_admin: bool = False


class EpisodeSpec(_Frozen):
    episode_id: str
    task_id: str
    user_message: str
    principal: Principal
    system_prompt: str = SYSTEM_PROMPT_KEY
    finalize_prompt: str = FINALIZE_PROMPT_KEY
    tool_names: tuple[str, ...]
    thinking: bool = False
    budget: Budget = Budget()
    sampling: Sampling = Sampling()
    metadata: dict[str, str] = Field(default_factory=dict)


class TurnKind(StrEnum):
    TOOL_CALLS = "tool_calls"
    FINAL = "final"
    PARSE_ERROR = "parse_error"


class AssistantTurn(_Frozen):
    kind: TurnKind
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    raw_text: str
    canonical_text: str
    parse_error: str | None = None
    prompt_token_ids: tuple[int, ...] = ()
    completion_token_ids: tuple[int, ...] = ()
    completion_logprobs: tuple[float, ...] = ()
    non_canonical: bool = False
    server_parse_mismatch: bool = False
    finish_reason: str | None = None
    latency_ms: float = 0.0


class Observation(_Frozen):
    call_id: str
    name: str
    ok: bool
    payload: dict[str, Any]
    error_code: str | None = None


class Termination(StrEnum):
    FINAL_ANSWER = "final_answer"
    MAX_TURNS = "max_turns"
    TOOL_BUDGET = "tool_budget"
    PARSE_ERROR_BUDGET = "parse_error_budget"
    CONTEXT_BUDGET = "context_budget"
    ENV_ERROR = "env_error"
    INFRA_ERROR = "infra_error"


class FailureOwner(StrEnum):
    NONE = "none"
    MODEL = "model"
    ENV = "env"
    INFRA = "infra"


class Episode(_Frozen):
    spec: EpisodeSpec
    contract_hash: str
    messages: tuple[Message, ...]
    turns: tuple[AssistantTurn, ...]
    observations: tuple[Observation, ...]
    termination: Termination
    failure_owner: FailureOwner
    final_answer: str | None = None
    error_detail: str | None = None
    environment_trace: dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd studyhub-agent && $PY -m pytest tests/contracts/test_episode.py -q`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add studyhub-agent/src/studyhub_agent/contracts/episode.py studyhub-agent/tests/contracts/test_episode.py
git commit -m "feat: add episode data models"
```

---

### Task 5: The single chat renderer and tool-call parser

**Files:**
- Create: `studyhub-agent/src/studyhub_agent/contracts/templates/qwen3_5.jinja` (verbatim copy), `studyhub-agent/src/studyhub_agent/contracts/render.py`
- Modify: `studyhub-agent/pyproject.toml` — add `[tool.hatch.build.targets.wheel.force-include]` so the template ships: `"src/studyhub_agent/contracts/templates" = "studyhub_agent/contracts/templates"`
- Test: `studyhub-agent/tests/contracts/test_render.py`

**Interfaces:**
- Consumes: `ToolSpec` (Task 2), `Message`, `ToolCall`, `TurnKind` (Task 4).
- Produces:
  - `TEMPLATE_SHA256: str` (hex digest of the vendored template, checked at import)
  - `render_text(messages: Sequence[Message], tools: Sequence[ToolSpec], *, thinking: bool, add_generation_prompt: bool) -> str`
  - `ParsedCompletion(kind: TurnKind, content: str, tool_calls: tuple[ToolCall, ...], error: str | None)` frozen dataclass
  - `parse_completion(text: str, tools: Sequence[ToolSpec], *, thinking: bool) -> ParsedCompletion` (call ids are `call_0`, `call_1`, …; the runner re-labels them)
  - `canonical_completion_text(history: Sequence[Message], assistant: Message, tools: Sequence[ToolSpec], *, thinking: bool) -> str` — the exact text the template renders for `assistant` after the generation prompt, including the trailing `<|im_end|>\n`
  - `END_OF_TURN = "<|im_end|>"`
  - `RenderError(ValueError)` — raised by `render_text` when a value cannot be represented (e.g. string argument containing `</parameter>`)

- [ ] **Step 1: Vendor the template**

```bash
mkdir -p studyhub-agent/src/studyhub_agent/contracts/templates
cp /data/chengjin/studyhub/models/P1/Qwen3.5-4B/chat_template.jinja studyhub-agent/src/studyhub_agent/contracts/templates/qwen3_5.jinja
sha256sum studyhub-agent/src/studyhub_agent/contracts/templates/qwen3_5.jinja
```
Expected digest: `a4aee8afcf2e0711942cf848899be66016f8d14a889ff9ede07bca099c28f715` (already pinned in Step 4). A different digest means the model files changed — stop and report.

- [ ] **Step 2: Write the failing tests**

```python
import pytest

from studyhub_agent.contracts.episode import Message, ToolCall, TurnKind
from studyhub_agent.contracts.render import (
    RenderError,
    canonical_completion_text,
    parse_completion,
    render_text,
)
from studyhub_agent.contracts.tools import ToolSpec

SEARCH = ToolSpec(
    name="materials_search",
    version="1.0",
    description="检索资料",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "关键词"},
            "limit": {"type": "integer", "description": "条数"},
            "filters": {"type": "object", "description": "过滤条件"},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
)
TOOLS = (SEARCH,)
HISTORY = (
    Message(role="system", content="系统提示"),
    Message(role="user", content="找高数资料"),
)


def test_generation_prompt_disables_thinking_with_empty_block() -> None:
    text = render_text(HISTORY, TOOLS, thinking=False, add_generation_prompt=True)
    assert text.endswith("<|im_start|>assistant\n<think>\n\n</think>\n\n")
    assert '"name": "materials_search"' in text


def test_generation_prompt_with_thinking_opens_block() -> None:
    text = render_text(HISTORY, TOOLS, thinking=True, add_generation_prompt=True)
    assert text.endswith("<|im_start|>assistant\n<think>\n")


def test_parse_final_answer() -> None:
    parsed = parse_completion("这是答案。", TOOLS, thinking=False)
    assert parsed.kind is TurnKind.FINAL
    assert parsed.content == "这是答案。"


def test_parse_tool_call_with_preamble() -> None:
    text = "先检索一下。\n\n<tool_call>\n<function=materials_search>\n<parameter=query>\n高等数学 期末\n</parameter>\n<parameter=limit>\n5\n</parameter>\n</function>\n</tool_call>"
    parsed = parse_completion(text, TOOLS, thinking=False)
    assert parsed.kind is TurnKind.TOOL_CALLS
    assert parsed.content == "先检索一下。"
    assert parsed.tool_calls == (ToolCall(call_id="call_0", name="materials_search", arguments={"query": "高等数学 期末", "limit": 5}),)


def test_parse_multiline_chinese_value_round_trips() -> None:
    call = ToolCall(call_id="call_0", name="materials_search", arguments={"query": "线性代数\n第二章 习题", "filters": {"school": "电子科技大学"}})
    assistant = Message(role="assistant", content="", tool_calls=(call,))
    completion = canonical_completion_text(HISTORY, assistant, TOOLS, thinking=False)
    assert completion.endswith("<|im_end|>\n")
    parsed = parse_completion(completion, TOOLS, thinking=False)
    assert parsed.tool_calls == (call,)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("101", 101), (" 7 ", 7)],
)
def test_integer_parameter_coercion(raw, expected) -> None:
    text = f"<tool_call>\n<function=materials_search>\n<parameter=query>\nq\n</parameter>\n<parameter=limit>\n{raw}\n</parameter>\n</function>\n</tool_call>"
    assert parse_completion(text, TOOLS, thinking=False).tool_calls[0].arguments["limit"] == expected


@pytest.mark.parametrize(
    ("text", "error"),
    [
        ("<tool_call>\n<function=materials_search>\n<parameter=query>\nq\n</parameter>\n<parameter=limit>\nabc\n</parameter>\n</function>\n</tool_call>", "invalid_argument"),
        ("<tool_call>\n<function=materials_search>\n<parameter=limit>\n3\n</parameter>\n</function>\n</tool_call>", "missing_required"),
        ("<tool_call>\n<function=unknown_tool>\n</function>\n</tool_call>", "unknown_tool"),
        ("<tool_call>\n<function=materials_search>\n<parameter=query>\nq\n</parameter>\n</function>\n</tool_call>\n答案在此", "text_after_tool_call"),
        ("<tool_call>\n<function=materials_search>\n<parameter=query>\nq\n", "malformed_tool_call"),
        ("<tool_call>\n<function=materials_search>\n<parameter=bogus>\nq\n</parameter>\n</function>\n</tool_call>", "unknown_parameter"),
        ("   ", "empty_response"),
    ],
)
def test_parse_errors_are_reported_not_raised(text, error) -> None:
    parsed = parse_completion(text, TOOLS, thinking=False)
    assert parsed.kind is TurnKind.PARSE_ERROR
    assert parsed.error is not None and parsed.error.startswith(error)
    assert parsed.tool_calls == ()


def test_value_containing_parameter_close_tag_is_rejected_by_renderer() -> None:
    call = ToolCall(call_id="c", name="materials_search", arguments={"query": "x</parameter>y"})
    with pytest.raises(RenderError):
        canonical_completion_text(HISTORY, Message(role="assistant", tool_calls=(call,)), TOOLS, thinking=False)


def test_prefix_property_holds_for_tool_turns() -> None:
    call = ToolCall(call_id="c", name="materials_search", arguments={"query": "概率论"})
    assistant = Message(role="assistant", content="检索中", tool_calls=(call,))
    prompt = render_text(HISTORY, TOOLS, thinking=False, add_generation_prompt=True)
    full = render_text((*HISTORY, assistant), TOOLS, thinking=False, add_generation_prompt=False)
    assert full == prompt + canonical_completion_text(HISTORY, assistant, TOOLS, thinking=False)


def test_thinking_completion_splits_reasoning() -> None:
    parsed = parse_completion("先想想\n</think>\n\n最终答案", TOOLS, thinking=True)
    assert parsed.kind is TurnKind.FINAL
    assert parsed.content == "最终答案"


def test_trailing_end_of_turn_token_is_ignored() -> None:
    assert parse_completion("答案<|im_end|>", TOOLS, thinking=False).content == "答案"
```

- [ ] **Step 3: Run to verify failure**

Run: `cd studyhub-agent && $PY -m pytest tests/contracts/test_render.py -q`
Expected: FAIL — module not found.

- [ ] **Step 4: Implement `contracts/render.py`**

```python
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2.exceptions import TemplateError
from jinja2.sandbox import ImmutableSandboxedEnvironment

from studyhub_agent.contracts.episode import Message, ToolCall, TurnKind
from studyhub_agent.contracts.tools import ToolSpec

TEMPLATE_PATH = Path(__file__).parent / "templates" / "qwen3_5.jinja"
TEMPLATE_SHA256 = "a4aee8afcf2e0711942cf848899be66016f8d14a889ff9ede07bca099c28f715"
END_OF_TURN = "<|im_end|>"
_THINK_CLOSE = "</think>"

_CALL = re.compile(r"\s*<tool_call>\s*<function=([^>\n]+)>\n?(.*?)</function>\s*</tool_call>", re.DOTALL)
_PARAM = re.compile(r"<parameter=([^>\n]+)>\n(.*?)\n</parameter>", re.DOTALL)


class RenderError(ValueError):
    """A message cannot be represented faithfully by the chat template."""


@dataclass(frozen=True, slots=True)
class ParsedCompletion:
    kind: TurnKind
    content: str
    tool_calls: tuple[ToolCall, ...]
    error: str | None


def _raise_exception(message: str) -> None:
    raise RenderError(message)


def _tojson(value: Any, indent: int | None = None) -> str:
    # Matches transformers' chat-template tojson filter (ensure_ascii=False).
    return json.dumps(value, ensure_ascii=False, indent=indent)


@lru_cache(maxsize=1)
def _template():
    source = TEMPLATE_PATH.read_text(encoding="utf-8")
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    if digest != TEMPLATE_SHA256:
        raise RenderError(f"chat template digest {digest} does not match the pinned contract digest")
    env = ImmutableSandboxedEnvironment(trim_blocks=True, lstrip_blocks=True)
    env.filters["tojson"] = _tojson
    env.globals["raise_exception"] = _raise_exception
    return env.from_string(source)


def _message_dict(message: Message) -> dict[str, Any]:
    if message.role == "assistant" and message.tool_calls:
        for call in message.tool_calls:
            for value in call.arguments.values():
                if isinstance(value, str) and "</parameter>" in value:
                    raise RenderError(f"argument of {call.name} contains a </parameter> tag")
        return {
            "role": "assistant",
            "content": message.content,
            "tool_calls": [
                {"type": "function", "function": {"name": call.name, "arguments": call.arguments}}
                for call in message.tool_calls
            ],
        }
    return {"role": message.role, "content": message.content}


def render_text(
    messages: Sequence[Message],
    tools: Sequence[ToolSpec],
    *,
    thinking: bool,
    add_generation_prompt: bool,
) -> str:
    try:
        return _template().render(
            messages=[_message_dict(message) for message in messages],
            tools=[tool.to_openai() for tool in tools] or None,
            add_generation_prompt=add_generation_prompt,
            enable_thinking=thinking,
        )
    except TemplateError as exc:
        raise RenderError(str(exc)) from exc


def canonical_completion_text(
    history: Sequence[Message],
    assistant: Message,
    tools: Sequence[ToolSpec],
    *,
    thinking: bool,
) -> str:
    prompt = render_text(history, tools, thinking=thinking, add_generation_prompt=True)
    full = render_text((*history, assistant), tools, thinking=thinking, add_generation_prompt=False)
    if not full.startswith(prompt):
        raise RenderError("chat template violates the prompt prefix property")
    return full[len(prompt) :]


def parse_completion(text: str, tools: Sequence[ToolSpec], *, thinking: bool) -> ParsedCompletion:
    body = text.split(END_OF_TURN, 1)[0]
    if thinking and _THINK_CLOSE in body:
        body = body.split(_THINK_CLOSE, 1)[1]
    start = body.find("<tool_call>")
    if start < 0:
        content = body.strip()
        if not content:
            return _error("empty_response")
        return ParsedCompletion(TurnKind.FINAL, content, (), None)
    preamble = body[:start].strip()
    specs = {tool.name: tool for tool in tools}
    calls: list[ToolCall] = []
    position = start
    while True:
        match = _CALL.match(body, position)
        if match is None:
            break
        call, error = _parse_call(match.group(1).strip(), match.group(2), specs, index=len(calls))
        if error:
            return _error(error)
        calls.append(call)
        position = match.end()
    remainder = body[position:]
    if remainder.strip():
        return _error("malformed_tool_call" if "<tool_call>" in remainder else "text_after_tool_call")
    if not calls:
        return _error("malformed_tool_call")
    return ParsedCompletion(TurnKind.TOOL_CALLS, preamble, tuple(calls), None)


def _error(code: str) -> ParsedCompletion:
    return ParsedCompletion(TurnKind.PARSE_ERROR, "", (), code)


def _parse_call(
    name: str,
    body: str,
    specs: dict[str, ToolSpec],
    *,
    index: int,
) -> tuple[ToolCall | None, str | None]:
    spec = specs.get(name)
    if spec is None:
        return None, f"unknown_tool: {name}"
    properties = spec.parameters.get("properties", {})
    arguments: dict[str, Any] = {}
    for match in _PARAM.finditer(body):
        param, raw = match.group(1).strip(), match.group(2)
        if param not in properties:
            return None, f"unknown_parameter: {name}.{param}"
        value, ok = _coerce(raw, properties[param])
        if not ok:
            return None, f"invalid_argument: {name}.{param}"
        arguments[param] = value
    if _PARAM.sub("", body).strip():
        return None, f"malformed_tool_call: {name}"
    missing = [param for param in spec.parameters.get("required", []) if param not in arguments]
    if missing:
        return None, f"missing_required: {name}.{','.join(missing)}"
    return ToolCall(call_id=f"call_{index}", name=name, arguments=arguments), None


def _coerce(raw: str, schema: dict[str, Any]) -> tuple[Any, bool]:
    kind = schema.get("type")
    if kind == "string":
        value: Any = raw
    else:
        try:
            value = json.loads(raw.strip())
        except json.JSONDecodeError:
            return None, False
        expected = {
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "array": list,
            "object": dict,
            "null": type(None),
        }[kind]
        if kind in {"integer", "number"} and isinstance(value, bool):
            return None, False
        if not isinstance(value, expected):
            return None, False
    if "enum" in schema and value not in schema["enum"]:
        return None, False
    return value, True
```

Add to `pyproject.toml`:
```toml
[tool.hatch.build.targets.wheel.force-include]
"src/studyhub_agent/contracts/templates" = "studyhub_agent/contracts/templates"
```

- [ ] **Step 5: Run to verify pass**

Run: `cd studyhub-agent && $PY -m pytest tests/contracts/test_render.py -q`
Expected: all passed. If `test_prefix_property_holds_for_tool_turns` fails, print both strings and fix `_message_dict` (the template must see exactly the OpenAI-style message shape) — do not weaken the test.

- [ ] **Step 6: Commit**

```bash
git add studyhub-agent/src/studyhub_agent/contracts/render.py studyhub-agent/src/studyhub_agent/contracts/templates studyhub-agent/tests/contracts/test_render.py studyhub-agent/pyproject.toml
git commit -m "feat: add single Qwen3.5 chat renderer and tool-call parser"
```

---

### Task 6: Contract hash

**Files:**
- Create: `studyhub-agent/src/studyhub_agent/contracts/fingerprint.py`
- Test: `studyhub-agent/tests/contracts/test_fingerprint.py`

**Interfaces:**
- Consumes: `PromptTemplate` (Task 3), `ToolSpec` (Task 2), `TEMPLATE_SHA256` (Task 5).
- Produces: `TURN_RULE_VERSION = "turn-rule@1"`; `ContractInputs(system_prompt: PromptTemplate, finalize_prompt: PromptTemplate, tools: tuple[ToolSpec, ...], thinking: bool, tokenizer_revision: str, max_context_tokens: int, max_new_tokens: int, template_sha256: str = TEMPLATE_SHA256, turn_rule_version: str = TURN_RULE_VERSION)` frozen dataclass; `contract_hash(inputs: ContractInputs) -> str` returning `"sha256:<64 hex>"`.

- [ ] **Step 1: Write the failing tests**

```python
import dataclasses

import pytest

from studyhub_agent.contracts.fingerprint import ContractInputs, contract_hash
from studyhub_agent.contracts.prompts import DEFAULT_PROMPTS, FINALIZE_PROMPT_KEY, SYSTEM_PROMPT_KEY, PromptTemplate
from studyhub_agent.contracts.tools import ToolSpec


def _tool(name: str) -> ToolSpec:
    return ToolSpec(name=name, version="1.0", description="d", parameters={"type": "object", "properties": {}, "required": [], "additionalProperties": False})


BASE = ContractInputs(
    system_prompt=DEFAULT_PROMPTS.get(SYSTEM_PROMPT_KEY),
    finalize_prompt=DEFAULT_PROMPTS.get(FINALIZE_PROMPT_KEY),
    tools=(_tool("a"), _tool("b")),
    thinking=False,
    tokenizer_revision="qwen3.5-4b@rev1",
    max_context_tokens=16384,
    max_new_tokens=2048,
)


def test_hash_format_and_determinism() -> None:
    value = contract_hash(BASE)
    assert value.startswith("sha256:") and len(value) == len("sha256:") + 64
    assert contract_hash(BASE) == value


def test_tool_order_does_not_matter() -> None:
    assert contract_hash(dataclasses.replace(BASE, tools=(_tool("b"), _tool("a")))) == contract_hash(BASE)


@pytest.mark.parametrize(
    "change",
    [
        {"thinking": True},
        {"tokenizer_revision": "qwen3.5-4b@rev2"},
        {"max_context_tokens": 8192},
        {"max_new_tokens": 1024},
        {"template_sha256": "0" * 64},
        {"turn_rule_version": "turn-rule@2"},
        {"tools": (_tool("a"),)},
        {"system_prompt": PromptTemplate("studyhub.agent.system", "1.1", "新提示")},
        {"finalize_prompt": PromptTemplate("studyhub.agent.finalize", "1.1", "新收尾")},
    ],
)
def test_every_component_changes_the_hash(change) -> None:
    assert contract_hash(dataclasses.replace(BASE, **change)) != contract_hash(BASE)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd studyhub-agent && $PY -m pytest tests/contracts/test_fingerprint.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `contracts/fingerprint.py`**

```python
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from studyhub_agent.contracts.prompts import PromptTemplate
from studyhub_agent.contracts.render import TEMPLATE_SHA256
from studyhub_agent.contracts.tools import ToolSpec

TURN_RULE_VERSION = "turn-rule@1"


@dataclass(frozen=True, slots=True)
class ContractInputs:
    system_prompt: PromptTemplate
    finalize_prompt: PromptTemplate
    tools: tuple[ToolSpec, ...]
    thinking: bool
    tokenizer_revision: str
    max_context_tokens: int
    max_new_tokens: int
    template_sha256: str = TEMPLATE_SHA256
    turn_rule_version: str = TURN_RULE_VERSION


def contract_hash(inputs: ContractInputs) -> str:
    document = {
        "system_prompt": {"key": inputs.system_prompt.key, "text": inputs.system_prompt.text},
        "finalize_prompt": {"key": inputs.finalize_prompt.key, "text": inputs.finalize_prompt.text},
        "tools": sorted((tool.canonical() for tool in inputs.tools), key=lambda item: item["name"]),
        "thinking": inputs.thinking,
        "tokenizer_revision": inputs.tokenizer_revision,
        "max_context_tokens": inputs.max_context_tokens,
        "max_new_tokens": inputs.max_new_tokens,
        "template_sha256": inputs.template_sha256,
        "turn_rule_version": inputs.turn_rule_version,
    }
    payload = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Run to verify pass**

Run: `cd studyhub-agent && $PY -m pytest tests/contracts -q`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add studyhub-agent/src/studyhub_agent/contracts/fingerprint.py studyhub-agent/tests/contracts/test_fingerprint.py
git commit -m "feat: add runtime contract hash"
```

---

### Task 7: Port guardrails

**Files:**
- Create: `studyhub-agent/src/studyhub_agent/guardrails/permissions.py`, `privacy.py`, `web_security.py`
- Test: `studyhub-agent/tests/guardrails/test_permissions.py`, `test_privacy.py`, `test_web_security.py` (+ `tests/guardrails/__init__.py`)

**Interfaces:**
- Consumes: `Principal` (Task 4).
- Produces:
  - `permissions.can_read(principal: Principal, *, material_id: int, access_scope: str, owner_id: str | None) -> bool`
  - `privacy.FORBIDDEN_KEYS: frozenset[str]`, `privacy.redact_text(value: str) -> str`, `privacy.sanitize_output(value: Any) -> Any`
  - `web_security.UnsafeUrlError(ValueError)`, `web_security.WebSecurityPolicy(max_urls_per_call=3, allowed_ports=(None, 80, 443))` with `.validate_url(url: str, *, resolver: Callable[[str], Iterable[str]]) -> str`

- [ ] **Step 1: Write the failing tests**

`tests/guardrails/test_permissions.py`:
```python
import pytest

from studyhub_agent.contracts.episode import Principal
from studyhub_agent.guardrails.permissions import can_read

USER = Principal(principal_id="u-1", purchased_material_ids=frozenset({7}), owned_material_ids=frozenset({9}))


@pytest.mark.parametrize(
    ("material_id", "scope", "owner", "expected"),
    [
        (1, "public", None, True),
        (7, "paid", None, True),
        (8, "paid", None, False),
        (9, "owner", None, True),
        (10, "owner", "u-1", True),
        (11, "owner", "u-2", False),
        (12, "unknown", None, False),
    ],
)
def test_can_read(material_id, scope, owner, expected) -> None:
    assert can_read(USER, material_id=material_id, access_scope=scope, owner_id=owner) is expected


def test_admin_reads_everything() -> None:
    admin = Principal(principal_id="a", is_admin=True)
    assert can_read(admin, material_id=11, access_scope="owner", owner_id="u-2")
```

`tests/guardrails/test_privacy.py`:
```python
from studyhub_agent.guardrails.privacy import sanitize_output


def test_sanitize_removes_forbidden_keys_and_redacts_emails() -> None:
    value = {"title": "联系 a.b@example.com", "email": "x@y.com", "nested": [{"user_id": 3, "ok": "yes"}]}
    assert sanitize_output(value) == {"title": "联系 [redacted-email]", "nested": [{"ok": "yes"}]}


def test_sanitize_returns_new_objects() -> None:
    original = {"a": ["b"]}
    result = sanitize_output(original)
    assert result == original and result is not original and result["a"] is not original["a"]
```

`tests/guardrails/test_web_security.py`:
```python
import pytest

from studyhub_agent.guardrails.web_security import UnsafeUrlError, WebSecurityPolicy

POLICY = WebSecurityPolicy()


def _public(_host: str) -> list[str]:
    return ["93.184.216.34"]


def _private(_host: str) -> list[str]:
    return ["10.0.0.8"]


def test_public_https_url_is_allowed() -> None:
    assert POLICY.validate_url("https://example.com/a", resolver=_public) == "https://example.com/a"


@pytest.mark.parametrize(
    "url",
    ["ftp://example.com", "http://user:pw@example.com", "http://example.com:8080", "http://127.0.0.1/", "https:///nohost"],
)
def test_unsafe_urls_are_rejected(url) -> None:
    with pytest.raises(UnsafeUrlError):
        POLICY.validate_url(url, resolver=_public)


def test_hostname_resolving_to_private_address_is_rejected() -> None:
    with pytest.raises(UnsafeUrlError, match="non-public"):
        POLICY.validate_url("https://intranet.example.com", resolver=_private)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd studyhub-agent && $PY -m pytest tests/guardrails -q`
Expected: FAIL — modules not found.

- [ ] **Step 3: Implement the three modules**

`guardrails/permissions.py`:
```python
from __future__ import annotations

from studyhub_agent.contracts.episode import Principal


def can_read(principal: Principal, *, material_id: int, access_scope: str, owner_id: str | None) -> bool:
    if principal.is_admin:
        return True
    if access_scope in {"public", "free"}:
        return True
    if access_scope == "paid":
        return material_id in principal.purchased_material_ids
    if access_scope == "owner":
        return material_id in principal.owned_material_ids or bool(owner_id and owner_id == principal.principal_id)
    return False
```

`guardrails/privacy.py`:
```python
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

FORBIDDEN_KEYS = frozenset({"email", "phone", "username", "raw_user_id", "user_id", "chat_transcript", "id_card"})
EMAIL_PATTERN = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def redact_text(value: str) -> str:
    return EMAIL_PATTERN.sub("[redacted-email]", value)


def sanitize_output(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        return {
            str(key): sanitize_output(item)
            for key, item in value.items()
            if str(key).strip().lower() not in FORBIDDEN_KEYS
        }
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [sanitize_output(item) for item in value]
    return value
```

`guardrails/web_security.py`:
```python
from __future__ import annotations

import ipaddress
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from urllib.parse import urlsplit

AddressResolver = Callable[[str], Iterable[str]]


class UnsafeUrlError(ValueError):
    """A URL the agent may not fetch."""


def _is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified)


@dataclass(frozen=True, slots=True)
class WebSecurityPolicy:
    max_urls_per_call: int = 3
    allowed_ports: tuple[int | None, ...] = (None, 80, 443)

    def validate_url(self, url: str, *, resolver: AddressResolver) -> str:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"}:
            raise UnsafeUrlError("only http and https URLs are allowed")
        if not parsed.hostname or parsed.username or parsed.password:
            raise UnsafeUrlError("URL must contain a plain hostname")
        if parsed.port not in self.allowed_ports:
            raise UnsafeUrlError("non-standard ports are blocked")
        try:
            addresses = [str(ipaddress.ip_address(parsed.hostname))]
        except ValueError:
            addresses = list(resolver(parsed.hostname))
        if not addresses or not all(_is_public(address) for address in addresses):
            raise UnsafeUrlError("URL resolves to a non-public address")
        return url
```

- [ ] **Step 4: Run to verify pass**

Run: `cd studyhub-agent && $PY -m pytest tests/guardrails -q`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add studyhub-agent/src/studyhub_agent/guardrails studyhub-agent/tests/guardrails
git commit -m "feat: port permission, privacy and SSRF guardrails"
```

---

### Task 8: Tool specs and MCP names

**Files:**
- Create: `studyhub-agent/src/studyhub_agent/tools/specs.py`
- Test: `studyhub-agent/tests/tools/test_specs.py` (+ `tests/tools/__init__.py`)

**Interfaces:**
- Consumes: `ToolSpec` (Task 2).
- Produces: `TOOL_SPECS: tuple[ToolSpec, ...]` (8 specs, names listed in Global Constraints), `TOOLS_BY_NAME: Mapping[str, ToolSpec]`, `POLICY_TOPICS: tuple[str, ...] = ("refund", "copyright", "download", "account", "payout")`, `mcp_name_for(tool_name: str) -> str | None`, `select_tools(names: Sequence[str]) -> tuple[ToolSpec, ...]` (raises `KeyError` listing unknown names).

- [ ] **Step 1: Write the failing tests**

```python
import pytest

from studyhub_agent.tools.specs import TOOL_SPECS, mcp_name_for, select_tools

EXPECTED = {
    "materials_search": "materials.search",
    "materials_get": "materials.get",
    "materials_recommend": "materials.recommend",
    "platform_policy": "platform.policy",
    "materials_read": None,
    "web_extract": None,
    "memory_get": None,
    "memory_update": None,
}


def test_tool_set_and_mcp_names() -> None:
    assert {spec.name: spec.mcp_name for spec in TOOL_SPECS} == EXPECTED
    assert all(mcp_name_for(name) == mcp for name, mcp in EXPECTED.items())


def test_snapshot_capability_is_explicit() -> None:
    assert all(spec.capability == "snapshot" for spec in TOOL_SPECS)


def test_select_tools_preserves_request_order_and_rejects_unknown() -> None:
    assert [spec.name for spec in select_tools(["web_extract", "materials_search"])] == ["web_extract", "materials_search"]
    with pytest.raises(KeyError, match="web_fetch"):
        select_tools(["web_fetch"])
```

- [ ] **Step 2: Run to verify failure**

Run: `cd studyhub-agent && $PY -m pytest tests/tools -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `tools/specs.py`**

```python
from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any

from studyhub_agent.contracts.tools import ToolSpec

POLICY_TOPICS = ("refund", "copyright", "download", "account", "payout")


def _object(properties: dict[str, dict[str, Any]], required: Sequence[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="materials_search",
        version="1.0",
        description="按关键词检索 StudyHub 资料，返回资料元数据（不含正文）。可按学校、课程过滤。",
        parameters=_object(
            {
                "query": {"type": "string", "description": "检索关键词，例如课程名、考试类型"},
                "school": {"type": "string", "description": "可选，学校全称"},
                "course": {"type": "string", "description": "可选，课程名"},
                "limit": {"type": "integer", "description": "返回条数，1-10，默认 5"},
            },
            ["query"],
        ),
        mcp_name="materials.search",
    ),
    ToolSpec(
        name="materials_get",
        version="1.0",
        description="读取一份已检索到的资料的详情：价格、页数、简介、标签。",
        parameters=_object({"material_id": {"type": "integer", "description": "资料 ID"}}, ["material_id"]),
        mcp_name="materials.get",
    ),
    ToolSpec(
        name="materials_recommend",
        version="1.0",
        description="根据学习需求推荐资料，返回资料元数据。",
        parameters=_object(
            {
                "context": {"type": "string", "description": "用户的学习需求描述"},
                "limit": {"type": "integer", "description": "返回条数，1-5，默认 3"},
            },
            ["context"],
        ),
        mcp_name="materials.recommend",
    ),
    ToolSpec(
        name="platform_policy",
        version="1.0",
        description="查询 StudyHub 平台规则原文。",
        parameters=_object(
            {"topic": {"type": "string", "description": "规则主题", "enum": list(POLICY_TOPICS)}},
            ["topic"],
        ),
        mcp_name="platform.policy",
    ),
    ToolSpec(
        name="materials_read",
        version="1.0",
        description="读取已检索到的资料的公开预览页正文。",
        parameters=_object(
            {
                "material_id": {"type": "integer", "description": "资料 ID"},
                "page": {"type": "integer", "description": "预览页码，从 1 开始，默认 1"},
            },
            ["material_id"],
        ),
    ),
    ToolSpec(
        name="web_extract",
        version="1.0",
        description="提取网页正文（只读快照）。一次最多 3 个网址。",
        parameters=_object(
            {"urls": {"type": "array", "description": "要提取的网址列表", "items": {"type": "string"}}},
            ["urls"],
        ),
    ),
    ToolSpec(
        name="memory_get",
        version="1.0",
        description="读取当前用户的学习记忆，例如考试日期、学习目标。",
        parameters=_object(
            {"keys": {"type": "array", "description": "可选，要读取的键；不填返回全部", "items": {"type": "string"}}},
            [],
        ),
    ),
    ToolSpec(
        name="memory_update",
        version="1.0",
        description="写入当前用户的一条学习记忆。不要写入邮箱、电话、证件号等个人信息。",
        parameters=_object(
            {
                "key": {"type": "string", "description": "记忆键，小写英文和下划线"},
                "value": {"type": "string", "description": "记忆内容"},
            },
            ["key", "value"],
        ),
    ),
)

TOOLS_BY_NAME: Mapping[str, ToolSpec] = MappingProxyType({spec.name: spec for spec in TOOL_SPECS})


def mcp_name_for(tool_name: str) -> str | None:
    return TOOLS_BY_NAME[tool_name].mcp_name


def select_tools(names: Sequence[str]) -> tuple[ToolSpec, ...]:
    unknown = [name for name in names if name not in TOOLS_BY_NAME]
    if unknown:
        raise KeyError(f"unknown tools: {', '.join(unknown)}")
    return tuple(TOOLS_BY_NAME[name] for name in names)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd studyhub-agent && $PY -m pytest tests/tools -q`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add studyhub-agent/src/studyhub_agent/tools studyhub-agent/tests/tools
git commit -m "feat: define MCP-aligned tool specs"
```

---

### Task 9: Replay environment with discovery/unlock gating

**Files:**
- Create: `studyhub-agent/src/studyhub_agent/environments/base.py`, `environments/replay/__init__.py`, `environments/replay/snapshot.py`, `environments/replay/index.py`, `environments/replay/handlers.py`, `environments/replay/environment.py`
- Create fixture: `studyhub-agent/tests/fixtures/replay_snapshot.json`
- Test: `studyhub-agent/tests/environments/test_replay_index.py`, `tests/environments/test_replay_environment.py` (+ `tests/environments/__init__.py`)

**Interfaces:**
- Consumes: `EpisodeSpec`, `Principal`, `ToolCall`, `Observation` (Task 4); guardrails (Task 7); `TOOL_SPECS`, `POLICY_TOPICS` (Task 8).
- Produces:
  - `environments.base.Environment` Protocol: `reset(spec: EpisodeSpec) -> None`, `tool_specs() -> tuple[ToolSpec, ...]`, `execute(call: ToolCall) -> Observation`, `trace() -> dict[str, Any]`
  - `environments.base.EnvironmentInfraError(RuntimeError)`
  - `replay.snapshot.ReplaySnapshot` (pydantic frozen) with `materials: tuple[SnapshotMaterial, ...]`, `policies: dict[str, str]`, `web_pages: tuple[SnapshotWebPage, ...]`, `memory: dict[str, dict[str, str]]`, `snapshot_id: str`, `schema_version: Literal["studyhub.replay.v3"]`; `load_snapshot(path: Path) -> ReplaySnapshot`; `snapshot_digest(snapshot) -> str`
  - `replay.index.mixed_tokens(text: str) -> list[str]`, `replay.index.Bm25Index(rows: Sequence[SnapshotMaterial])` with `.search(query: str, *, limit: int) -> list[tuple[float, SnapshotMaterial]]`
  - `replay.environment.ReplayEnvironment(snapshot: ReplaySnapshot)` implementing `Environment`

- [ ] **Step 1: Write the fixture snapshot**

`tests/fixtures/replay_snapshot.json`:
```json
{
  "schema_version": "studyhub.replay.v3",
  "snapshot_id": "fixture-2026-09-25",
  "materials": [
    {"material_id": 101, "title": "高等数学（上）期末复习提纲", "course": "高等数学", "school": "电子科技大学", "summary": "极限、导数、积分三大块的题型总结", "tags": ["期末", "提纲"], "access_scope": "public", "owner_id": null, "price_cents": 0, "downloads": 320, "preview_pages": ["第一章 极限：夹逼准则与两个重要极限。", "第二章 导数：链式法则与隐函数求导。"], "unlock_after": []},
    {"material_id": 102, "title": "高等数学历年期末真题（含解析）", "course": "高等数学", "school": "电子科技大学", "summary": "2021-2025 年期末真题及详细解析", "tags": ["真题", "期末"], "access_scope": "paid", "owner_id": null, "price_cents": 990, "downloads": 510, "preview_pages": ["2025 年期末第一题：求极限 lim(x→0) sin x / x。"], "unlock_after": []},
    {"material_id": 103, "title": "线性代数重点笔记", "course": "线性代数", "school": "四川大学", "summary": "矩阵、行列式、特征值笔记", "tags": ["笔记"], "access_scope": "public", "owner_id": null, "price_cents": 0, "downloads": 150, "preview_pages": ["特征值：det(A-λI)=0 的根。"], "unlock_after": []},
    {"material_id": 104, "title": "线性代数习题答案（进阶）", "course": "线性代数", "school": "四川大学", "summary": "配套进阶习题答案，需先阅读重点笔记", "tags": ["习题"], "access_scope": "public", "owner_id": null, "price_cents": 0, "downloads": 90, "preview_pages": ["习题 3.2 答案：特征值为 1 和 3。"], "unlock_after": [103]},
    {"material_id": 105, "title": "私人草稿：概率论", "course": "概率论", "school": "电子科技大学", "summary": "作者私人草稿", "tags": ["草稿"], "access_scope": "owner", "owner_id": "u-2002", "price_cents": 0, "downloads": 0, "preview_pages": ["仅作者可见。"], "unlock_after": []}
  ],
  "policies": {
    "refund": "购买后 24 小时内未下载可申请退款。",
    "copyright": "上传资料须为本人原创或已获授权。",
    "download": "免费资料每日可下载 20 次。",
    "account": "每个手机号只能注册一个账号。",
    "payout": "创作者收益在订单完成 7 天后可提现。"
  },
  "web_pages": [
    {"url": "https://www.example.edu.cn/exam-schedule", "title": "2026 秋季期末考试安排", "text": "高等数学期末考试时间为 2027 年 1 月 8 日。"}
  ],
  "memory": {"u-1001": {"exam_date": "2027-01-08", "goal": "高数 85 分"}}
}
```

- [ ] **Step 2: Write the failing tests**

`tests/environments/test_replay_index.py`:
```python
from pathlib import Path

from studyhub_agent.environments.replay.index import Bm25Index, mixed_tokens
from studyhub_agent.environments.replay.snapshot import load_snapshot

SNAPSHOT = load_snapshot(Path(__file__).parent.parent / "fixtures" / "replay_snapshot.json")


def test_mixed_tokens_emits_chinese_unigrams_bigrams_and_latin_words() -> None:
    assert mixed_tokens("高数 Final2025") == ["final2025", "高", "数", "高数"]


def test_search_ranks_relevant_material_first_and_is_deterministic() -> None:
    index = Bm25Index(SNAPSHOT.materials)
    first = index.search("高等数学 期末 真题", limit=3)
    assert first[0][1].material_id == 102
    assert index.search("高等数学 期末 真题", limit=3) == first


def test_empty_query_returns_nothing() -> None:
    assert Bm25Index(SNAPSHOT.materials).search("   ", limit=5) == []
```

`tests/environments/test_replay_environment.py`:
```python
from pathlib import Path

import pytest

from studyhub_agent.contracts.episode import EpisodeSpec, Principal, ToolCall
from studyhub_agent.environments.replay.environment import ReplayEnvironment
from studyhub_agent.environments.replay.snapshot import load_snapshot

SNAPSHOT = load_snapshot(Path(__file__).parent.parent / "fixtures" / "replay_snapshot.json")


def _env(principal: Principal | None = None) -> ReplayEnvironment:
    env = ReplayEnvironment(SNAPSHOT)
    env.reset(
        EpisodeSpec(
            episode_id="ep",
            task_id="t",
            user_message="q",
            principal=principal or Principal(principal_id="u-1001"),
            tool_names=("materials_search",),
        )
    )
    return env


def _call(name: str, **arguments) -> ToolCall:
    return ToolCall(call_id="c1", name=name, arguments=arguments)


def test_read_requires_discovery_first() -> None:
    env = _env()
    blocked = env.execute(_call("materials_read", material_id=101))
    assert blocked.ok is False and blocked.error_code == "material_not_discovered"
    env.execute(_call("materials_search", query="高等数学 提纲"))
    read = env.execute(_call("materials_read", material_id=101, page=2))
    assert read.ok and "链式法则" in read.payload["text"]


def test_unlock_after_requires_reading_prerequisite() -> None:
    env = _env()
    env.execute(_call("materials_search", query="线性代数"))
    assert env.execute(_call("materials_read", material_id=104)).error_code == "material_locked"
    env.execute(_call("materials_read", material_id=103))
    assert env.execute(_call("materials_read", material_id=104)).ok


def test_owner_scoped_material_is_invisible_to_others() -> None:
    env = _env()
    result = env.execute(_call("materials_search", query="概率论 草稿"))
    assert all(item["material_id"] != 105 for item in result.payload["results"])
    owner_env = _env(Principal(principal_id="u-2002"))
    result = owner_env.execute(_call("materials_search", query="概率论 草稿"))
    assert any(item["material_id"] == 105 for item in result.payload["results"])


def test_search_filters_and_limit_bounds() -> None:
    env = _env()
    result = env.execute(_call("materials_search", query="笔记 习题", school="四川大学", limit=50))
    assert {item["school"] for item in result.payload["results"]} == {"四川大学"}
    assert len(result.payload["results"]) <= 10


def test_get_returns_metadata_without_preview_text() -> None:
    env = _env()
    env.execute(_call("materials_search", query="真题"))
    detail = env.execute(_call("materials_get", material_id=102))
    assert detail.ok and detail.payload["price_cents"] == 990 and detail.payload["preview_page_count"] == 1
    assert "preview_pages" not in detail.payload


def test_read_page_out_of_range() -> None:
    env = _env()
    env.execute(_call("materials_search", query="提纲"))
    assert env.execute(_call("materials_read", material_id=101, page=9)).error_code == "page_out_of_range"


def test_policy_and_web_extract() -> None:
    env = _env()
    assert "24 小时" in env.execute(_call("platform_policy", topic="refund")).payload["text"]
    pages = env.execute(_call("web_extract", urls=["https://www.example.edu.cn/exam-schedule", "https://unknown.example.com"]))
    assert pages.ok
    assert pages.payload["pages"][0]["text"].startswith("高等数学期末")
    assert pages.payload["pages"][1]["error"] == "not_in_snapshot"


def test_web_extract_blocks_unsafe_and_too_many_urls() -> None:
    env = _env()
    assert env.execute(_call("web_extract", urls=["http://127.0.0.1/admin"])).payload["pages"][0]["error"] == "unsafe_url"
    assert env.execute(_call("web_extract", urls=["https://a.cn"] * 4)).error_code == "too_many_urls"


def test_memory_update_is_per_episode_and_rejects_personal_keys() -> None:
    env = _env()
    assert env.execute(_call("memory_get")).payload["memory"] == {"exam_date": "2027-01-08", "goal": "高数 85 分"}
    assert env.execute(_call("memory_update", key="email", value="a@b.com")).error_code == "forbidden_memory_key"
    assert env.execute(_call("memory_update", key="weak_topic", value="积分")).ok
    assert env.execute(_call("memory_get", keys=["weak_topic"])).payload["memory"] == {"weak_topic": "积分"}
    fresh = _env()
    assert "weak_topic" not in fresh.execute(_call("memory_get")).payload["memory"]
    assert "weak_topic" not in SNAPSHOT.memory["u-1001"]


def test_trace_records_discovery_reads_and_calls() -> None:
    env = _env()
    env.execute(_call("materials_search", query="提纲"))
    env.execute(_call("materials_read", material_id=101))
    trace = env.trace()
    assert 101 in trace["discovered_material_ids"] and trace["read_material_ids"] == [101]
    assert trace["snapshot_digest"].startswith("sha256:")


def test_unknown_tool_is_an_error_observation() -> None:
    assert _env().execute(_call("web_fetch", url="x")).error_code == "unknown_tool"


def test_execute_before_reset_is_a_programming_error() -> None:
    with pytest.raises(RuntimeError, match="reset"):
        ReplayEnvironment(SNAPSHOT).execute(_call("memory_get"))
```

- [ ] **Step 3: Run to verify failure**

Run: `cd studyhub-agent && $PY -m pytest tests/environments -q`
Expected: FAIL — modules not found.

- [ ] **Step 4: Implement**

`environments/base.py`:
```python
from __future__ import annotations

from typing import Any, Protocol

from studyhub_agent.contracts.episode import EpisodeSpec, Observation, ToolCall
from studyhub_agent.contracts.tools import ToolSpec


class EnvironmentInfraError(RuntimeError):
    """The environment's backing service failed; not the model's fault."""


class Environment(Protocol):
    def reset(self, spec: EpisodeSpec) -> None: ...

    def tool_specs(self) -> tuple[ToolSpec, ...]: ...

    def execute(self, call: ToolCall) -> Observation: ...

    def trace(self) -> dict[str, Any]: ...
```

`environments/replay/snapshot.py`:
```python
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SnapshotMaterial(_Frozen):
    material_id: int
    title: str
    course: str
    school: str
    summary: str
    tags: tuple[str, ...] = ()
    access_scope: Literal["public", "free", "paid", "owner"]
    owner_id: str | None = None
    price_cents: int = Field(ge=0)
    downloads: int = Field(default=0, ge=0)
    preview_pages: tuple[str, ...]
    unlock_after: tuple[int, ...] = ()


class SnapshotWebPage(_Frozen):
    url: str
    title: str
    text: str


class ReplaySnapshot(_Frozen):
    schema_version: Literal["studyhub.replay.v3"]
    snapshot_id: str
    materials: tuple[SnapshotMaterial, ...]
    policies: dict[str, str]
    web_pages: tuple[SnapshotWebPage, ...] = ()
    memory: dict[str, dict[str, str]] = Field(default_factory=dict)


def load_snapshot(path: Path) -> ReplaySnapshot:
    return ReplaySnapshot.model_validate_json(path.read_text(encoding="utf-8"))


def snapshot_digest(snapshot: ReplaySnapshot) -> str:
    payload = json.dumps(snapshot.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

`environments/replay/index.py`:
```python
from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence

from studyhub_agent.environments.replay.snapshot import SnapshotMaterial

_LATIN_OR_NUMBER = re.compile(r"[a-z0-9]+")
_CHINESE_RUN = re.compile(r"[㐀-鿿]+")
_K1 = 1.5
_B = 0.75


def mixed_tokens(text: str) -> list[str]:
    normalized = text.casefold()
    tokens = _LATIN_OR_NUMBER.findall(normalized)
    for run in _CHINESE_RUN.findall(normalized):
        tokens.extend(run)
        tokens.extend(run[index : index + 2] for index in range(max(0, len(run) - 1)))
    return tokens


class Bm25Index:
    """Deterministic BM25 over material metadata (title, course, school, summary, tags)."""

    def __init__(self, rows: Sequence[SnapshotMaterial]) -> None:
        self._rows = tuple(rows)
        self._frequencies = tuple(Counter(mixed_tokens(_document_text(row))) for row in self._rows)
        self._lengths = tuple(sum(freq.values()) for freq in self._frequencies)
        total = len(self._rows)
        self._average = sum(self._lengths) / total if total else 0.0
        document_frequency: Counter[str] = Counter()
        for frequencies in self._frequencies:
            document_frequency.update(frequencies.keys())
        self._idf = {term: math.log(1 + (total - count + 0.5) / (count + 0.5)) for term, count in document_frequency.items()}

    def search(self, query: str, *, limit: int) -> list[tuple[float, SnapshotMaterial]]:
        terms = mixed_tokens(query)
        if not terms or not self._rows:
            return []
        scored: list[tuple[float, int, SnapshotMaterial]] = []
        for row, frequencies, length in zip(self._rows, self._frequencies, self._lengths, strict=True):
            score = 0.0
            for term in terms:
                frequency = frequencies.get(term, 0)
                if frequency:
                    denominator = frequency + _K1 * (1 - _B + _B * length / max(self._average, 1e-9))
                    score += self._idf.get(term, 0.0) * frequency * (_K1 + 1) / denominator
            if score > 0:
                scored.append((round(score, 6), row.material_id, row))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [(score, row) for score, _, row in scored[:limit]]


def _document_text(row: SnapshotMaterial) -> str:
    return " ".join([row.title, row.course, row.school, row.summary, *row.tags])
```

`environments/replay/handlers.py` (pure functions over an explicit state; each returns `(ok, payload, error_code)` and a new state — no mutation):
```python
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any

from studyhub_agent.contracts.episode import Principal
from studyhub_agent.environments.replay.index import Bm25Index
from studyhub_agent.environments.replay.snapshot import ReplaySnapshot, SnapshotMaterial
from studyhub_agent.guardrails.permissions import can_read
from studyhub_agent.guardrails.privacy import FORBIDDEN_KEYS, sanitize_output
from studyhub_agent.guardrails.web_security import UnsafeUrlError, WebSecurityPolicy

SNAPSHOT_HOST_ADDRESS = "93.184.216.34"
_WEB_POLICY = WebSecurityPolicy()


@dataclass(frozen=True, slots=True)
class ReplayState:
    principal: Principal
    discovered: frozenset[int] = frozenset()
    read: tuple[int, ...] = ()
    memory: Mapping[str, str] = MappingProxyType({})


Result = tuple[bool, dict[str, Any], str | None, ReplayState]
Handler = Callable[["ReplayContext", ReplayState, dict[str, Any]], Result]


@dataclass(frozen=True, slots=True)
class ReplayContext:
    snapshot: ReplaySnapshot
    index: Bm25Index
    materials: Mapping[int, SnapshotMaterial]
    pages: Mapping[str, Any]


def _visible(context: ReplayContext, state: ReplayState, material: SnapshotMaterial) -> bool:
    return can_read(state.principal, material_id=material.material_id, access_scope=material.access_scope, owner_id=material.owner_id)


def _summary(material: SnapshotMaterial) -> dict[str, Any]:
    return {
        "material_id": material.material_id,
        "title": material.title,
        "course": material.course,
        "school": material.school,
        "price_cents": material.price_cents,
        "tags": list(material.tags),
    }


def _error(state: ReplayState, code: str, **details: Any) -> Result:
    return False, {"error": code, **details}, code, state


def _clamp(value: Any, *, default: int, upper: int) -> int:
    return max(1, min(int(value if value is not None else default), upper))


def _search_rows(context: ReplayContext, state: ReplayState, query: str, limit: int, **filters: str | None) -> list[SnapshotMaterial]:
    hits = context.index.search(query, limit=len(context.materials))
    rows = [row for _, row in hits if _visible(context, state, row)]
    for field, expected in filters.items():
        if expected:
            rows = [row for row in rows if getattr(row, field) == expected]
    return rows[:limit]


def materials_search(context: ReplayContext, state: ReplayState, args: dict[str, Any]) -> Result:
    rows = _search_rows(context, state, args["query"], _clamp(args.get("limit"), default=5, upper=10), school=args.get("school"), course=args.get("course"))
    new_state = replace(state, discovered=state.discovered | {row.material_id for row in rows})
    return True, {"results": [_summary(row) for row in rows]}, None, new_state


def materials_recommend(context: ReplayContext, state: ReplayState, args: dict[str, Any]) -> Result:
    candidates = _search_rows(context, state, args["context"], len(context.materials))
    rows = sorted(candidates, key=lambda row: (-row.downloads, row.material_id))[: _clamp(args.get("limit"), default=3, upper=5)]
    new_state = replace(state, discovered=state.discovered | {row.material_id for row in rows})
    return True, {"results": [_summary(row) for row in rows]}, None, new_state


def _discovered_material(context: ReplayContext, state: ReplayState, material_id: int) -> SnapshotMaterial | str:
    material = context.materials.get(material_id)
    if material is None or not _visible(context, state, material):
        return "material_not_found"
    if material_id not in state.discovered:
        return "material_not_discovered"
    return material


def materials_get(context: ReplayContext, state: ReplayState, args: dict[str, Any]) -> Result:
    material = _discovered_material(context, state, args["material_id"])
    if isinstance(material, str):
        return _error(state, material, material_id=args["material_id"])
    payload = {**_summary(material), "summary": material.summary, "preview_page_count": len(material.preview_pages), "downloads": material.downloads}
    return True, payload, None, state


def materials_read(context: ReplayContext, state: ReplayState, args: dict[str, Any]) -> Result:
    material = _discovered_material(context, state, args["material_id"])
    if isinstance(material, str):
        return _error(state, material, material_id=args["material_id"])
    if not set(material.unlock_after) <= set(state.read):
        return _error(state, "material_locked", material_id=material.material_id, read_first=list(material.unlock_after))
    page = int(args.get("page") or 1)
    if not 1 <= page <= len(material.preview_pages):
        return _error(state, "page_out_of_range", material_id=material.material_id, page_count=len(material.preview_pages))
    read = state.read if material.material_id in state.read else (*state.read, material.material_id)
    payload = {"material_id": material.material_id, "page": page, "text": material.preview_pages[page - 1], "citation": f"[{material.material_id}:{page}]"}
    return True, payload, None, replace(state, read=read)


def platform_policy(context: ReplayContext, state: ReplayState, args: dict[str, Any]) -> Result:
    text = context.snapshot.policies.get(args["topic"])
    if text is None:
        return _error(state, "policy_not_found", topic=args["topic"])
    return True, {"topic": args["topic"], "text": text}, None, state


def web_extract(context: ReplayContext, state: ReplayState, args: dict[str, Any]) -> Result:
    urls = list(args["urls"])
    if len(urls) > _WEB_POLICY.max_urls_per_call:
        return _error(state, "too_many_urls", limit=_WEB_POLICY.max_urls_per_call)
    pages = []
    for url in urls:
        try:
            _WEB_POLICY.validate_url(url, resolver=lambda _host: [SNAPSHOT_HOST_ADDRESS])
        except UnsafeUrlError:
            pages.append({"url": url, "error": "unsafe_url"})
            continue
        page = context.pages.get(url)
        pages.append({"url": url, "title": page.title, "text": page.text} if page else {"url": url, "error": "not_in_snapshot"})
    return True, {"pages": pages}, None, state


def memory_get(context: ReplayContext, state: ReplayState, args: dict[str, Any]) -> Result:
    keys = args.get("keys")
    memory = dict(state.memory) if not keys else {key: state.memory[key] for key in keys if key in state.memory}
    return True, {"memory": memory}, None, state


def memory_update(context: ReplayContext, state: ReplayState, args: dict[str, Any]) -> Result:
    key = str(args["key"]).strip().lower()
    if key in FORBIDDEN_KEYS or not key.replace("_", "").isalnum():
        return _error(state, "forbidden_memory_key", key=key)
    value = sanitize_output(str(args["value"]))
    return True, {"key": key, "stored": True}, None, replace(state, memory=MappingProxyType({**state.memory, key: value}))


HANDLERS: Mapping[str, Handler] = MappingProxyType(
    {
        "materials_search": materials_search,
        "materials_get": materials_get,
        "materials_recommend": materials_recommend,
        "materials_read": materials_read,
        "platform_policy": platform_policy,
        "web_extract": web_extract,
        "memory_get": memory_get,
        "memory_update": memory_update,
    }
)
```

`environments/replay/environment.py`:
```python
from __future__ import annotations

from types import MappingProxyType
from typing import Any

from studyhub_agent.contracts.episode import EpisodeSpec, Observation, ToolCall
from studyhub_agent.contracts.tools import ToolSpec
from studyhub_agent.environments.replay.handlers import HANDLERS, ReplayContext, ReplayState
from studyhub_agent.environments.replay.index import Bm25Index
from studyhub_agent.environments.replay.snapshot import ReplaySnapshot, snapshot_digest
from studyhub_agent.guardrails.privacy import sanitize_output
from studyhub_agent.tools.specs import TOOL_SPECS


class ReplayEnvironment:
    """Deterministic, gated replay of a frozen StudyHub snapshot."""

    def __init__(self, snapshot: ReplaySnapshot) -> None:
        self._context = ReplayContext(
            snapshot=snapshot,
            index=Bm25Index(snapshot.materials),
            materials=MappingProxyType({row.material_id: row for row in snapshot.materials}),
            pages=MappingProxyType({page.url: page for page in snapshot.web_pages}),
        )
        self._digest = snapshot_digest(snapshot)
        self._state: ReplayState | None = None
        self._calls: tuple[str, ...] = ()

    def reset(self, spec: EpisodeSpec) -> None:
        memory = self._context.snapshot.memory.get(spec.principal.principal_id, {})
        self._state = ReplayState(principal=spec.principal, memory=MappingProxyType(dict(memory)))
        self._calls = ()

    def tool_specs(self) -> tuple[ToolSpec, ...]:
        return TOOL_SPECS

    def execute(self, call: ToolCall) -> Observation:
        if self._state is None:
            raise RuntimeError("ReplayEnvironment.execute called before reset")
        self._calls = (*self._calls, call.name)
        handler = HANDLERS.get(call.name)
        if handler is None:
            return Observation(call_id=call.call_id, name=call.name, ok=False, payload={"error": "unknown_tool"}, error_code="unknown_tool")
        ok, payload, error_code, self._state = handler(self._context, self._state, dict(call.arguments))
        return Observation(call_id=call.call_id, name=call.name, ok=ok, payload=sanitize_output(payload), error_code=error_code)

    def trace(self) -> dict[str, Any]:
        state = self._state
        return {
            "snapshot_id": self._context.snapshot.snapshot_id,
            "snapshot_digest": self._digest,
            "discovered_material_ids": sorted(state.discovered) if state else [],
            "read_material_ids": list(state.read) if state else [],
            "tool_calls": list(self._calls),
        }
```

`environments/replay/__init__.py`:
```python
from studyhub_agent.environments.replay.environment import ReplayEnvironment
from studyhub_agent.environments.replay.snapshot import ReplaySnapshot, load_snapshot

__all__ = ["ReplayEnvironment", "ReplaySnapshot", "load_snapshot"]
```

- [ ] **Step 5: Run to verify pass**

Run: `cd studyhub-agent && $PY -m pytest tests/environments -q && lint-imports --config .importlinter`
Expected: all passed; contracts kept.

- [ ] **Step 6: Commit**

```bash
git add studyhub-agent/src/studyhub_agent/environments studyhub-agent/tests/environments studyhub-agent/tests/fixtures/replay_snapshot.json
git commit -m "feat: add gated replay environment with MCP-aligned tools"
```

---

### Task 10: EpisodeRunner

**Files:**
- Create: `studyhub-agent/src/studyhub_agent/runtime/policy.py`, `runtime/runner.py`
- Test: `studyhub-agent/tests/runtime/test_runner.py`, `tests/runtime/fakes.py` (+ `tests/runtime/__init__.py`)

**Interfaces:**
- Consumes: Tasks 3–9.
- Produces:
  - `runtime.policy.PolicyClient` Protocol: `step(messages: Sequence[Message], tools: Sequence[ToolSpec], *, thinking: bool, sampling: Sampling, max_new_tokens: int) -> AssistantTurn`
  - `runtime.policy.PolicyInfraError(RuntimeError)`
  - `runtime.runner.TokenCounter = Callable[[Sequence[Message], Sequence[ToolSpec], bool], int]`
  - `runtime.runner.EpisodeRunner(*, prompts: PromptRegistry, tokenizer_revision: str, count_tokens: TokenCounter)` with `.run(spec: EpisodeSpec, environment: Environment, policy: PolicyClient) -> Episode` and `.contract_for(spec: EpisodeSpec, tools: Sequence[ToolSpec]) -> str`
  - Runtime feedback messages use `Message(role="tool", name="runtime_feedback", content=<json>)`.

- [ ] **Step 1: Write the test fakes**

`tests/runtime/fakes.py`:
```python
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from studyhub_agent.contracts.episode import AssistantTurn, Message, Sampling, ToolCall, TurnKind
from studyhub_agent.contracts.tools import ToolSpec
from studyhub_agent.runtime.policy import PolicyInfraError


def tool_turn(*calls: tuple[str, dict], preamble: str = "") -> AssistantTurn:
    tool_calls = tuple(ToolCall(call_id=f"call_{i}", name=name, arguments=args) for i, (name, args) in enumerate(calls))
    return AssistantTurn(kind=TurnKind.TOOL_CALLS, content=preamble, tool_calls=tool_calls, raw_text="<tool>", canonical_text="<tool>")


def final_turn(text: str) -> AssistantTurn:
    return AssistantTurn(kind=TurnKind.FINAL, content=text, raw_text=text, canonical_text=text)


def parse_error_turn(code: str = "malformed_tool_call") -> AssistantTurn:
    return AssistantTurn(kind=TurnKind.PARSE_ERROR, raw_text="<bad", canonical_text="<bad", parse_error=code)


@dataclass
class ScriptedPolicy:
    turns: list[AssistantTurn | Exception]
    seen: list[tuple[Message, ...]] = field(default_factory=list)

    def step(self, messages: Sequence[Message], tools: Sequence[ToolSpec], *, thinking: bool, sampling: Sampling, max_new_tokens: int) -> AssistantTurn:
        self.seen.append(tuple(messages))
        item = self.turns.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def infra_failure() -> PolicyInfraError:
    return PolicyInfraError("sglang connection refused")


def count_chars(messages: Sequence[Message], tools: Sequence[ToolSpec], thinking: bool) -> int:
    return sum(len(message.content) for message in messages)
```

- [ ] **Step 2: Write the failing tests**

`tests/runtime/test_runner.py`:
```python
import json
from pathlib import Path

from studyhub_agent.contracts.episode import Budget, EpisodeSpec, FailureOwner, Principal, Termination, TurnKind
from studyhub_agent.contracts.prompts import DEFAULT_PROMPTS
from studyhub_agent.environments.replay import ReplayEnvironment, load_snapshot
from studyhub_agent.runtime.runner import EpisodeRunner
from tests.runtime.fakes import ScriptedPolicy, count_chars, final_turn, infra_failure, parse_error_turn, tool_turn

SNAPSHOT = load_snapshot(Path(__file__).parent.parent / "fixtures" / "replay_snapshot.json")
RUNNER = EpisodeRunner(prompts=DEFAULT_PROMPTS, tokenizer_revision="test-rev", count_tokens=count_chars)
TOOLS = ("materials_search", "materials_read", "memory_update")


def _spec(**overrides) -> EpisodeSpec:
    base = {"episode_id": "ep-1", "task_id": "t-1", "user_message": "高数期末复习看什么？", "principal": Principal(principal_id="u-1001"), "tool_names": TOOLS}
    return EpisodeSpec(**{**base, **overrides})


def _run(spec, turns):
    policy = ScriptedPolicy(list(turns))
    return RUNNER.run(spec, ReplayEnvironment(SNAPSHOT), policy), policy


def test_search_read_answer_happy_path() -> None:
    episode, policy = _run(
        _spec(),
        [
            tool_turn(("materials_search", {"query": "高等数学 提纲"})),
            tool_turn(("materials_read", {"material_id": 101})),
            final_turn("先看提纲第一章 [101:1]。"),
        ],
    )
    assert episode.termination is Termination.FINAL_ANSWER
    assert episode.failure_owner is FailureOwner.NONE
    assert episode.final_answer == "先看提纲第一章 [101:1]。"
    assert [obs.ok for obs in episode.observations] == [True, True]
    assert episode.turns[1].tool_calls[0].call_id == "t1_c0"
    tool_message = episode.messages[4]
    assert tool_message.role == "tool" and tool_message.tool_call_id == "t0_c0"
    assert json.loads(tool_message.content)["results"][0]["material_id"] == 101
    assert episode.environment_trace["read_material_ids"] == [101]
    assert episode.contract_hash == RUNNER.contract_for(episode.spec, episode_tools())


def episode_tools():
    from studyhub_agent.tools.specs import select_tools

    return select_tools(TOOLS)


def test_parse_error_is_fed_back_then_budget_ends_episode() -> None:
    episode, policy = _run(_spec(budget=Budget(max_parse_errors=1)), [parse_error_turn(), parse_error_turn()])
    assert episode.termination is Termination.PARSE_ERROR_BUDGET
    assert episode.failure_owner is FailureOwner.MODEL
    feedback = policy.seen[1][-1]
    assert feedback.role == "tool" and feedback.name == "runtime_feedback"
    assert json.loads(feedback.content)["error"] == "malformed_tool_call"


def test_max_turns_injects_finalize_prompt_on_last_turn() -> None:
    episode, policy = _run(
        _spec(budget=Budget(max_turns=2)),
        [tool_turn(("materials_search", {"query": "高数"})), tool_turn(("materials_search", {"query": "高数"}))],
    )
    assert episode.termination is Termination.MAX_TURNS
    last_prompt = policy.seen[-1][-1]
    assert last_prompt.name == "runtime_feedback" and "最后一轮" in last_prompt.content


def test_tool_budget_stops_before_executing() -> None:
    episode, _ = _run(
        _spec(budget=Budget(max_tool_calls=1)),
        [tool_turn(("materials_search", {"query": "a"}), ("materials_search", {"query": "b"}))],
    )
    assert episode.termination is Termination.TOOL_BUDGET
    assert episode.observations == ()


def test_turn_with_one_invalid_call_executes_nothing() -> None:
    episode, _ = _run(_spec(), [parse_error_turn("invalid_argument: materials_read.material_id"), final_turn("完成")])
    assert episode.observations == ()
    assert episode.turns[0].kind is TurnKind.PARSE_ERROR
    assert episode.termination is Termination.FINAL_ANSWER


def test_infra_error_is_explicit_not_raised() -> None:
    episode, _ = _run(_spec(), [infra_failure()])
    assert episode.termination is Termination.INFRA_ERROR
    assert episode.failure_owner is FailureOwner.INFRA
    assert "connection refused" in (episode.error_detail or "")


def test_environment_exception_ends_episode_as_env_error() -> None:
    class ExplodingEnvironment(ReplayEnvironment):
        def execute(self, call):
            raise KeyError("snapshot corrupted")

    policy = ScriptedPolicy([tool_turn(("materials_search", {"query": "a"}))])
    episode = RUNNER.run(_spec(), ExplodingEnvironment(SNAPSHOT), policy)
    assert episode.termination is Termination.ENV_ERROR
    assert episode.failure_owner is FailureOwner.ENV


def test_context_budget_checked_before_each_step() -> None:
    episode, policy = _run(_spec(user_message="长" * 200, budget=Budget(max_context_tokens=150, max_new_tokens=10)), [])
    assert episode.termination is Termination.CONTEXT_BUDGET
    assert policy.seen == []


def test_unknown_tool_name_in_spec_is_a_configuration_error() -> None:
    import pytest

    with pytest.raises(KeyError, match="web_fetch"):
        _run(_spec(tool_names=("web_fetch",)), [])


def test_contract_hash_depends_on_thinking() -> None:
    tools = episode_tools()
    assert RUNNER.contract_for(_spec(), tools) != RUNNER.contract_for(_spec(thinking=True), tools)
```

- [ ] **Step 3: Run to verify failure**

Run: `cd studyhub-agent && $PY -m pytest tests/runtime/test_runner.py -q`
Expected: FAIL — modules not found.

- [ ] **Step 4: Implement**

`runtime/policy.py`:
```python
from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from studyhub_agent.contracts.episode import AssistantTurn, Message, Sampling
from studyhub_agent.contracts.tools import ToolSpec


class PolicyInfraError(RuntimeError):
    """The model server failed (timeout, connection, 5xx); the episode is not the model's fault."""


class PolicyClient(Protocol):
    def step(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec],
        *,
        thinking: bool,
        sampling: Sampling,
        max_new_tokens: int,
    ) -> AssistantTurn: ...
```

`runtime/runner.py`:
```python
from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from studyhub_agent.contracts.episode import (
    AssistantTurn,
    Episode,
    EpisodeSpec,
    FailureOwner,
    Message,
    Observation,
    Termination,
    ToolCall,
    TurnKind,
)
from studyhub_agent.contracts.fingerprint import ContractInputs, contract_hash
from studyhub_agent.contracts.prompts import PromptRegistry
from studyhub_agent.contracts.tools import ToolSpec
from studyhub_agent.environments.base import Environment
from studyhub_agent.runtime.policy import PolicyClient, PolicyInfraError
from studyhub_agent.tools.specs import select_tools

TokenCounter = Callable[[Sequence[Message], Sequence[ToolSpec], bool], int]


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _feedback(payload: dict) -> Message:
    return Message(role="tool", name="runtime_feedback", content=_json(payload))


@dataclass
class _Progress:
    messages: list[Message]
    turns: list[AssistantTurn] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)
    tool_calls_used: int = 0
    parse_errors: int = 0


class EpisodeRunner:
    """The one agent loop shared by data generation, RL rollouts and evaluation."""

    def __init__(self, *, prompts: PromptRegistry, tokenizer_revision: str, count_tokens: TokenCounter) -> None:
        self._prompts = prompts
        self._tokenizer_revision = tokenizer_revision
        self._count_tokens = count_tokens

    def contract_for(self, spec: EpisodeSpec, tools: Sequence[ToolSpec]) -> str:
        return contract_hash(
            ContractInputs(
                system_prompt=self._prompts.get(spec.system_prompt),
                finalize_prompt=self._prompts.get(spec.finalize_prompt),
                tools=tuple(tools),
                thinking=spec.thinking,
                tokenizer_revision=self._tokenizer_revision,
                max_context_tokens=spec.budget.max_context_tokens,
                max_new_tokens=spec.budget.max_new_tokens,
            )
        )

    def run(self, spec: EpisodeSpec, environment: Environment, policy: PolicyClient) -> Episode:
        tools = select_tools(spec.tool_names)
        contract = self.contract_for(spec, tools)
        environment.reset(spec)
        progress = _Progress(
            messages=[
                Message(role="system", content=self._prompts.get(spec.system_prompt).text),
                Message(role="user", content=spec.user_message),
            ]
        )
        outcome = self._loop(spec, environment, policy, tools, progress)
        termination, owner, final_answer, detail = outcome
        return Episode(
            spec=spec,
            contract_hash=contract,
            messages=tuple(progress.messages),
            turns=tuple(progress.turns),
            observations=tuple(progress.observations),
            termination=termination,
            failure_owner=owner,
            final_answer=final_answer,
            error_detail=detail,
            environment_trace=environment.trace(),
        )

    def _loop(
        self,
        spec: EpisodeSpec,
        environment: Environment,
        policy: PolicyClient,
        tools: tuple[ToolSpec, ...],
        progress: _Progress,
    ) -> tuple[Termination, FailureOwner, str | None, str | None]:
        budget = spec.budget
        for turn_index in range(budget.max_turns):
            if turn_index == budget.max_turns - 1 and turn_index > 0:
                progress.messages.append(Message(role="tool", name="runtime_feedback", content=self._prompts.get(spec.finalize_prompt).text))
            if self._count_tokens(progress.messages, tools, spec.thinking) > budget.max_context_tokens - budget.max_new_tokens:
                return Termination.CONTEXT_BUDGET, FailureOwner.MODEL, None, None
            try:
                turn = policy.step(progress.messages, tools, thinking=spec.thinking, sampling=spec.sampling, max_new_tokens=budget.max_new_tokens)
            except PolicyInfraError as exc:
                return Termination.INFRA_ERROR, FailureOwner.INFRA, None, str(exc)
            turn = _relabel(turn, turn_index)
            progress.turns.append(turn)
            if turn.kind is TurnKind.PARSE_ERROR:
                progress.parse_errors += 1
                progress.messages.append(Message(role="assistant", content=turn.raw_text))
                if progress.parse_errors > budget.max_parse_errors:
                    return Termination.PARSE_ERROR_BUDGET, FailureOwner.MODEL, None, turn.parse_error
                progress.messages.append(_feedback({"error": (turn.parse_error or "parse_error").split(":", 1)[0], "detail": turn.parse_error}))
                continue
            if turn.kind is TurnKind.FINAL:
                progress.messages.append(Message(role="assistant", content=turn.content))
                return Termination.FINAL_ANSWER, FailureOwner.NONE, turn.content, None
            if progress.tool_calls_used + len(turn.tool_calls) > budget.max_tool_calls:
                return Termination.TOOL_BUDGET, FailureOwner.MODEL, None, None
            progress.messages.append(Message(role="assistant", content=turn.content, tool_calls=turn.tool_calls))
            progress.tool_calls_used += len(turn.tool_calls)
            for call in turn.tool_calls:
                try:
                    observation = environment.execute(call)
                except Exception as exc:  # noqa: BLE001 - any tool crash is an environment failure
                    return Termination.ENV_ERROR, FailureOwner.ENV, None, f"{type(exc).__name__}: {exc}"
                progress.observations.append(observation)
                progress.messages.append(Message(role="tool", tool_call_id=call.call_id, name=call.name, content=_json(observation.payload)))
        return Termination.MAX_TURNS, FailureOwner.MODEL, None, None


def _relabel(turn: AssistantTurn, turn_index: int) -> AssistantTurn:
    if not turn.tool_calls:
        return turn
    calls = tuple(
        ToolCall(call_id=f"t{turn_index}_c{index}", name=call.name, arguments=call.arguments)
        for index, call in enumerate(turn.tool_calls)
    )
    return turn.model_copy(update={"tool_calls": calls})
```

- [ ] **Step 5: Run to verify pass**

Run: `cd studyhub-agent && $PY -m pytest tests/runtime/test_runner.py -q && lint-imports --config .importlinter`
Expected: all passed; contracts kept.

- [ ] **Step 6: Commit**

```bash
git add studyhub-agent/src/studyhub_agent/runtime studyhub-agent/tests/runtime
git commit -m "feat: add EpisodeRunner shared by datagen, rollout and eval"
```

---

### Task 11: Token-level and OpenAI-compatible policy clients + parity

**Files:**
- Create: `studyhub-agent/src/studyhub_agent/runtime/tokenizer.py`, `runtime/token_client.py`, `runtime/openai_client.py`
- Test: `studyhub-agent/tests/runtime/test_clients.py`

**Interfaces:**
- Consumes: `render_text`, `parse_completion`, `canonical_completion_text`, `END_OF_TURN` (Task 5); `PolicyInfraError` (Task 10).
- Produces:
  - `runtime.tokenizer.Tokenizer` Protocol: `encode(text: str) -> list[int]`, `decode(ids: Sequence[int]) -> str`, `stop_token_ids: tuple[int, ...]`; `HFTokenizer.from_model_dir(path: Path)` (uses `tokenizers.Tokenizer.from_file(path / "tokenizer.json")`, stop ids = ids of `<|im_end|>` and `<|endoftext|>`); `token_counter(tokenizer) -> TokenCounter`
  - `runtime.token_client.Generation(output_ids: tuple[int, ...], logprobs: tuple[float, ...], finish_reason: str | None)`; `GenerateBackend` Protocol `generate(input_ids, *, sampling, max_new_tokens, stop_token_ids) -> Generation`; `SGLangGenerateBackend(base_url: str, *, timeout_s: float = 120.0, client: httpx.Client | None = None)`; `TokenPolicyClient(tokenizer: Tokenizer, backend: GenerateBackend)` implementing `PolicyClient`
  - `runtime.openai_client.OpenAICompatPolicyClient(base_url: str, model: str, *, api_key: str | None = None, tokenizer: Tokenizer | None = None, timeout_s: float = 120.0, client: httpx.Client | None = None)` implementing `PolicyClient`

- [ ] **Step 1: Write the failing tests**

```python
import json
from collections.abc import Sequence

import httpx
import pytest

from studyhub_agent.contracts.episode import Message, Sampling, ToolCall, TurnKind
from studyhub_agent.contracts.render import canonical_completion_text
from studyhub_agent.runtime.openai_client import OpenAICompatPolicyClient
from studyhub_agent.runtime.policy import PolicyInfraError
from studyhub_agent.runtime.token_client import Generation, SGLangGenerateBackend, TokenPolicyClient
from studyhub_agent.tools.specs import select_tools

TOOLS = select_tools(["materials_search", "materials_read"])
HISTORY = (Message(role="system", content="系统"), Message(role="user", content="找线性代数笔记"))
CALL = ToolCall(call_id="call_0", name="materials_search", arguments={"query": "线性代数 笔记", "limit": 3})
ASSISTANT = Message(role="assistant", content="我先检索。", tool_calls=(CALL,))
CANONICAL = canonical_completion_text(HISTORY, ASSISTANT, TOOLS, thinking=False)


class CharTokenizer:
    stop_token_ids: tuple[int, ...] = ()

    def encode(self, text: str) -> list[int]:
        return [ord(ch) for ch in text]

    def decode(self, ids: Sequence[int]) -> str:
        return "".join(chr(i) for i in ids)


class CannedBackend:
    def __init__(self, text: str) -> None:
        self.text = text
        self.last_input: list[int] = []

    def generate(self, input_ids, *, sampling, max_new_tokens, stop_token_ids) -> Generation:
        self.last_input = list(input_ids)
        ids = tuple(ord(ch) for ch in self.text)
        return Generation(output_ids=ids, logprobs=tuple(-0.1 for _ in ids), finish_reason="stop")


def _openai_transport(message: dict) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["tools"][0]["function"]["name"] == "materials_search"
        assert body["chat_template_kwargs"] == {"enable_thinking": False}
        return httpx.Response(200, json={"choices": [{"message": message, "finish_reason": "tool_calls"}]})

    return httpx.MockTransport(handler)


def test_token_and_openai_clients_produce_identical_canonical_completion() -> None:
    generated = CANONICAL.removesuffix("<|im_end|>\n")
    token_client = TokenPolicyClient(CharTokenizer(), CannedBackend(generated))
    token_turn = token_client.step(HISTORY, TOOLS, thinking=False, sampling=Sampling(), max_new_tokens=256)

    openai_message = {
        "role": "assistant",
        "content": "我先检索。",
        "tool_calls": [{"id": "x", "type": "function", "function": {"name": "materials_search", "arguments": json.dumps({"limit": 3, "query": "线性代数 笔记"}, ensure_ascii=False)}}],
    }
    openai_client = OpenAICompatPolicyClient(
        "http://teacher", "qwen", tokenizer=CharTokenizer(), client=httpx.Client(transport=_openai_transport(openai_message))
    )
    openai_turn = openai_client.step(HISTORY, TOOLS, thinking=False, sampling=Sampling(), max_new_tokens=256)

    assert token_turn.kind is openai_turn.kind is TurnKind.TOOL_CALLS
    assert token_turn.tool_calls == openai_turn.tool_calls
    assert token_turn.canonical_text == openai_turn.canonical_text == CANONICAL
    assert openai_turn.completion_token_ids == tuple(ord(ch) for ch in CANONICAL)
    assert token_turn.non_canonical is False and openai_turn.server_parse_mismatch is False


def test_token_client_sends_rendered_prompt_and_keeps_logprobs() -> None:
    backend = CannedBackend("好的，答案是 A。")
    turn = TokenPolicyClient(CharTokenizer(), backend).step(HISTORY, TOOLS, thinking=False, sampling=Sampling(), max_new_tokens=64)
    assert "".join(chr(i) for i in backend.last_input).endswith("<think>\n\n</think>\n\n")
    assert turn.kind is TurnKind.FINAL and len(turn.completion_logprobs) == len(turn.completion_token_ids)
    assert turn.prompt_token_ids == tuple(backend.last_input)


def test_token_client_flags_non_canonical_whitespace() -> None:
    turn = TokenPolicyClient(CharTokenizer(), CannedBackend("答案。   ")).step(HISTORY, TOOLS, thinking=False, sampling=Sampling(), max_new_tokens=64)
    assert turn.kind is TurnKind.FINAL and turn.non_canonical is True


def test_openai_invalid_arguments_become_parse_error() -> None:
    message = {"role": "assistant", "content": None, "tool_calls": [{"id": "x", "type": "function", "function": {"name": "materials_search", "arguments": "{not json"}}]}
    client = OpenAICompatPolicyClient("http://t", "m", client=httpx.Client(transport=_openai_transport(message)))
    turn = client.step(HISTORY, TOOLS, thinking=False, sampling=Sampling(), max_new_tokens=64)
    assert turn.kind is TurnKind.PARSE_ERROR and turn.parse_error.startswith("invalid_arguments_json")


def test_openai_mixed_answer_and_tool_call_is_a_tool_turn_with_preamble() -> None:
    message = {
        "role": "assistant",
        "content": "答案是 A",
        "tool_calls": [{"id": "x", "type": "function", "function": {"name": "materials_search", "arguments": "{\"query\": \"a\"}"}}],
    }
    client = OpenAICompatPolicyClient("http://t", "m", client=httpx.Client(transport=_openai_transport(message)))
    turn = client.step(HISTORY, TOOLS, thinking=False, sampling=Sampling(), max_new_tokens=64)
    assert turn.kind is TurnKind.TOOL_CALLS and turn.content == "答案是 A"


def test_http_failures_raise_policy_infra_error() -> None:
    failing = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(503, text="overloaded")))
    with pytest.raises(PolicyInfraError):
        OpenAICompatPolicyClient("http://t", "m", client=failing).step(HISTORY, TOOLS, thinking=False, sampling=Sampling(), max_new_tokens=8)
    backend = SGLangGenerateBackend("http://sglang", client=failing)
    with pytest.raises(PolicyInfraError):
        backend.generate([1, 2], sampling=Sampling(), max_new_tokens=8, stop_token_ids=())


def test_sglang_backend_request_and_response_shape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["input_ids"] == [5, 6]
        assert body["sampling_params"]["max_new_tokens"] == 8
        assert body["return_logprob"] is True
        return httpx.Response(200, json={"text": "ab", "meta_info": {"output_token_logprobs": [[-0.5, 97, "a"], [-0.25, 98, "b"]], "finish_reason": {"type": "stop"}}})

    backend = SGLangGenerateBackend("http://sglang", client=httpx.Client(transport=httpx.MockTransport(handler)))
    generation = backend.generate([5, 6], sampling=Sampling(), max_new_tokens=8, stop_token_ids=(151645,))
    assert generation == Generation(output_ids=(97, 98), logprobs=(-0.5, -0.25), finish_reason="stop")
```

- [ ] **Step 2: Run to verify failure**

Run: `cd studyhub-agent && $PY -m pytest tests/runtime/test_clients.py -q`
Expected: FAIL — modules not found.

- [ ] **Step 3: Implement**

`runtime/tokenizer.py`:
```python
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from studyhub_agent.contracts.episode import Message
from studyhub_agent.contracts.render import render_text
from studyhub_agent.contracts.tools import ToolSpec


class Tokenizer(Protocol):
    stop_token_ids: tuple[int, ...]

    def encode(self, text: str) -> list[int]: ...

    def decode(self, ids: Sequence[int]) -> str: ...


class HFTokenizer:
    """Thin wrapper over the model's tokenizer.json (no transformers dependency)."""

    def __init__(self, backend, stop_token_ids: tuple[int, ...]) -> None:
        self._backend = backend
        self.stop_token_ids = stop_token_ids

    @classmethod
    def from_model_dir(cls, path: Path) -> HFTokenizer:
        from tokenizers import Tokenizer as RawTokenizer

        backend = RawTokenizer.from_file(str(path / "tokenizer.json"))
        stops = tuple(token_id for token_id in (backend.token_to_id("<|im_end|>"), backend.token_to_id("<|endoftext|>")) if token_id is not None)
        return cls(backend, stops)

    def encode(self, text: str) -> list[int]:
        return self._backend.encode(text, add_special_tokens=False).ids

    def decode(self, ids: Sequence[int]) -> str:
        return self._backend.decode(list(ids), skip_special_tokens=False)


def token_counter(tokenizer: Tokenizer):
    def count(messages: Sequence[Message], tools: Sequence[ToolSpec], thinking: bool) -> int:
        return len(tokenizer.encode(render_text(messages, tools, thinking=thinking, add_generation_prompt=True)))

    return count
```

`runtime/token_client.py`:
```python
from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import httpx

from studyhub_agent.contracts.episode import AssistantTurn, Message, Sampling, TurnKind
from studyhub_agent.contracts.render import END_OF_TURN, RenderError, canonical_completion_text, parse_completion, render_text
from studyhub_agent.contracts.tools import ToolSpec
from studyhub_agent.runtime.policy import PolicyInfraError
from studyhub_agent.runtime.tokenizer import Tokenizer


@dataclass(frozen=True, slots=True)
class Generation:
    output_ids: tuple[int, ...]
    logprobs: tuple[float, ...]
    finish_reason: str | None


class GenerateBackend(Protocol):
    def generate(self, input_ids: Sequence[int], *, sampling: Sampling, max_new_tokens: int, stop_token_ids: Sequence[int]) -> Generation: ...


class SGLangGenerateBackend:
    def __init__(self, base_url: str, *, timeout_s: float = 120.0, client: httpx.Client | None = None) -> None:
        self._url = base_url.rstrip("/") + "/generate"
        self._client = client or httpx.Client(timeout=timeout_s)

    def generate(self, input_ids: Sequence[int], *, sampling: Sampling, max_new_tokens: int, stop_token_ids: Sequence[int]) -> Generation:
        params = {
            "temperature": sampling.temperature,
            "top_p": sampling.top_p,
            "max_new_tokens": max_new_tokens,
            "stop_token_ids": list(stop_token_ids),
            "skip_special_tokens": False,
        }
        if sampling.seed is not None:
            params["sampling_seed"] = sampling.seed
        try:
            response = self._client.post(self._url, json={"input_ids": list(input_ids), "sampling_params": params, "return_logprob": True})
            response.raise_for_status()
            meta = response.json()["meta_info"]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise PolicyInfraError(f"sglang generate failed: {exc}") from exc
        pairs = meta.get("output_token_logprobs") or []
        finish = meta.get("finish_reason")
        return Generation(
            output_ids=tuple(int(item[1]) for item in pairs),
            logprobs=tuple(float(item[0]) for item in pairs),
            finish_reason=finish.get("type") if isinstance(finish, dict) else finish,
        )


class TokenPolicyClient:
    def __init__(self, tokenizer: Tokenizer, backend: GenerateBackend) -> None:
        self._tokenizer = tokenizer
        self._backend = backend

    def step(self, messages: Sequence[Message], tools: Sequence[ToolSpec], *, thinking: bool, sampling: Sampling, max_new_tokens: int) -> AssistantTurn:
        prompt_ids = self._tokenizer.encode(render_text(messages, tools, thinking=thinking, add_generation_prompt=True))
        started = time.perf_counter()
        generation = self._backend.generate(prompt_ids, sampling=sampling, max_new_tokens=max_new_tokens, stop_token_ids=self._tokenizer.stop_token_ids)
        latency_ms = (time.perf_counter() - started) * 1000
        raw_text = self._tokenizer.decode(generation.output_ids).split(END_OF_TURN, 1)[0]
        parsed = parse_completion(raw_text, tools, thinking=thinking)
        canonical = raw_text
        if parsed.kind is not TurnKind.PARSE_ERROR:
            assistant = Message(role="assistant", content=parsed.content, tool_calls=parsed.tool_calls)
            try:
                canonical = canonical_completion_text(messages, assistant, tools, thinking=thinking)
            except RenderError as exc:
                return _parse_error_turn(raw_text, f"unrenderable: {exc}", prompt_ids, generation, latency_ms)
        return AssistantTurn(
            kind=parsed.kind,
            content=parsed.content,
            tool_calls=parsed.tool_calls,
            raw_text=raw_text,
            canonical_text=canonical,
            parse_error=parsed.error,
            prompt_token_ids=tuple(prompt_ids),
            completion_token_ids=generation.output_ids,
            completion_logprobs=generation.logprobs,
            non_canonical=parsed.kind is not TurnKind.PARSE_ERROR and canonical.removesuffix(END_OF_TURN + "\n") != raw_text,
            finish_reason=generation.finish_reason,
            latency_ms=latency_ms,
        )


def _parse_error_turn(raw_text: str, error: str, prompt_ids: Sequence[int], generation: Generation, latency_ms: float) -> AssistantTurn:
    return AssistantTurn(
        kind=TurnKind.PARSE_ERROR,
        raw_text=raw_text,
        canonical_text=raw_text,
        parse_error=error,
        prompt_token_ids=tuple(prompt_ids),
        completion_token_ids=generation.output_ids,
        completion_logprobs=generation.logprobs,
        finish_reason=generation.finish_reason,
        latency_ms=latency_ms,
    )
```

Note for the implementer: `non_canonical` compares the generated text with the canonical render minus the end marker. With thinking disabled the canonical render of a FINAL turn is `content + "<|im_end|>\n"` where the template trims `content`, so trailing spaces in the raw text make the turn non-canonical (as the test expects).

`runtime/openai_client.py`:
```python
from __future__ import annotations

import json
import time
from collections.abc import Sequence
from typing import Any

import httpx

from studyhub_agent.contracts.episode import AssistantTurn, Message, Sampling, ToolCall, TurnKind
from studyhub_agent.contracts.render import RenderError, canonical_completion_text, parse_completion
from studyhub_agent.contracts.tools import ToolSpec
from studyhub_agent.runtime.policy import PolicyInfraError
from studyhub_agent.runtime.tokenizer import Tokenizer


def _wire_message(message: Message) -> dict[str, Any]:
    if message.role == "assistant" and message.tool_calls:
        return {
            "role": "assistant",
            "content": message.content or None,
            "tool_calls": [
                {"id": call.call_id, "type": "function", "function": {"name": call.name, "arguments": json.dumps(call.arguments, ensure_ascii=False)}}
                for call in message.tool_calls
            ],
        }
    if message.role == "tool":
        return {"role": "tool", "content": message.content, "tool_call_id": message.tool_call_id or message.name or "runtime"}
    return {"role": message.role, "content": message.content}


class OpenAICompatPolicyClient:
    """Teacher/baseline client. Its turns are re-rendered through the single renderer before any use as data."""

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        api_key: str | None = None,
        tokenizer: Tokenizer | None = None,
        timeout_s: float = 120.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._url = base_url.rstrip("/") + "/v1/chat/completions"
        self._model = model
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._tokenizer = tokenizer
        self._client = client or httpx.Client(timeout=timeout_s)

    def step(self, messages: Sequence[Message], tools: Sequence[ToolSpec], *, thinking: bool, sampling: Sampling, max_new_tokens: int) -> AssistantTurn:
        body: dict[str, Any] = {
            "model": self._model,
            "messages": [_wire_message(message) for message in messages],
            "tools": [tool.to_openai() for tool in tools],
            "temperature": sampling.temperature,
            "top_p": sampling.top_p,
            "max_tokens": max_new_tokens,
            "chat_template_kwargs": {"enable_thinking": thinking},
        }
        if sampling.seed is not None:
            body["seed"] = sampling.seed
        started = time.perf_counter()
        try:
            response = self._client.post(self._url, json=body, headers=self._headers)
            response.raise_for_status()
            choice = response.json()["choices"][0]
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            raise PolicyInfraError(f"chat completion failed: {exc}") from exc
        latency_ms = (time.perf_counter() - started) * 1000
        return self._to_turn(messages, tools, choice, thinking=thinking, latency_ms=latency_ms)

    def _to_turn(self, messages: Sequence[Message], tools: Sequence[ToolSpec], choice: dict[str, Any], *, thinking: bool, latency_ms: float) -> AssistantTurn:
        message = choice.get("message") or {}
        content = (message.get("content") or "").strip()
        raw_text = json.dumps(message, ensure_ascii=False, sort_keys=True)
        calls: list[ToolCall] = []
        for index, item in enumerate(message.get("tool_calls") or []):
            function = item.get("function") or {}
            try:
                arguments = json.loads(function.get("arguments") or "{}")
            except json.JSONDecodeError:
                return self._error(raw_text, f"invalid_arguments_json: {function.get('name')}", choice, latency_ms)
            if not isinstance(arguments, dict):
                return self._error(raw_text, f"invalid_arguments_json: {function.get('name')}", choice, latency_ms)
            calls.append(ToolCall(call_id=f"call_{index}", name=str(function.get("name")), arguments=arguments))
        if not calls and not content:
            return self._error(raw_text, "empty_response", choice, latency_ms)
        assistant = Message(role="assistant", content=content, tool_calls=tuple(calls))
        try:
            canonical = canonical_completion_text(messages, assistant, tools, thinking=thinking)
        except RenderError as exc:
            return self._error(raw_text, f"unrenderable: {exc}", choice, latency_ms)
        reparsed = parse_completion(canonical, tools, thinking=thinking)
        if reparsed.kind is TurnKind.PARSE_ERROR:
            return self._error(raw_text, reparsed.error or "parse_error", choice, latency_ms)
        return AssistantTurn(
            kind=reparsed.kind,
            content=reparsed.content,
            tool_calls=reparsed.tool_calls,
            raw_text=raw_text,
            canonical_text=canonical,
            completion_token_ids=tuple(self._tokenizer.encode(canonical)) if self._tokenizer else (),
            server_parse_mismatch=reparsed.tool_calls != tuple(calls),
            finish_reason=choice.get("finish_reason"),
            latency_ms=latency_ms,
        )

    @staticmethod
    def _error(raw_text: str, error: str, choice: dict[str, Any], latency_ms: float) -> AssistantTurn:
        return AssistantTurn(kind=TurnKind.PARSE_ERROR, raw_text=raw_text, canonical_text=raw_text, parse_error=error, finish_reason=choice.get("finish_reason"), latency_ms=latency_ms)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd studyhub-agent && $PY -m pytest tests/runtime -q && lint-imports --config .importlinter`
Expected: all passed. If the parity test fails, diff the two `canonical_text` values; the fix belongs in the client that deviates, never in the test.

- [ ] **Step 5: Commit**

```bash
git add studyhub-agent/src/studyhub_agent/runtime studyhub-agent/tests/runtime/test_clients.py
git commit -m "feat: add token-level and OpenAI-compatible policy clients with render parity"
```

---

### Task 12: Grader protocol and exact-match grader

**Files:**
- Create: `studyhub-agent/src/studyhub_agent/graders/base.py`, `graders/exact_match.py`
- Test: `studyhub-agent/tests/graders/test_exact_match.py` (+ `tests/graders/__init__.py`)

**Interfaces:**
- Consumes: `Episode`, `FailureOwner`, `Termination` (Task 4).
- Produces: `TaskSpec(task_id: str, expected_final: str | None = None, required_tools: tuple[str, ...] = ())` (pydantic frozen, extra forbid); `GradeResult(strict_pass: bool, hard_gates: dict[str, bool], scores: dict[str, float], failure_owner: FailureOwner, evidence: tuple[str, ...] = ())`; `Grader` Protocol `grade(episode: Episode, task: TaskSpec) -> GradeResult`; `ExactMatchGrader()`.

- [ ] **Step 1: Write the failing tests**

```python
from studyhub_agent.contracts.episode import Episode, EpisodeSpec, FailureOwner, Message, Principal, Termination, ToolCall, AssistantTurn, TurnKind
from studyhub_agent.graders.base import TaskSpec
from studyhub_agent.graders.exact_match import ExactMatchGrader

SPEC = EpisodeSpec(episode_id="e", task_id="t", user_message="q", principal=Principal(principal_id="u"), tool_names=("materials_search",))


def _episode(final: str | None, termination=Termination.FINAL_ANSWER, owner=FailureOwner.NONE, tools=("materials_search",)) -> Episode:
    turns = tuple(
        AssistantTurn(kind=TurnKind.TOOL_CALLS, tool_calls=(ToolCall(call_id="c", name=name, arguments={}),), raw_text="", canonical_text="")
        for name in tools
    )
    return Episode(spec=SPEC, contract_hash="sha256:x", messages=(Message(role="user", content="q"),), turns=turns, observations=(), termination=termination, failure_owner=owner, final_answer=final)


def test_pass_requires_answer_match_and_required_tools() -> None:
    task = TaskSpec(task_id="t", expected_final=" 2027-01-08 ", required_tools=("materials_search",))
    result = ExactMatchGrader().grade(_episode("2027-01-08"), task)
    assert result.strict_pass and result.hard_gates == {"final_answer_present": True, "required_tools_used": True, "answer_matches": True}


def test_missing_tool_fails_gate() -> None:
    task = TaskSpec(task_id="t", expected_final="a", required_tools=("materials_read",))
    result = ExactMatchGrader().grade(_episode("a"), task)
    assert not result.strict_pass and result.hard_gates["required_tools_used"] is False


def test_infra_failure_is_attributed_not_scored_as_model_failure() -> None:
    result = ExactMatchGrader().grade(_episode(None, Termination.INFRA_ERROR, FailureOwner.INFRA), TaskSpec(task_id="t", expected_final="a"))
    assert not result.strict_pass and result.failure_owner is FailureOwner.INFRA


def test_wrong_answer_is_model_failure() -> None:
    result = ExactMatchGrader().grade(_episode("b"), TaskSpec(task_id="t", expected_final="a"))
    assert result.failure_owner is FailureOwner.MODEL and result.scores["answer_match"] == 0.0
```

- [ ] **Step 2: Run to verify failure**

Run: `cd studyhub-agent && $PY -m pytest tests/graders -q`
Expected: FAIL — modules not found.

- [ ] **Step 3: Implement**

`graders/base.py`:
```python
from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict

from studyhub_agent.contracts.episode import Episode, FailureOwner


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class TaskSpec(_Frozen):
    task_id: str
    expected_final: str | None = None
    required_tools: tuple[str, ...] = ()


class GradeResult(_Frozen):
    strict_pass: bool
    hard_gates: dict[str, bool]
    scores: dict[str, float]
    failure_owner: FailureOwner
    evidence: tuple[str, ...] = ()


class Grader(Protocol):
    def grade(self, episode: Episode, task: TaskSpec) -> GradeResult: ...
```

`graders/exact_match.py`:
```python
from __future__ import annotations

from studyhub_agent.contracts.episode import Episode, FailureOwner
from studyhub_agent.graders.base import GradeResult, TaskSpec


def _normalize(text: str | None) -> str:
    return " ".join((text or "").split())


class ExactMatchGrader:
    """Test grader: normalized exact match plus required-tool usage."""

    def grade(self, episode: Episode, task: TaskSpec) -> GradeResult:
        used = {call.name for turn in episode.turns for call in turn.tool_calls}
        matches = task.expected_final is None or _normalize(episode.final_answer) == _normalize(task.expected_final)
        gates = {
            "final_answer_present": bool(_normalize(episode.final_answer)),
            "required_tools_used": set(task.required_tools) <= used,
            "answer_matches": matches,
        }
        strict = all(gates.values())
        if episode.failure_owner in {FailureOwner.INFRA, FailureOwner.ENV}:
            owner = episode.failure_owner
        else:
            owner = FailureOwner.NONE if strict else FailureOwner.MODEL
        evidence = tuple(f"{gate}=false" for gate, ok in gates.items() if not ok)
        return GradeResult(strict_pass=strict and owner is FailureOwner.NONE, hard_gates=gates, scores={"answer_match": 1.0 if matches else 0.0}, failure_owner=owner, evidence=evidence)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd studyhub-agent && $PY -m pytest tests/graders -q && lint-imports --config .importlinter`
Expected: all passed; graders contract kept.

- [ ] **Step 5: Commit**

```bash
git add studyhub-agent/src/studyhub_agent/graders studyhub-agent/tests/graders
git commit -m "feat: add grader protocol and exact-match grader"
```

---

### Task 13: CI workflow, coverage gate and README

**Files:**
- Create: `.github/workflows/agent.yml`
- Modify: `studyhub-agent/README.md` (full rewrite)

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Write `.github/workflows/agent.yml`**

```yaml
name: Agent

on:
  workflow_dispatch:
  push:
    branches: [main]
    paths: ["studyhub-agent/**", ".github/workflows/agent.yml"]
  pull_request:
    paths: ["studyhub-agent/**", ".github/workflows/agent.yml"]

permissions:
  contents: read

jobs:
  test:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    defaults:
      run:
        working-directory: studyhub-agent
    steps:
      - uses: actions/checkout@v5
      - uses: actions/setup-python@v6
        with:
          python-version: "3.12"
          cache: pip
          cache-dependency-path: studyhub-agent/pyproject.toml
      - run: pip install -e ".[dev]"
      - run: ruff check src tests
      - run: lint-imports --config .importlinter
      - run: pytest --cov --cov-report=term-missing
```

- [ ] **Step 2: Rewrite `studyhub-agent/README.md`**

```markdown
# StudyHub Agent v3

A research codebase for a StudyHub study-assistant agent built on Qwen3.5-4B, with 9B/27B as prompted baselines.
Design: [`docs/specs/2026-09-25-foundation-design.md`](docs/specs/2026-09-25-foundation-design.md).

## Layout

| Package | Responsibility |
|---|---|
| `contracts` | ToolSpec + lint, versioned prompts, episode models, the single Qwen3.5 renderer/parser, contract hash |
| `guardrails` | permissions, privacy redaction, SSRF policy |
| `tools` | the 8 tool specs and their backend MCP names |
| `environments` | `Environment` protocol and the gated `ReplayEnvironment` |
| `runtime` | `EpisodeRunner`, token-level (SGLang) and OpenAI-compatible policy clients |
| `graders` | `Grader` protocol (benchmark and reward graders arrive in sub-project 2) |

Layering is enforced by `lint-imports --config .importlinter`.

## Contract

Every episode, SFT sample, rollout and evaluation row carries a `contract_hash` covering the prompts, tool specs,
thinking flag, chat-template digest, tokenizer revision, token limits and the turn rule. Rows with different hashes are
never mixed. Tools marked `capability="snapshot"` run against frozen data and are not claims about the live product.

## Development

```bash
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev,tokenizers]"
.venv/bin/ruff check src tests && .venv/bin/lint-imports --config .importlinter && .venv/bin/pytest --cov
```

Model-dependent acceptance tests: `STUDYHUB_AGENT_MODEL_DIR=/path/to/Qwen3.5-4B pytest -m requires_model`.

## History

The v2 code (Hermes/AReaL workflows, benchmark v1/v2, SFT/GRPO/OPD scripts) is preserved at tag `legacy-agent-v2`
(unmerged OPD work at `archive/opd-*`). Reports and design-defect post-mortems are in `docs/history/`.
```

- [ ] **Step 3: Run the full gate**

Run: `cd studyhub-agent && $PY -m ruff check src tests && lint-imports --config .importlinter && $PY -m pytest --cov`
Expected: ruff clean; 2 contracts kept; all tests pass; coverage ≥ 80% (`Required test coverage of 80% reached`).

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/agent.yml studyhub-agent/README.md
git commit -m "ci: add studyhub-agent v3 workflow with coverage and layering gates"
```

---

### Task 14: Server acceptance — real template, real tokenizer, real model

**Files:**
- Create: `studyhub-agent/tests/acceptance/__init__.py`, `tests/acceptance/test_template_matches_transformers.py`, `studyhub-agent/scripts/smoke_episodes.py`, `studyhub-agent/tests/fixtures/smoke_tasks.jsonl`

**Interfaces:**
- Consumes: `render_text`, `HFTokenizer`, `TokenPolicyClient`, `SGLangGenerateBackend`, `EpisodeRunner`, `ReplayEnvironment`.
- Produces: `scripts/smoke_episodes.py --model-dir PATH --sglang-url URL --snapshot PATH --tasks PATH --out PATH` writing one `Episode` JSON per line.

- [ ] **Step 1: Write the transformers equivalence test**

```python
import os
from pathlib import Path

import pytest

from studyhub_agent.contracts.episode import Message, ToolCall
from studyhub_agent.contracts.render import render_text
from studyhub_agent.tools.specs import TOOL_SPECS

MODEL_DIR = os.environ.get("STUDYHUB_AGENT_MODEL_DIR")
pytestmark = [pytest.mark.requires_model, pytest.mark.skipif(not MODEL_DIR, reason="STUDYHUB_AGENT_MODEL_DIR not set")]

CONVERSATIONS = [
    (Message(role="system", content="系统"), Message(role="user", content="找高数资料")),
    (
        Message(role="system", content="系统"),
        Message(role="user", content="找高数资料"),
        Message(role="assistant", content="检索中", tool_calls=(ToolCall(call_id="c", name="materials_search", arguments={"query": "高数\n期末", "limit": 3}),)),
        Message(role="tool", tool_call_id="c", name="materials_search", content='{"results":[]}'),
    ),
]


@pytest.mark.parametrize("thinking", [False, True])
@pytest.mark.parametrize("conversation", CONVERSATIONS)
def test_render_matches_transformers_apply_chat_template(conversation, thinking) -> None:
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(Path(MODEL_DIR))
    wire = []
    for message in conversation:
        item = {"role": message.role, "content": message.content}
        if message.tool_calls:
            item["tool_calls"] = [{"type": "function", "function": {"name": c.name, "arguments": c.arguments}} for c in message.tool_calls]
        wire.append(item)
    expected = tokenizer.apply_chat_template(
        wire, tools=[t.to_openai() for t in TOOL_SPECS], tokenize=False, add_generation_prompt=True, enable_thinking=thinking
    )
    assert render_text(conversation, TOOL_SPECS, thinking=thinking, add_generation_prompt=True) == expected
```

- [ ] **Step 2: Write `tests/fixtures/smoke_tasks.jsonl`**

```json
{"episode_id": "smoke-1", "task_id": "smoke-policy-refund", "user_message": "我买的资料还没下载，能退款吗？", "principal": {"principal_id": "u-1001"}, "tool_names": ["platform_policy", "materials_search"]}
{"episode_id": "smoke-2", "task_id": "smoke-search-read", "user_message": "电子科技大学高数期末复习先看什么？请引用资料。", "principal": {"principal_id": "u-1001"}, "tool_names": ["materials_search", "materials_get", "materials_read"]}
{"episode_id": "smoke-3", "task_id": "smoke-memory", "user_message": "我的考试是哪天？顺便记住我积分比较薄弱。", "principal": {"principal_id": "u-1001"}, "tool_names": ["memory_get", "memory_update"]}
```

- [ ] **Step 3: Write `scripts/smoke_episodes.py`**

```python
"""Run fixture tasks against a served model and write Episode JSONL (sub-project 1 acceptance)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from studyhub_agent.contracts.episode import EpisodeSpec
from studyhub_agent.contracts.prompts import DEFAULT_PROMPTS
from studyhub_agent.environments.replay import ReplayEnvironment, load_snapshot
from studyhub_agent.runtime.runner import EpisodeRunner
from studyhub_agent.runtime.token_client import SGLangGenerateBackend, TokenPolicyClient
from studyhub_agent.runtime.tokenizer import HFTokenizer, token_counter


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--sglang-url", required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--tasks", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    tokenizer = HFTokenizer.from_model_dir(args.model_dir)
    revision = f"{args.model_dir.name}@{(args.model_dir / 'tokenizer.json').stat().st_size}"
    runner = EpisodeRunner(prompts=DEFAULT_PROMPTS, tokenizer_revision=revision, count_tokens=token_counter(tokenizer))
    policy = TokenPolicyClient(tokenizer, SGLangGenerateBackend(args.sglang_url))
    environment = ReplayEnvironment(load_snapshot(args.snapshot))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        for line in args.tasks.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            episode = runner.run(EpisodeSpec.model_validate_json(line), environment, policy)
            handle.write(episode.model_dump_json() + "\n")
            print(f"{episode.spec.episode_id}: {episode.termination} turns={len(episode.turns)} hash={episode.contract_hash[:19]}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the equivalence test on the server**

```bash
/data/chengjin/.venvs/studyhub-agent/bin/pip install -q -e "studyhub-agent[acceptance]"
cd studyhub-agent && STUDYHUB_AGENT_MODEL_DIR=/data/chengjin/studyhub/models/P1/Qwen3.5-4B $PY -m pytest -m requires_model tests/acceptance -q
```
Expected: 4 passed. A failure here means `render_text` diverges from transformers — fix `render.py` (filters/env options), not the test.

- [ ] **Step 5: Serve Qwen3.5-4B with SGLang and run the smoke episodes**

```bash
nvidia-smi --query-gpu=index,memory.used,memory.total,utilization.gpu --format=csv
# pick a GPU with >= 20 GB free; locate an existing SGLang install first:
find /data/chengjin -maxdepth 6 -path "*site-packages/sglang" -type d 2>/dev/null | head -3
# if none: create /data/chengjin/.venvs/sglang with the uv Python 3.12 and `pip install "sglang[all]"` pinned to the version the legacy OPD docs recorded
CUDA_VISIBLE_DEVICES=<free gpu> <sglang python> -m sglang.launch_server --model-path /data/chengjin/studyhub/models/P1/Qwen3.5-4B --host 127.0.0.1 --port 30411 --mem-fraction-static 0.6 &
# wait until: curl -s 127.0.0.1:30411/health returns 200
cd studyhub-agent && $PY scripts/smoke_episodes.py --model-dir /data/chengjin/studyhub/models/P1/Qwen3.5-4B --sglang-url http://127.0.0.1:30411 --snapshot tests/fixtures/replay_snapshot.json --tasks tests/fixtures/smoke_tasks.jsonl --out /tmp/studyhub-agent-smoke/episodes.jsonl
# stop the server afterwards (kill the launch_server PID)
```
Expected: 3 lines printed, each with a termination and the same contract hash per tool set; `/tmp/studyhub-agent-smoke/episodes.jsonl` has 3 JSON lines that `Episode.model_validate_json` accepts. INFRA errors mean the server is not reachable — fix the server, not the runner. Record the printed lines in the commit message body.

- [ ] **Step 6: Commit**

```bash
git add studyhub-agent/tests/acceptance studyhub-agent/scripts/smoke_episodes.py studyhub-agent/tests/fixtures/smoke_tasks.jsonl
git commit -m "test: add real-model acceptance for renderer parity and smoke episodes"
```

---

### Task 15: Archive OPD conclusions, delete legacy branches and worktrees

**Files:**
- Create: `studyhub-agent/docs/history/opd-evaluation.md`

**Interfaces:**
- Consumes: tags from Task 1.

- [ ] **Step 1: Write the OPD history note from the archived branch**

```bash
cd /data/chengjin/studyhub
git show archive/opd-evaluation --stat | head -40
git ls-tree -r --name-only archive/opd-evaluation | grep -iE "OPD_FORMAL_300_CLOSEOUT|opd.*evaluation.*\.md" 
```
Write `studyhub-agent/docs/history/opd-evaluation.md` with: run dates, teacher/student, steps, Dev51 result (M2 4/51 vs OPD 4/51, 3W/3L/45T), Protocol128 metrics (tool parse 97.1%→89.1%, tool-name match 90.2%→79.2%, non-empty final 87.3%→98.4%), BFCL/tau2 not produced (`uv` missing), and the conclusion "no measurable gain; teacher not stronger than student on the target distribution". Cite the source paths as `archive/opd-evaluation:<path>`.

- [ ] **Step 2: Verify worktrees are clean and unused before deletion**

```bash
cd /data/chengjin/studyhub
for wt in $(git worktree list --porcelain | awk '/^worktree /{print $2}' | grep -v "^/data/chengjin/studyhub$" | grep -v "studyhub-agent-v3"); do
  echo "== $wt"; git -C "$wt" status --short | head -5
  ls -l /proc/*/cwd 2>/dev/null | grep -F "$wt" | head -2
done
```
Expected: every worktree prints no status lines and no process cwd lines. If any worktree is dirty or in use (e.g. a running bot under `studyhub-offline-pilot`), STOP and report the list to the owner instead of deleting.

- [ ] **Step 3: Remove worktrees and local branches**

```bash
cd /data/chengjin/studyhub
for wt in studyhub-m1-eval-worktree studyhub-m2-prep-validation studyhub-offline-pilot studyhub-opd-evaluation-worktree studyhub-opd-execution-worktree studyhub-opd-worktree studyhub-sft2-worktree studyhub-spark-worktree studyhub-tool-architecture; do
  git worktree remove "/data/chengjin/$wt"
done
git branch -D agent/fix-agent-security-boundaries agent/offline-pilot-runtime-guards \
  codex/hermes-native-tool-convergence codex/qwen35-4b-m1-eval codex/qwen35-4b-opd-evaluation \
  codex/qwen35-4b-opd-execution codex/qwen35-4b-opd-preflight codex/qwen35-4b-sft2-data-gate \
  codex/spark-hermes-teacher-v1 publish/merge-agent-research-20260816 refactor/agent-artifacts-layout \
  refactor/studyhub-agent-package research/agent-sft-completion research/router-rl-readiness-v1
git worktree list
```
Expected: only the main checkout and the v3 worktree remain.

- [ ] **Step 4: Delete the remote agent branches**

```bash
git push origin --delete agent-v2/hermes-rebuild agent/fix-agent-security-boundaries agent/offline-pilot-runtime-guards \
  codex/hermes-native-tool-convergence codex/qwen35-4b-m1-eval codex/qwen35-4b-opd-execution \
  codex/qwen35-4b-opd-preflight codex/qwen35-4b-sft2-data-gate codex/spark-hermes-teacher-v1 \
  research/agent-sft-completion research/router-rl-readiness-v1
git ls-remote --heads origin | grep -E "agent|codex|research" || echo "no agent branches left"
```
Expected: `no agent branches left`.

- [ ] **Step 5: Commit the history note**

```bash
git add studyhub-agent/docs/history/opd-evaluation.md
git commit -m "docs: archive OPD evaluation conclusions before deleting legacy branches"
```

---

## Self-Review Notes

- Spec §2 layout → Tasks 1, 2–6, 7, 8, 9, 10–11, 12; import-linter in Task 1/13.
- Spec §3 contract rules 1–5 → Task 6 (hash), Task 5 (turn rule, lint via Task 2), Task 4 (`extra="forbid"`), Task 10 (hash fixed per episode; finalize prompt from registry).
- Spec §4 runner outputs and INFRA handling → Task 10; §5 clients → Task 11; §6 tools/env → Tasks 8–9; §7 graders → Task 12; §8 legacy → Tasks 1 and 15; §9 tests/CI → Tasks 2–13; §10 acceptance → Task 14.
- The spec's "7 tools" counts the memory pair as one tool; 8 names are implemented (see Global Constraints).
