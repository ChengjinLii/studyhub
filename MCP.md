# StudyHub MCP public access

StudyHub exposes a remote MCP server for public material discovery and referral. It returns public metadata and StudyHub detail-page links. It never returns protected files, direct download URLs, net-disk links, extraction codes, storage keys, preview tokens, or full document text.

## Endpoint

```text
https://study-hub.cn/mcp
```

Transport: MCP Streamable HTTP. Clients should send JSON-RPC requests with `Accept: application/json, text/event-stream` and the negotiated `MCP-Protocol-Version` header.

## Public tools

- `materials.search`: searches public material metadata using StudyHub multi-word matching, the private platform synonym glossary, and weighted field ranking. Inputs can include `query`, `course`, `goal`, `material_type`, school filters, and `limit`.
- `materials.get`: returns safe public metadata for one numeric material ID and its StudyHub detail-page URL.
- `materials.recommend`: recommends public materials for a course, learning goal, time budget, and optional school profile. The external Agent remains responsible for natural-language reasoning.
- `platform.policy`: returns public upload, download, payment, copyright, review, account, and privacy rules with relevant StudyHub links.

No other tools are public. In particular, health checks, operational metrics, admin functions, write operations, request posts, market items, leaderboards, raw OpenAPI resources, MCP resources, and MCP prompts are not exposed by this server.

## Authorization

Production deployments should configure StudyHub as an OAuth 2.1 protected resource. Discover authorization metadata at:

```text
https://study-hub.cn/.well-known/oauth-protected-resource
https://study-hub.cn/.well-known/oauth-protected-resource/mcp
```

When OAuth mode is enabled, the metadata identifies the configured authorization server and the canonical resource identifier `https://study-hub.cn/mcp`. Access tokens must:

- be signed by a key published by the configured JWKS endpoint;
- contain the configured issuer and the exact MCP audience;
- contain `exp`, `iat`, `iss`, `aud`, and `sub` claims;
- identify the OAuth client through `client_id`, `azp`, or `sub`;
- include only the scopes needed by the requested tool.

Public scopes:

- `mcp:materials.search`
- `mcp:materials.read`
- `mcp:materials.recommend`
- `mcp:policy.read`

When authentication is missing or invalid, StudyHub returns `401` with a `WWW-Authenticate` challenge containing `resource_metadata`. A valid token without the required scope receives `403`.

Static Bearer tokens are retained only for local development and migration. New external integrations should use OAuth.

## Quotas and audit

StudyHub applies both IP-level protection and authenticated-client controls. Default client controls are 60 requests per minute and 1,000 requests per 24-hour window; deployment operators can change both values. A limit violation returns `429` and `Retry-After`.

Each MCP request writes a structured audit event containing the request ID, OAuth client ID, authentication method, requested tool, response status, and a hash of the user subject. Tokens, raw subjects, query text, and tool arguments are not written to the audit event.

## Client configuration

Clients that support remote MCP can register the server URL directly:

```json
{
  "mcpServers": {
    "studyhub": {
      "type": "http",
      "url": "https://study-hub.cn/mcp"
    }
  }
}
```

The client discovers the four tools through `tools/list`, obtains user authorization from the advertised OAuth authorization server, and sends the access token in the HTTP `Authorization` header.

Example request after authorization:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "materials.recommend",
    "arguments": {
      "query": "基础一般",
      "course": "通信原理",
      "goal": "两周后期末考试",
      "time_budget": "14 天，每天 2 小时",
      "limit": 5
    }
  }
}
```

The response contains material metadata, recommendation reasons, and URLs such as `https://study-hub.cn/materials/101?ref=mcp`. The user opens that URL and completes login, purchase, quota validation, and download inside StudyHub.

## Protocol references

- [MCP authorization specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization)
- [MCP Streamable HTTP transport](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)
- [OAuth 2.0 Protected Resource Metadata, RFC 9728](https://www.rfc-editor.org/rfc/rfc9728.html)
