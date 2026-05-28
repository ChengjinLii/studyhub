# StudyHub MCP Gateway Implementation Plan

Date: 2026-05-28

## Branch

Create `feat/studyhub-mcp-gateway` from `origin/main`.

## Implementation Tasks

1. Add `mcp>=1.27,<2.0` to `backend/pyproject.toml`.
2. Add `backend/app/mcp/` modules:
   - `server.py` for FastMCP creation and SDK HTTP settings.
   - `tools.py` for v0 read-only tool registration.
   - `search.py` for service-layer aggregation and typed-id fetch logic.
   - `resources.py` for `studyhub://` resources.
   - `prompts.py` for prompt templates.
   - `auth.py` for Origin checks and reserved write/admin access metadata.
   - `serializers.py` for result ids, URLs, and text fallbacks.
3. Add MCP config fields to `backend/app/core/config.py`.
4. Mount the MCP ASGI surface from `backend/app/main.py` and run the SDK session manager in application lifespan.
5. Add protocol, search/fetch, auth, resource, and prompt tests.
6. Document local validation commands in `backend/README.md`.

## Validation

Run the focused tests first:

```bash
cd backend
../.venv/bin/pytest tests/test_mcp_protocol.py tests/test_mcp_search_fetch.py tests/test_mcp_auth.py tests/test_mcp_resources_prompts.py
```

Then run the broader local gate:

```bash
cd backend && ../.venv/bin/pytest
cd frontend && npm run test:unit
bash scripts/dev/local-dev-status.sh
```

Manual MCP validation:

```bash
npx -y @modelcontextprotocol/inspector http://127.0.0.1:8011/mcp
```

Expected manual checks:

- `tools/list` includes the v0 read-only tools.
- `search` with `{"query":"数据结构","limit":10}` returns typed StudyHub result ids.
- `fetch` with `{"id":"material:101"}` returns structured material content and text fallback.
- `/api/healthz`, `/api/materials`, and the frontend homepage continue to work.

## PR Gate

Do not open the PR until local validation is green and the local MCP endpoint has been reviewed.
