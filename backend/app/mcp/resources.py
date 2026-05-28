from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from app.mcp.search import fetch_typed


def register_resources(mcp: FastMCP) -> None:
    @mcp.resource("studyhub://materials/{id}", title="StudyHub Material", mime_type="text/markdown")
    def read_material(id: str) -> str:
        return fetch_typed(f"material:{id}")["text"]

    @mcp.resource("studyhub://requests/{id}", title="StudyHub Request", mime_type="text/markdown")
    def read_request(id: str) -> str:
        return fetch_typed(f"request:{id}")["text"]

    @mcp.resource("studyhub://market/{id}", title="StudyHub Market Item", mime_type="text/markdown")
    def read_market(id: str) -> str:
        return fetch_typed(f"market:{id}")["text"]

    @mcp.resource("studyhub://users/{id}", title="StudyHub User", mime_type="text/markdown")
    def read_user(id: str) -> str:
        return f"# StudyHub 用户 {id}\n\n用户公开主页: https://study-hub.cn/u/{id}"

    @mcp.resource("studyhub://openapi", title="StudyHub OpenAPI", mime_type="text/markdown")
    def read_openapi() -> str:
        return "# StudyHub OpenAPI\n\nFastAPI OpenAPI schema is available at `/openapi.json` on the same host."
