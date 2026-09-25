# Hermes and StudyHub Tool Boundary

Status: production architecture contract

## Decision

Hermes owns general Agent infrastructure. StudyHub extends Hermes only where a
capability depends on StudyHub data semantics, access control, or learning
products. A production task receives one canonical tool name per capability
and only the schemas in its explicit allowlist.

| Capability | Runtime owner | Production tool |
|---|---|---|
| Public web search | Hermes | `web_search` |
| Public page extraction | Hermes | `web_extract` |
| Personal-memory lifecycle | Hermes `MemoryProvider` | `personal_memory_search` |
| StudyHub material retrieval | StudyHub | `knowledge_search` |
| StudyHub chunk reading | StudyHub | `knowledge_read` |
| StudyHub adjacent chunk browsing | StudyHub | `knowledge_browse` |
| Anonymous group learning patterns | StudyHub | `collective_memory_search` |

`web_fetch` is a frozen schema-v1 replay name. Production tasks must use the
upstream Hermes `web_extract` contract instead. The argument migration is
`{"url": "..."}` to `{"urls": ["..."]}`.

## Runtime Composition

```text
TaskSpec.allowed_tools
          |
          v
HermesRuntimeTools
  |-- StudyHub domain bridge
  |     knowledge_search/read/browse
  |     collective_memory_search
  |
  |-- Hermes native web policy wrapper
  |     budget + allowlist
  |     delegates to upstream web_search/web_extract
  |
  `-- Hermes MemoryManager
        StudyHub personal-memory provider
        namespace + privacy + budget
          |
          v
Exact task-scoped schema projection
          |
          v
Unmodified Hermes Agent loop
```

The native Web wrapper does not implement searching or extraction. It retains
the pinned Hermes schema, provider selection, availability check, result cap,
and security implementation, adding only the StudyHub task budget. The prior
StudyHub Web provider remains available only through the replay package.

Personal memory is attached as one external Hermes memory provider. It is not
also registered in the StudyHub tool registry. Hermes owns prefetch, turn sync,
tool dispatch, session hooks, and shutdown; StudyHub owns the pseudonymous
namespace and output privacy boundary.

## Production and Replay Separation

`build_domain_tool_registry()` creates the production StudyHub registry and
contains only the four domain tools. `studyhub_agent.replay` reconstructs the
frozen seven-tool schema-v1 fixture surface for historical tests and experiment
reproduction. Replay helpers must not be used to compose a production Agent.

The frozen training and Benchmark environments keep their recorded tool
contracts. This change does not rewrite completed datasets or move an
in-progress checkpoint to a different runtime.

## Why This Change Matters

Duplicate ownership was a correctness risk: a StudyHub handler could shadow a
Hermes built-in, Web used two names for the same capability, and personal
memory could be exposed through two dispatch systems. That creates schema
drift, inconsistent budgets, and train/runtime mismatch.

It does not by itself explain the weak SFT results. Most frozen Development
tasks already exposed only a small task-specific subset of tools. The observed
failures also involve premature stopping, citation discipline, recovery, and
trajectory quality. Tool convergence removes one confounder; it is not a
substitute for controlled data and policy experiments.

## Invariants

- No StudyHub production Web provider shadows `web_search` or `web_extract`.
- No production task exposes `web_fetch`.
- Personal memory is routed only through Hermes `MemoryManager`.
- Domain retrieval always passes StudyHub ACL checks before model observation.
- Final Hermes schemas equal `TaskSpec.allowed_tools`; missing or duplicate
  schemas fail closed.
- Overlay teardown restores the exact pinned Hermes registry entries.
- Website `backend/` and `frontend/` remain outside this runtime.
