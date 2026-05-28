# StudyHub MCP Gateway Design

Date: 2026-05-28

## Goal

Expose StudyHub read workflows through an MCP endpoint without changing the existing Next.js frontend or `/api/*` REST behavior.

The public MCP endpoint is:

```text
http://127.0.0.1:8011/mcp
```

## Architecture

- Use the official Python MCP SDK with `FastMCP`.
- Run the MCP server in Streamable HTTP mode with `stateless_http=True` and `json_response=True`.
- Register the MCP ASGI app from `backend/app/main.py` after the REST routes, so `/api/*` remains owned by FastAPI routers and `/mcp` is handled by the MCP SDK.
- Keep the v0 tool surface read-only. Mutating and admin capabilities are represented in access metadata but are intentionally not registered as tools yet.

## v0 Capabilities

Read-only tools:

- `search`
- `fetch`
- `materials.search`
- `materials.get`
- `materials.preview`
- `materials.recommend`
- `requests.search`
- `requests.get`
- `requests.leaderboard`
- `market.search`
- `market.get`
- `leaderboard.contributors`
- `health.ready`

Resources:

- `studyhub://materials/{id}`
- `studyhub://requests/{id}`
- `studyhub://market/{id}`
- `studyhub://users/{id}`
- `studyhub://openapi`

Prompts:

- `find_study_materials`
- `summarize_material`
- `compare_materials`
- `draft_material_request`
- `draft_market_listing`
- `admin_review_report`

## Auth And Safety

- Local and test environments allow anonymous read-only MCP calls.
- `STUDYHUB_MCP_ALLOWED_ORIGINS` enables explicit Origin validation for `/mcp`.
- `STUDYHUB_MCP_REQUIRE_AUTH`, `STUDYHUB_MCP_READ_SCOPE`, `STUDYHUB_MCP_WRITE_SCOPE`, and `STUDYHUB_MCP_ADMIN_SCOPE` reserve the auth model for later write/admin tool exposure.
- v0 does not expose mutating tools, so write/admin calls return the SDK's unknown-tool error.

## Compatibility

The gateway reuses the existing service layer for materials, requests, market listings, leaderboards, and readiness. It does not introduce new persistence tables or modify REST route contracts.
