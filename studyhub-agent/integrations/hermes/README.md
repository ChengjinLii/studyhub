# Hermes upstream integration

StudyHub Agent V2 starts from an unmodified Hermes Agent checkout. The exact
upstream repository and commit are recorded in `upstream.lock.json`.

Bootstrap the checkout with:

```bash
bash studyhub-agent/scripts/setup-hermes.sh
```

The script clones or fetches Hermes into
`studyhub-agent/.vendor/hermes-agent`, verifies that an existing checkout is
clean and points at the expected upstream repository, and checks out the pinned
commit in detached-HEAD mode.

This integration deliberately contains no StudyHub patch, skin, router,
planner, tool loop, memory implementation, or model configuration. Install and
configure Hermes from inside the checkout by following the upstream
documentation. Keep its virtual environment and credentials separate from the
StudyHub website runtime.

StudyHub composes the clean checkout through public runtime surfaces:

- Hermes owns `web_search`, `web_extract`, and the `MemoryProvider` lifecycle.
- StudyHub registers only material RAG and anonymous collective-memory tools.
- A task-scoped policy layer adds allowlist and budget checks, then projects the
  exact requested schemas.
- Frozen schema-v1 Web and memory fixtures live in `studyhub_agent.replay` and
  are not part of the production tool factory.

See [the tool ownership contract](../../docs/architecture/HERMES_TOOL_BOUNDARY.md).

The required construction order is:

```python
runtime_tools = HermesRuntimeTools(domain_registry, execution_context, personal_memory=memory)
with runtime_tools:
    agent = AIAgent(
        enabled_toolsets=runtime_tools.enabled_toolsets,
        skip_memory=True,
        # provider/model/session arguments omitted
    )
    runtime_tools.bind_agent(agent)
    answer = agent.chat(user_request)
```

`bind_agent()` must run before the first model request. It attaches the single
external memory provider and fails closed if the resulting schemas are not
exactly the task allowlist.
